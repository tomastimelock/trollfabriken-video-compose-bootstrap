from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import RectangleOverlay, CircleOverlay, LineOverlay, ArrowOverlay

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


def _png_to_webm(png_path: Path, out_path: Path, dur: float, fps: float, opacity: float) -> None:
    op_filter = f",colorchannelmixer=aa={opacity}" if opacity < 1.0 else ""
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(int(fps)), "-i", str(png_path),
        "-t", str(dur),
        "-vf", f"format=yuva420p{op_filter}",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20", "-an",
        str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"shape ffmpeg encode failed: {r.stderr[-300:]}")


def _parse_color(hex_color: str) -> tuple[int, int, int, int]:
    """Return (R, G, B, A) from a hex color string; 'transparent' → (0,0,0,0)."""
    if hex_color.lower() in ("transparent", "none", ""):
        return (0, 0, 0, 0)
    h = hex_color.lstrip("#")
    if len(h) == 8:
        r, g, b, a = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), int(h[6:8],16)
    elif len(h) == 6:
        r, g, b, a = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), 255
    else:
        r, g, b, a = 255, 255, 255, 255
    return r, g, b, a


def render_rectangle_overlay(ov: "RectangleOverlay", segment_duration, width, height, fps, work_dir, index) -> dict:
    from PIL import Image, ImageDraw
    w_px = int(width * ov.width_pct / 100)
    h_px = int(height * ov.height_pct / 100)
    img = Image.new("RGBA", (w_px, h_px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    fill = _parse_color(ov.color)
    outline = _parse_color(ov.stroke_color) if ov.stroke_color else None
    r = min(ov.border_radius, w_px // 2, h_px // 2)
    rect = [(0, 0), (w_px - 1, h_px - 1)]
    if r > 0:
        draw.rounded_rectangle(rect, radius=r, fill=fill, outline=outline, width=ov.stroke_width or 1)
    else:
        draw.rectangle(rect, fill=fill, outline=outline, width=ov.stroke_width or 1)

    png = work_dir / f"rect_overlay_{index}.png"
    img.save(png)
    out = work_dir / f"rect_overlay_{index}.webm"
    start, end = ov.timing.start, (ov.timing.end or segment_duration)
    _png_to_webm(png, out, end - start, fps, ov.opacity)
    x, y = (_POSITION_TO_XY.get(ov.position, _POSITION_TO_XY["center"])
            if ov.x_pct is None else (str(int(width*ov.x_pct/100)), str(int(height*ov.y_pct/100))))
    return {"path": out, "x": x, "y": y, "start": start, "end": end,
            "keyframes": ov.keyframes, "z_order": ov.z_order, "_is_media_overlay": True}


def render_circle_overlay(ov: "CircleOverlay", segment_duration, width, height, fps, work_dir, index) -> dict:
    from PIL import Image, ImageDraw
    r_px = int(width * ov.radius_pct / 100)
    w_px = r_px * 2
    h_px = int(w_px / ov.aspect)
    img = Image.new("RGBA", (w_px, h_px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fill = _parse_color(ov.color)
    outline = _parse_color(ov.stroke_color) if ov.stroke_color else None
    draw.ellipse([(0, 0), (w_px-1, h_px-1)], fill=fill, outline=outline, width=ov.stroke_width or 1)
    png = work_dir / f"circle_overlay_{index}.png"
    img.save(png)
    out = work_dir / f"circle_overlay_{index}.webm"
    start, end = ov.timing.start, (ov.timing.end or segment_duration)
    _png_to_webm(png, out, end - start, fps, ov.opacity)
    x, y = (_POSITION_TO_XY.get(ov.position, _POSITION_TO_XY["center"])
            if ov.x_pct is None else (str(int(width*ov.x_pct/100)), str(int(height*ov.y_pct/100))))
    return {"path": out, "x": x, "y": y, "start": start, "end": end,
            "keyframes": ov.keyframes, "z_order": ov.z_order, "_is_media_overlay": True}


def render_line_overlay(ov: "LineOverlay", segment_duration, width, height, fps, work_dir, index) -> dict:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x1, y1 = int(width*ov.x1_pct/100), int(height*ov.y1_pct/100)
    x2, y2 = int(width*ov.x2_pct/100), int(height*ov.y2_pct/100)
    color = _parse_color(ov.color)
    draw.line([(x1,y1),(x2,y2)], fill=color, width=ov.width)
    png = work_dir / f"line_overlay_{index}.png"
    img.save(png)
    out = work_dir / f"line_overlay_{index}.webm"
    start, end = ov.timing.start, (ov.timing.end or segment_duration)
    _png_to_webm(png, out, end - start, fps, ov.opacity)
    return {"path": out, "x": "0", "y": "0", "start": start, "end": end,
            "keyframes": None, "z_order": ov.z_order, "_is_media_overlay": True}


def render_arrow_overlay(ov: "ArrowOverlay", segment_duration, width, height, fps, work_dir, index) -> dict:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x1, y1 = int(width*ov.x1_pct/100), int(height*ov.y1_pct/100)
    x2, y2 = int(width*ov.x2_pct/100), int(height*ov.y2_pct/100)
    color = _parse_color(ov.color)
    draw.line([(x1,y1),(x2,y2)], fill=color, width=ov.width)
    _draw_arrowhead(draw, x2, y2, x1, y1, ov.arrowhead_size, color)
    if ov.double_headed:
        _draw_arrowhead(draw, x1, y1, x2, y2, ov.arrowhead_size, color)
    png = work_dir / f"arrow_overlay_{index}.png"
    img.save(png)
    out = work_dir / f"arrow_overlay_{index}.webm"
    start, end = ov.timing.start, (ov.timing.end or segment_duration)
    _png_to_webm(png, out, end - start, fps, ov.opacity)
    return {"path": out, "x": "0", "y": "0", "start": start, "end": end,
            "keyframes": None, "z_order": ov.z_order, "_is_media_overlay": True}


def _draw_arrowhead(draw, tip_x, tip_y, from_x, from_y, size, color):
    angle = math.atan2(tip_y - from_y, tip_x - from_x)
    spread = math.radians(25)
    p1 = (tip_x - size*math.cos(angle-spread), tip_y - size*math.sin(angle-spread))
    p2 = (tip_x - size*math.cos(angle+spread), tip_y - size*math.sin(angle+spread))
    draw.polygon([(tip_x, tip_y), p1, p2], fill=color)
