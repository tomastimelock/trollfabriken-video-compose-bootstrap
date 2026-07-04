from __future__ import annotations

import copy
import logging
import tempfile
from pathlib import Path
from typing import Callable, Any

logger = logging.getLogger(__name__)


class Assembler:
    """Full render pipeline: segment render → overlays → grade → transitions → concat → audio → subtitles.

    Pipeline per segment:
        0. Expand iterated segments (before render loop)
        1. Filter segments by condition
        2. Render segment (via renderers.dispatcher)
        3. Apply overlays — global elements merged first, then per-segment (via overlays.compositor)
        4. Apply per-segment grade (via grade.apply)

    Then global pipeline:
        5. Apply transitions between segments (via transition.apply)
        6. Concatenate all segments
        7. Apply global theme grade (if any)
        8. Mix audio (via audio.pipeline)
        9. Burn subtitles if configured (via audio.subtitles)
    """

    def __init__(
        self,
        spec,
        output_dir: Path | None = None,
        progress_cb: Callable[[str, float], None] | None = None,
    ) -> None:
        self._spec = spec
        self._output_dir = Path(output_dir) if output_dir else None
        self._progress_cb = progress_cb or (lambda msg, pct: None)

    def run(self) -> Path:
        """Execute the full render pipeline. Returns path to the final MP4."""
        spec = self._spec
        output = spec.output

        width = output.width if output else 1920
        height = output.height if output else 1080
        fps = float(output.fps if output else 30)

        grade_slug_global: str | None = None
        if spec.theme:
            grade_slug_global = getattr(spec.theme, "grade", None)

        # Build condition evaluator from spec.variables
        from video_compose.assembler.condition import ConditionEvaluator
        spec_vars = dict(getattr(spec, "variables", {}) or {})
        evaluator = ConditionEvaluator(spec_vars)

        # Global overlay elements (applied to every segment)
        global_elements = list(getattr(spec, "elements", None) or [])

        with tempfile.TemporaryDirectory() as td:
            work_dir = Path(td)

            from video_compose.data import DataResolver
            resolver = DataResolver(spec)

            # ── Phase 0: Expand iterated segments ─────────────────────────────
            from video_compose.assembler.iteration import IterationExpander
            segments = IterationExpander(resolver).expand(list(spec.segments))

            # ── Phase 0b: Filter by condition ─────────────────────────────────
            segments = [seg for seg in segments if evaluator.evaluate(getattr(seg, "condition", None))]

            # ── Phase 1: Render each segment ──────────────────────────────────
            segment_clips: list[Path] = []
            segment_timing: dict[str, float] = {}
            current_time = 0.0

            for i, seg in enumerate(segments):
                self._progress_cb(f"Rendering segment {seg.id}", i / len(segments) * 0.6)
                logger.info("[%d/%d] Rendering segment %r (type=%s)", i + 1, len(segments), seg.id, seg.type)

                segment_timing[seg.id] = current_time

                # 1a. Resolve data ref
                data_ref = getattr(seg, "data", None)
                data = resolver.resolve(data_ref) if data_ref is not None else None

                # 1b. Render the segment content
                clip_path = work_dir / f"seg_{i:03d}_{seg.id}.mp4"
                from video_compose.renderers.dispatcher import dispatch
                dispatch(seg, data, clip_path, width=width, height=height, fps=fps)

                # 1c. Merge global elements + per-segment overlays; apply condition per overlay
                per_seg_overlays = list(getattr(seg, "overlays", None) or [])
                # Global elements get z_order offset so they stack below per-segment overlays by default
                combined_overlays = [
                    _with_z_order_offset(ov, -1000) for ov in global_elements
                ] + per_seg_overlays

                if combined_overlays:
                    from video_compose.overlays.compositor import apply_overlays
                    clip_path = apply_overlays(
                        clip_path, combined_overlays, seg.duration,
                        width, height, fps,
                        condition_evaluator=evaluator,
                    )

                # 1d. Per-segment grade (prefer segment.grade, else global theme grade)
                grade_slug = getattr(seg, "grade", None) or grade_slug_global
                if grade_slug:
                    from video_compose.grade.apply import apply_grade
                    clip_path = apply_grade(clip_path, grade_slug)

                segment_clips.append(clip_path)
                current_time += seg.duration

            total_duration = current_time

            # ── Phase 2: Apply transitions ──────────────────────────────────
            self._progress_cb("Applying transitions", 0.65)
            clips_with_transitions = self._apply_transitions(segment_clips, spec, segments, work_dir)

            # ── Phase 3: Concatenate ─────────────────────────────────────────
            self._progress_cb("Concatenating", 0.75)
            from video_compose.assembler.concat import concat_clips
            silent_video = concat_clips(clips_with_transitions, work_dir / "assembled_silent.mp4")

            # ── Phase 4: Audio ───────────────────────────────────────────────
            self._progress_cb("Mixing audio", 0.85)
            from video_compose.audio.pipeline import AudioPipeline

            if self._output_dir:
                self._output_dir.mkdir(parents=True, exist_ok=True)
                final_path = self._output_dir / "output.mp4"
            else:
                final_path = work_dir / "final.mp4"

            audio_pipeline = AudioPipeline()
            final_video = audio_pipeline.run(
                spec=spec,
                video_path=silent_video,
                segment_timing=segment_timing,
                total_duration=total_duration,
                work_dir=work_dir,
                output_path=work_dir / "final_with_audio.mp4",
            )

            # ── Phase 5: Subtitles ───────────────────────────────────────────
            subtitle_cfg = getattr(spec, "subtitles", None)
            if subtitle_cfg is not None:
                self._progress_cb("Burning subtitles", 0.93)
                from video_compose.audio.subtitles import apply_subtitles
                subtitled = work_dir / "final_subtitled.mp4"
                try:
                    final_video = apply_subtitles(final_video, subtitle_cfg, work_dir, subtitled)
                except Exception as exc:
                    logger.error("Subtitle pass failed: %s — skipping subtitles", exc)

            # Copy final to output_dir
            import shutil
            shutil.copy2(final_video, final_path)

        self._progress_cb("Done", 1.0)
        logger.info("Render complete: %s", final_path)
        return final_path

    def render_segment_preview(self, segment_id: str, output_path: Path | None = None) -> Path:
        """Render a single segment to a temporary file for preview."""
        spec = self._spec
        seg = next((s for s in spec.segments if s.id == segment_id), None)
        if seg is None:
            raise ValueError(f"No segment with id {segment_id!r}")

        output = spec.output
        width = output.width if output else 1920
        height = output.height if output else 1080
        fps = float(output.fps if output else 30)

        if output_path is None:
            import tempfile
            tf = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            output_path = Path(tf.name)
            tf.close()

        from video_compose.data import DataResolver
        resolver = DataResolver(spec)
        data_ref = getattr(seg, "data", None)
        data = resolver.resolve(data_ref) if data_ref is not None else None

        from video_compose.renderers.dispatcher import dispatch
        dispatch(seg, data, output_path, width=width, height=height, fps=fps)

        return output_path

    def _apply_transitions(
        self,
        clips: list[Path],
        spec,
        segments: list,
        work_dir: Path,
    ) -> list[Path]:
        """Apply transitions between consecutive clips."""
        if len(clips) <= 1:
            return clips

        from video_compose.transition.apply import apply_transition

        transitions_block = getattr(spec, "transitions", None)
        default_ref = transitions_block.default if transitions_block else None
        overrides_list = (transitions_block.overrides or []) if transitions_block else []

        override_map: dict[tuple[str, str], Any] = {}
        for ov in overrides_list:
            override_map[(ov.from_segment, ov.to)] = ov

        result_clips = [clips[0]]

        for i in range(len(clips) - 1):
            from_id = segments[i].id
            to_id = segments[i + 1].id
            transition_config = override_map.get((from_id, to_id), default_ref)

            joined = work_dir / f"joined_{i:03d}_{i+1:03d}.mp4"
            try:
                joined_path = apply_transition(result_clips[-1], clips[i + 1], transition_config, joined)
                result_clips[-1] = joined_path
            except Exception as exc:
                logger.warning("Transition %d→%d failed: %s — using hard cut", i, i + 1, exc)
                result_clips.append(clips[i + 1])

        return result_clips


def _with_z_order_offset(overlay, offset: int):
    """Return overlay with z_order shifted by offset (to push global elements below per-segment)."""
    if not hasattr(overlay, "z_order"):
        return overlay
    clone = copy.copy(overlay)
    try:
        object.__setattr__(clone, "z_order", overlay.z_order + offset)
    except Exception:
        pass
    return clone
