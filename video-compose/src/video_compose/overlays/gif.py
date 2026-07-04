from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import GifOverlay

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


def render_gif_overlay(
    ov: "GifOverlay",
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    work_dir: Path,
    index: int,
) -> dict:
    """Convert an animated GIF to a yuva420p WebM with proper loop support."""
    src = Path(ov.src)
    if not src.exists():
        raise FileNotFoundError(f"GIF not found: {src}")

    out = work_dir / f"gif_overlay_{index}.webm"
    start = ov.timing.start
    end = ov.timing.end if ov.timing.end is not None else segment_duration
    dur = max(end - start, 0.1)

    scale_filter = _build_scale(ov, width, height)
    speed_filter = f",setpts=PTS/{ov.speed}" if ov.speed != 1.0 else ""
    opacity_filter = f",colorchannelmixer=aa={ov.opacity}" if ov.opacity < 1.0 else ""

    vf = f"{scale_filter}{speed_filter},format=yuva420p{opacity_filter}"

    loop_args = ["-stream_loop", "-1", "-ignore_loop", "0"] if ov.loop else []

    cmd = [
        "ffmpeg", "-y",
        *loop_args,
        "-i", str(src),
        "-t", str(dur),
        "-r", str(int(fps)),
        "-vf", vf,
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20",
        "-an", str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"GIF overlay ffmpeg failed: {r.stderr[-400:]}")

    x, y = (_POSITION_TO_XY.get(ov.position, _POSITION_TO_XY["center"])
            if ov.x_pct is None else (str(int(width*ov.x_pct/100)), str(int(height*ov.y_pct/100))))
    return {"path": out, "x": x, "y": y, "start": start, "end": end,
            "keyframes": None, "z_order": ov.z_order, "_is_media_overlay": True}


def _build_scale(ov: "GifOverlay", width: int, height: int) -> str:
    if ov.width_pct and ov.height_pct:
        return f"scale={int(width*ov.width_pct/100)}:{int(height*ov.height_pct/100)}"
    if ov.width_pct:
        return f"scale={int(width*ov.width_pct/100)}:-1"
    if ov.height_pct:
        return f"scale=-1:{int(height*ov.height_pct/100)}"
    return "scale=iw:ih"
