from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from video_compose._fonts import resolve_font_family


def _position_to_textfx(position: str, height: int) -> tuple:
    """Map a TVCS position string to a text-fx (x, y) position tuple."""
    lower_y = int(height * 0.76)
    lower2_y = int(height * 0.84)  # second lower-third row (stacked elements)
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
        "lower_third_2":     ("center", lower2_y),
    }
    return mapping.get(position, ("center", "center"))


def _auto_font_size(text: str, base_size: int) -> int:
    """Scale font size continuously with text length to prevent overflow."""
    n = len(text)
    if n <= 20:
        return base_size
    # Linear ramp: 1.0 at n=20, 0.55 at n=120; clamped at 0.55 below 18px
    scale = max(0.55, 1.0 - (n - 20) * (0.45 / 100))
    return max(18, int(base_size * scale))


def _height_scaled_font(height: int, role: str = "body") -> int:
    """Return a font size proportional to video height for the given role.

    Broadcast-standard sizing:
        title   : ~6.7% of height  (72px @ 1080p, 48px @ 720p)
        subtitle: ~5.0% of height  (54px @ 1080p, 36px @ 720p)
        body    : ~3.7% of height  (40px @ 1080p, 27px @ 720p)
        caption : ~2.8% of height  (30px @ 1080p, 20px @ 720p)
    """
    scales = {"title": 0.067, "subtitle": 0.050, "body": 0.037, "caption": 0.028}
    factor = scales.get(role, 0.050)
    return max(18, int(height * factor))


def render_text_overlay(
    overlay,
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    output_dir: Path,
    index: int,
) -> dict:
    """Render a TextOverlay to a full-canvas WebM clip.

    Returns dict: path, start, end, x (always '0'), y (always '0').
    text-fx positions the text within the full-canvas clip; the compositor
    then keys out the black background (VP9 yuva420p alpha not available on
    all ffmpeg builds, so we use colorkey instead).
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

    # Detect star rating pattern — render PIL circles instead of going through text-fx
    from video_compose.overlays.stars import parse_star_rating, render_star_rating
    star = parse_star_rating(overlay.text)
    if star is not None:
        filled, total = star
        return render_star_rating(
            filled=filled,
            total=total,
            color=overlay.color or "#f5c518",
            width=width,
            height=height,
            duration=duration,
            fps=fps,
            output=out_path,
        )

    # Font size: explicit > role field > intensity heuristic. Scale to height, never hardcoded.
    if overlay.font_size:
        base_font = overlay.font_size
    else:
        explicit_role = getattr(overlay, "role", None)
        if explicit_role:
            role = explicit_role if explicit_role != "label" else "caption"
        else:
            intensity = float(getattr(overlay, "intensity", 1.0))
            if intensity >= 1.4:
                role = "title"
            elif intensity >= 1.1:
                role = "subtitle"
            elif intensity >= 0.8:
                role = "body"
            else:
                role = "caption"
        base_font = _height_scaled_font(height, role)

    font_size = _auto_font_size(overlay.text, base_font)

    position = _position_to_textfx(overlay.position, height)

    font_family  = resolve_font_family(
        getattr(overlay, "font_family", "Inter"),
        weight=getattr(overlay, "font_weight", "bold"),
    )
    stroke_color = getattr(overlay, "stroke_color",  None)
    stroke_width = getattr(overlay, "stroke_width",  0)
    shadow       = getattr(overlay, "shadow",        True)
    intensity    = float(getattr(overlay, "intensity", 1.0))
    _margin_x    = getattr(overlay, "margin_x",      None)
    _margin_y    = getattr(overlay, "margin_y",      None)
    margin_x     = _margin_x if _margin_x is not None else max(60, int(width  * 0.05))
    margin_y     = _margin_y if _margin_y is not None else max(50, int(height * 0.05))
    font_weight  = getattr(overlay, "font_weight",   "bold")
    easing       = getattr(overlay, "easing",        "ease-out-cubic")

    # Strip any unicode that reliably fails in PIL (e.g. star chars map to empty glyph)
    safe_text = _sanitize_text(overlay.text)

    shadow_dx      = getattr(overlay, "shadow_dx",      0)
    shadow_dy      = getattr(overlay, "shadow_dy",      4)
    shadow_blur_v  = getattr(overlay, "shadow_blur",    8)
    shadow_opacity = getattr(overlay, "shadow_opacity", 0.5)
    max_width_pct  = getattr(overlay, "max_width_pct",  None)
    text_align     = getattr(overlay, "text_align",     "center")

    config_kwargs: dict[str, Any] = {
        "font_size":      font_size,
        "color":          overlay.color or "#ffffff",
        "font_family":    font_family,
        "font_weight":    font_weight,
        "position":       position,
        "margin_x":       margin_x,
        "margin_y":       margin_y,
        "shadow_enabled": shadow,
        "shadow_offset":  (int(shadow_dx), int(shadow_dy)),
        "shadow_blur":    int(shadow_blur_v),
        "shadow_opacity": float(shadow_opacity),
        "intensity":      intensity,
        "easing":         easing,
        "text_align":     text_align,
    }
    if max_width_pct is not None:
        config_kwargs["max_width_pct"] = float(max_width_pct)
    if stroke_color:
        config_kwargs["stroke_color"] = stroke_color
        config_kwargs["stroke_width"] = max(1, int(stroke_width))
    elif stroke_width:
        config_kwargs["stroke_width"] = int(stroke_width)

    try:
        config = TextEffectConfig(**config_kwargs)
    except Exception:
        config = TextEffectConfig(
            font_size=font_size,
            color=overlay.color or "#ffffff",
        )

    aa_mode = getattr(overlay, "aa_mode", "none")

    if aa_mode == "supersample":
        # Render at 2× resolution, then LANCZOS-downscale to target size.
        # Eliminates sub-pixel aliasing on text edges and motion stutter.
        tmp_path = out_path.with_stem(out_path.stem + "_2x")
        render_overlay(
            text=safe_text,
            effect=overlay.effect,
            width=width * 2,
            height=height * 2,
            duration=duration,
            fps=int(fps),
            output=tmp_path,
            config=config,
        )
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(tmp_path),
                "-vf", f"scale={width}:{height}:flags=lanczos",
                "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-b:v", "0", "-crf", "10",
                str(out_path),
            ],
            capture_output=True, text=True,
        )
        try:
            tmp_path.unlink()
        except OSError:
            pass
        if result.returncode != 0:
            raise RuntimeError(f"Supersample downscale failed: {result.stderr[-300:]}")
    else:
        render_overlay(
            text=safe_text,
            effect=overlay.effect,
            width=width,
            height=height,
            duration=duration,
            fps=int(fps),
            output=out_path,
            config=config,
        )

    return {"path": out_path, "start": start, "end": end, "x": "0", "y": "0"}


def _sanitize_text(text: str) -> str:
    """Replace unicode characters that cause blank glyph rendering in PIL.

    Star chars (★ ☆ ✩ etc.) map to empty glyphs in most system fonts,
    producing a white fallback rectangle in the rendered overlay.
    Replace with ASCII equivalents.
    """
    replacements = {
        "★": "*",
        "☆": "*",
        "✩": "*",
        "✦": "*",
        "✧": "*",
        "•": "-",
        "→": "->",
        "←": "<-",
        "↑": "^",
        "↓": "v",
        "…": "...",
        "’": "'",  # right single quote
        "‘": "'",  # left single quote
        "“": '"',  # left double quote
        "”": '"',  # right double quote
        "„": '"',       # German open quote
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text
