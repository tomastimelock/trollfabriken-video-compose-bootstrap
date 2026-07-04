from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


_POSITION_Y: dict[str, str] = {
    "top":               "top",
    "center":            "center",
    "bottom":            "bottom",
    "lower_third":       "lower_third",
    "lower_third_left":  "lower_third",
    "lower_third_right": "lower_third",
    "lower_third_2":     "lower_third_2",
}


def render_bar_overlay(
    overlay,
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    output_dir: Path,
    index: int,
) -> dict:
    """Render a BarOverlay (solid background strip/pill) to a full-canvas WebM.

    Returns overlay dict: path, start, end, x='0', y='0'.
    """
    start = overlay.timing.start
    end = overlay.timing.end if overlay.timing.end is not None else segment_duration
    duration = max(end - start, 0.1)
    out_path = output_dir / f"bar_overlay_{index}.webm"

    bar_w = max(1, int(width * overlay.width_pct / 100.0))
    bar_h = max(1, int(height * overlay.height_pct / 100.0))

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    r, g, b = _hex_to_rgb(overlay.color)
    alpha = int(overlay.opacity * 255)
    fill = (r, g, b, alpha)

    # Compute vertical position
    pos = overlay.position
    if pos in ("top",):
        y0 = 0
    elif pos == "center":
        y0 = (height - bar_h) // 2
    elif pos == "bottom":
        y0 = height - bar_h
    elif pos in ("lower_third", "lower_third_left", "lower_third_right"):
        y0 = int(height * 0.72)
    elif pos == "lower_third_2":
        y0 = int(height * 0.82)
    else:
        y0 = height - bar_h

    x0 = (width - bar_w) // 2
    x1 = x0 + bar_w
    y1 = y0 + bar_h

    radius = min(overlay.border_radius, bar_h // 2, bar_w // 2)
    if radius > 0:
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=fill)
    else:
        draw.rectangle([x0, y0, x1, y1], fill=fill)

    with tempfile.TemporaryDirectory() as tmpdir:
        png_path = Path(tmpdir) / "bar.png"
        canvas.save(png_path)
        total_frames = max(1, int(duration * fps))
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-framerate", str(fps),
            "-i", str(png_path),
            "-t", str(duration),
            "-frames:v", str(total_frames),
            "-vf", "premultiply=inplace=1,format=yuv420p",
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-b:v", "0", "-crf", "10",
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Bar overlay encode failed: {result.stderr[-300:]}")

    return {"path": out_path, "start": start, "end": end, "x": "0", "y": "0"}


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
