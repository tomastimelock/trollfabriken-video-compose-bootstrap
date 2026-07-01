from __future__ import annotations

import subprocess
from pathlib import Path


def remux_mp4(source: Path, output: Path, *, width: int, height: int, fps: float) -> Path:
    """Re-encode *source* to a clean H.264 MP4 at the specified resolution and fps."""
    cmd = [
        "ffmpeg", "-y", "-i", str(source),
        "-vf", f"scale={width}:{height}",
        "-r", str(fps),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
        "-c:a", "copy",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"remux failed: {result.stderr[:500]}")
    return output
