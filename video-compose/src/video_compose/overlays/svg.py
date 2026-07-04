from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import SvgOverlay

_POSITION_TO_XY = {
    "center":            ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
    "top":               ("(main_w-overlay_w)/2", "0"),
    "bottom":            ("(main_w-overlay_w)/2", "main_h-overlay_h"),
    "top-left":          ("0", "0"),
    "top-right":         ("main_w-overlay_w", "0"),
    "bottom-left":       ("0", "main_h-overlay_h"),
    "bottom-right":      ("main_w-overlay_w", "main_h-overlay_h"),
    "left":              ("0", "(main_h-overlay_h)/2"),
    "right":             ("main_w-overlay_w", "(main_h-overlay_h)/2"),
    "lower_third":       ("(main_w-overlay_w)/2", "main_h*0.78"),
    "lower_third_left":  ("main_w*0.05", "main_h*0.78"),
    "lower_third_right": ("main_w*0.95-overlay_w", "main_h*0.78"),
    "lower_third_2":     ("(main_w-overlay_w)/2", "main_h*0.86"),
}


def render_svg_overlay(
    ov: "SvgOverlay",
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    work_dir: Path,
    index: int,
) -> dict:
    """Render an SvgOverlay to a WebM with alpha channel.

    Uses cairosvg to rasterise the SVG to a PNG preserving transparency, then
    ffmpeg loops the PNG to a yuva420p WebM for the overlay duration.
    Returns a layer dict with _is_media_overlay=True so the compositor skips colorkey.
    """
    svg_content = _resolve_svg(ov)
    png_path = work_dir / f"svg_overlay_{index}.png"
    out_path = work_dir / f"svg_overlay_{index}.webm"

    start = ov.timing.start
    end = ov.timing.end if ov.timing.end is not None else segment_duration
    dur = max(end - start, 0.1)

    target_w, target_h = _target_size(ov, width, height)
    _rasterise(svg_content, png_path, target_w, target_h)

    opacity_filter = f",colorchannelmixer=aa={ov.opacity}" if ov.opacity < 1.0 else ""

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(int(fps)),
        "-i", str(png_path),
        "-t", str(dur),
        "-vf", f"format=yuva420p{opacity_filter}",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20",
        "-an", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"SVG ffmpeg encode failed: {result.stderr[-400:]}")

    x, y = _xy(ov, width, height)
    return {
        "path": out_path, "x": x, "y": y,
        "start": start, "end": end,
        "keyframes": None, "z_order": ov.z_order,
        "_is_media_overlay": True,
    }


def _resolve_svg(ov: "SvgOverlay") -> str:
    if ov.content:
        return ov.content
    p = Path(ov.src)
    if not p.exists():
        raise FileNotFoundError(f"SVG file not found: {p}")
    return p.read_text(encoding="utf-8")


def _target_size(ov: "SvgOverlay", canvas_w: int, canvas_h: int) -> tuple[int, int]:
    if ov.width_pct and ov.height_pct:
        return int(canvas_w * ov.width_pct / 100), int(canvas_h * ov.height_pct / 100)
    if ov.width_pct:
        w = int(canvas_w * ov.width_pct / 100)
        return w, w  # cairosvg preserves aspect when only one dim given
    if ov.height_pct:
        h = int(canvas_h * ov.height_pct / 100)
        return h, h
    return canvas_w, canvas_h


def _rasterise(svg_content: str, out_path: Path, w: int, h: int) -> None:
    try:
        import cairosvg
        png_bytes = cairosvg.svg2png(
            bytestring=svg_content.encode(),
            output_width=w,
            output_height=h,
        )
        out_path.write_bytes(png_bytes)
        return
    except ImportError:
        pass

    # Fallback: Inkscape CLI
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False, mode="w", encoding="utf-8") as f:
        f.write(svg_content)
        svg_tmp = f.name
    cmd = ["inkscape", "--export-type=png", f"--export-filename={out_path}",
           f"--export-width={w}", f"--export-height={h}", svg_tmp]
    result = subprocess.run(cmd, capture_output=True, text=True)
    Path(svg_tmp).unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(
            "cairosvg is not installed and Inkscape fallback failed. "
            "Install cairosvg: pip install cairosvg"
        )


def _xy(ov: "SvgOverlay", width: int, height: int) -> tuple[str, str]:
    if ov.x_pct is not None and ov.y_pct is not None:
        return str(int(width * ov.x_pct / 100)), str(int(height * ov.y_pct / 100))
    return _POSITION_TO_XY.get(ov.position, _POSITION_TO_XY["center"])
