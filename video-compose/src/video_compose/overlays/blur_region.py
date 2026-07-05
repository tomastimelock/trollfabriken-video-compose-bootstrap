from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import BlurRegionOverlay


def render_blur_region_overlay(
    ov: "BlurRegionOverlay",
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    work_dir: Path,
    index: int,
    clip_path: Path,
) -> dict:
    """Crop the specified region from clip_path, blur/pixelate it, pad back to canvas.

    Returns a full-canvas yuva420p WebM where only the blur region has content
    (transparent elsewhere), so the compositor overlays it on the base video
    — effectively replacing just that region with the blurred version.
    """
    start = ov.timing.start
    end = ov.timing.end if ov.timing.end is not None else segment_duration
    dur = max(end - start, 0.1)

    # Pixel coordinates (must be even for yuv420p)
    x = int(width * ov.x_pct / 100)
    y = int(height * ov.y_pct / 100)
    w = max(2, int(width * ov.width_pct / 100))
    h = max(2, int(height * ov.height_pct / 100))
    x = x - (x % 2)
    y = y - (y % 2)
    w = w + (w % 2)
    h = h + (h % 2)
    # Clamp to canvas
    w = min(w, width - x)
    h = min(h, height - y)

    if ov.pixelate:
        block = max(4, ov.radius // 2)
        region_filter = (
            f"crop={w}:{h}:{x}:{y},"
            f"scale=iw/{block}:ih/{block}:flags=neighbor,"
            f"scale={w}:{h}:flags=neighbor"
        )
    else:
        r = ov.radius
        region_filter = f"crop={w}:{h}:{x}:{y},boxblur={r}:{r}"

    # Pad blurred region back to full canvas with transparent edges
    pad_filter = f"pad={width}:{height}:{x}:{y}:color=black@0"
    vf = f"{region_filter},{pad_filter},format=yuva420p"

    out = work_dir / f"blur_region_{index}.webm"
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(clip_path),
        "-t", str(dur),
        "-vf", vf,
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20", "-an",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"blur_region ffmpeg failed: {result.stderr[-400:]}")

    return {
        "path": out,
        "x": "0", "y": "0",
        "start": start, "end": end,
        "keyframes": None,
        "z_order": ov.z_order,
        "_is_media_overlay": True,
    }
