from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import AutoCaptionOverlay


def render_auto_caption_overlay(
    ov: "AutoCaptionOverlay",
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    work_dir: Path,
    index: int,
) -> dict:
    """Transcribe source audio then render kinetic word-highlight captions."""
    from video_compose.audio.transcription import transcribe, WordTiming as TransWordTiming
    from video_compose.schema.spec import WordHighlightOverlay, OverlayTiming, WordTiming as SchemaWordTiming

    start = ov.timing.start
    end_time = ov.timing.end if ov.timing.end is not None else segment_duration

    result = transcribe(ov.source, language=ov.language)

    words = result.words
    if not words:
        # No speech detected — skip gracefully
        raise ValueError(f"auto_caption: no speech detected in {ov.source!r}")

    schema_timings = [
        SchemaWordTiming(
            word=w.word,
            start=round(w.start, 3),
            end=round(w.end, 3),
        )
        for w in words
    ]

    # Build a duck-typed WordHighlightOverlay
    from types import SimpleNamespace
    wh_ov = SimpleNamespace(
        type="word_highlight",
        words=[w.word for w in words],
        word_timings=schema_timings,
        style=ov.style,
        position=ov.position,
        font_family=ov.font_family,
        font_size_pct=ov.font_size_pct,
        text_color=ov.text_color,
        highlight_color=ov.highlight_color,
        highlight_bg=ov.highlight_bg,
        opacity=ov.opacity,
        z_order=ov.z_order,
        timing=ov.timing,
    )

    from video_compose.overlays.word_highlight import render_word_highlight_overlay
    return render_word_highlight_overlay(wh_ov, segment_duration, width, height, fps, work_dir, index)
