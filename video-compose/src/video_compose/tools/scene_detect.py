from __future__ import annotations

import subprocess
import re
from pathlib import Path


def detect_scenes(
    video_path: str | Path,
    threshold: float = 0.3,
) -> list[float]:
    """Return list of scene-change timestamps (seconds) in *video_path*.

    Uses ffmpeg showinfo filter to find frames where scene score > threshold.
    """
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-vsync", "vfr", "-f", "null", "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    timestamps: list[float] = [0.0]
    for line in r.stderr.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
            if t > 0.05 and (not timestamps or t - timestamps[-1] > 0.1):
                timestamps.append(t)
    return sorted(set(timestamps))
