from __future__ import annotations

from pathlib import Path
from typing import Any


def _position_to_textfx(position: str, height: int) -> tuple:
    """Map a TVCS position string to a text-fx (x, y) position tuple."""
    lower_y = int(height * 0.76)
    mapping: dict[str, tuple] = {
        "center":            ("center", "center"),
        "top":               ("center", "top"),
        "bottom":            ("center", "bottom"),
        "top-left":          ("left",   "top"),
        "top-right":         ("right",  "top"),
        "bottom-left":       ("left",   "bottom"),
        "bottom-right":      ("right",  "bottom"),
        "left":              ("left",   "center"),
        "right":             ("right",  "center"),
        "lower_third":       ("center", lower_y),
        "lower_third_left":  ("left",   lower_y),
        "lower_third_right": ("right",  lower_y),
    }
    return mapping.get(position, ("center", "center"))


def _auto_font_size(text: str, base_size: int) -> int:
    """Scale font size down for longer texts to prevent overflow."""
    n = len(text)
    if n <= 20:
        return base_size
    if n <= 40:
        return max(24, int(base_size * 0.80))
    if n <= 70:
        return max(20, int(base_size * 0.65))
    return max(18, int(base_size * 0.55))


def render_text_overlay(
    overlay,
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    output_dir: Path,
    index: int,
) -> dict:
    """Render a TextOverlay to a full-canvas transparent WebM clip.

    Returns dict: path, start, end, x (always '0'), y (always '0').
    text-fx positions the text within the full-canvas transparent clip.
    """
    try:
        from text_fx import render_overlay
        from text_fx import TextEffectConfig
    except ImportError as exc:
        raise RuntimeError(
            "text-fx is required for text overlays — pip install text-fx"
        ) from exc

    start = overlay.timing.start
    end = overlay.timing.end if overlay.timing.end is not None else segment_duration
    duration = max(end - start, 0.1)

    out_path = output_dir / f"text_overlay_{index}.webm"

    # Base font size — auto-scale if not explicitly set
    base_font = overlay.font_size or 72
    font_size = _auto_font_size(overlay.text, base_font)

    # Position within the full-canvas clip
    position = _position_to_textfx(overlay.position, height)

    # Pull extended fields (all optional with defaults in schema)
    font_family  = getattr(overlay, "font_family",   "Inter")
    stroke_color = getattr(overlay, "stroke_color",  None)
    stroke_width = getattr(overlay, "stroke_width",  0)
    shadow       = getattr(overlay, "shadow",        True)
    intensity    = getattr(overlay, "intensity",     1.0)
    margin_x     = getattr(overlay, "margin_x",      60)
    margin_y     = getattr(overlay, "margin_y",      50)
    font_weight  = getattr(overlay, "font_weight",   "bold")

    config_kwargs: dict[str, Any] = {
        "font_size":      font_size,
        "color":          overlay.color or "#ffffff",
        "font_family":    font_family,
        "font_weight":    font_weight,
        "position":       position,
        "margin_x":       margin_x,
        "margin_y":       margin_y,
        "shadow_enabled": shadow,
        "intensity":      float(intensity),
    }
    if stroke_color:
        config_kwargs["stroke_color"] = stroke_color
        config_kwargs["stroke_width"] = max(1, int(stroke_width))
    elif stroke_width:
        config_kwargs["stroke_width"] = int(stroke_width)

    try:
        config = TextEffectConfig(**config_kwargs)
    except Exception:
        # Fallback: minimal config if extended fields cause validation issues
        config = TextEffectConfig(
            font_size=font_size,
            color=overlay.color or "#ffffff",
        )

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

    # The WebM is full W×H — compositor overlays it at (0,0)
    return {"path": out_path, "start": start, "end": end, "x": "0", "y": "0"}
