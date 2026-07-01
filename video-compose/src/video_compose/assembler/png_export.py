from __future__ import annotations

import subprocess
from pathlib import Path


def export_frames(video_path: Path, output_dir: Path, fps: float | None = None) -> list[Path]:
    """Extract all frames from *video_path* as PNG files in *output_dir*.

    Args:
        video_path: Source MP4.
        output_dir: Directory to write PNG frames.
        fps:        If set, extract at this rate; otherwise extract every frame.

    Returns:
        Sorted list of Path objects for the extracted PNGs.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    vf_args = []
    if fps is not None:
        vf_args = ["-vf", f"fps={fps}"]

    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        *vf_args,
        str(output_dir / "frame_%06d.png"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"PNG export failed: {result.stderr[:500]}")

    return sorted(output_dir.glob("frame_*.png"))
