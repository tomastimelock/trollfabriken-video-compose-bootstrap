from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class AudioPipeline:
    """Orchestrates voiceover generation and audio mixing for a render session."""

    def run(
        self,
        spec,
        video_path: Path,
        segment_timing: dict[str, float],
        total_duration: float,
        work_dir: Path,
        output_path: Path,
    ) -> Path:
        """Generate voiceover if configured, then mix all audio onto *video_path*.

        Returns:
            Path to the final video (with audio) at *output_path*, or *video_path*
            unchanged if no audio is configured.
        """
        from video_compose.audio.voiceover import VoiceoverEngine
        from video_compose.audio.mixer import AudioMixer

        audio_config = spec.audio if spec.audio else None
        if not audio_config:
            return video_path

        has_tracks = bool(getattr(audio_config, "tracks", None))
        has_voiceover = audio_config.voiceover is not None

        if not has_tracks and not has_voiceover:
            return video_path

        # Generate voiceover audio (per-segment or manual)
        vo_clips: dict[str, Path] = {}
        if has_voiceover:
            try:
                engine = VoiceoverEngine(audio_config.voiceover)
                vo_clips = engine.generate_all(spec.segments, work_dir)
                logger.info("Voiceover: generated %d clip(s)", len(vo_clips))
            except Exception as exc:
                logger.warning("Voiceover generation failed, continuing without: %s", exc)

        # Mix everything onto the video
        mixer = AudioMixer()
        try:
            return mixer.mix_onto_video(
                video_path=video_path,
                spec=spec,
                segment_timing=segment_timing,
                voiceover_clips=vo_clips,
                total_duration=total_duration,
                output_path=output_path,
            )
        except Exception as exc:
            logger.warning("Audio mixing failed, returning silent video: %s", exc)
            return video_path
