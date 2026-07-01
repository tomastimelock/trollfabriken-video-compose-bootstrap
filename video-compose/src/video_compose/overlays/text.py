from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any


_POSITION_MAP = {
    "center":       ("(W-w)/2", "(H-h)/2"),
    "top":          ("(W-w)/2", "20"),
    "bottom":       ("(W-w)/2", "H-h-20"),
    "top-left":     ("20",      "20"),
    "top-right":    ("W-w-20",  "20"),
    "bottom-left":  ("20",      "H-h-20"),
    "bottom-right": ("W-w-20",  "H-h-20"),
}


def render_text_overlay(
    overlay,
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    output_dir: Path,
    index: int,
) -> dict:
    """Render a TextOverlay to a transparent WebM/RGBA video clip.

    Returns:
        dict with keys: path (Path), start (float), end (float), position (tuple[str,str])
    """
    try:
        from text_fx import render_overlay
    except ImportError as exc:
        raise RuntimeError(
            "text-fx is required for text overlays — pip install text-fx"
        ) from exc

    start = overlay.timing.start
    end = overlay.timing.end if overlay.timing.end is not None else segment_duration
    duration = max(end - start, 0.1)

    out_path = output_dir / f"text_overlay_{index}.webm"

    config_kwargs: dict[str, Any] = {}
    if overlay.font_size:
        config_kwargs["font_size"] = overlay.font_size
    if overlay.color:
        config_kwargs["color"] = overlay.color
    if overlay.bold:
        config_kwargs["bold"] = overlay.bold

    try:
        from text_fx import TextEffectConfig
        config = TextEffectConfig(**config_kwargs) if config_kwargs else None
    except Exception:
        config = None

    render_overlay(
        text=overlay.text,
        effect=overlay.effect,
        width=width,
        height=height,
        duration=duration,
        fps=int(fps),
        output=out_path,
        config=config,
    )

    x_expr, y_expr = _POSITION_MAP.get(overlay.position, ("(W-w)/2", "(H-h)/2"))
    return {"path": out_path, "start": start, "end": end, "x": x_expr, "y": y_expr}
