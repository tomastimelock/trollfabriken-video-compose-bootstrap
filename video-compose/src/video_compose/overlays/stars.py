from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

_STAR_RE = re.compile(r"^[★☆✩✦✧]+$")


def parse_star_rating(text: str) -> tuple[float, int] | None:
    """Return (filled_count, total) if text is a star pattern, else None.

    Supports: '★★★★★', '★★★★☆', '4/5', '4.5/5'.
    """
    t = text.strip()
    if _STAR_RE.match(t):
        filled = t.count("★") + t.count("✩") + t.count("✦") + t.count("✧")
        total = len(t)
        return float(filled), total
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*/\s*(\d+)", t)
    if m:
        return float(m.group(1)), int(m.group(2))
    return None


def render_star_rating(
    filled: float,
    total: int,
    color: str,
    width: int,
    height: int,
    duration: float,
    fps: float,
    output: Path,
    *,
    circle_radius_pct: float = 0.025,
    gap_pct: float = 0.012,
    y_pct: float = 0.10,
) -> dict:
    """Render filled/empty circles as a PIL image encoded to WebM.

    Args:
        filled: Number of filled circles (may be fractional — rounds to nearest 0.5).
        total: Total circle count.
        color: Hex color for filled circles (empty ones drawn at 30% opacity).
        width/height: Canvas size.
        duration/fps: Output video params.
        output: Destination .webm path.
        circle_radius_pct: Circle radius as fraction of width.
        gap_pct: Gap between circles as fraction of width.
        y_pct: Vertical centre of the rating strip as fraction of height.

    Returns:
        Overlay dict: path, start, end, x, y.
    """
    r = max(8, int(width * circle_radius_pct))
    gap = max(4, int(width * gap_pct))
    total_w = total * (2 * r) + (total - 1) * gap
    strip_h = 2 * r + 4

    strip = Image.new("RGBA", (total_w, strip_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(strip)

    fill_rgb = _hex_to_rgb(color)
    dim_rgba = fill_rgb + (77,)  # ~30% opacity for empty circles

    for i in range(total):
        x0 = i * (2 * r + gap)
        y0 = 2
        x1 = x0 + 2 * r
        y1 = y0 + 2 * r
        if i < int(filled):
            draw.ellipse([x0, y0, x1, y1], fill=fill_rgb + (255,), outline=fill_rgb + (255,))
        else:
            draw.ellipse([x0, y0, x1, y1], fill=dim_rgba, outline=fill_rgb + (180,), width=2)

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    px = (width - total_w) // 2
    py = int(height * y_pct) - r
    canvas.paste(strip, (max(0, px), max(0, py)), strip)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir) / "star.png"
        canvas.save(tmp)
        total_frames = max(1, int(duration * fps))
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-framerate", str(fps),
            "-i", str(tmp),
            "-t", str(duration),
            "-frames:v", str(total_frames),
            "-vf", "premultiply=inplace=1,format=yuv420p",
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-b:v", "0", "-crf", "10",
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Star rating WebM encode failed: {result.stderr[-300:]}")

    return {"path": output, "start": 0.0, "end": duration, "x": "0", "y": "0"}


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return r, g, b
