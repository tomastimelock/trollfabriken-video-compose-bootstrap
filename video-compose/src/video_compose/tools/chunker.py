from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from video_compose.tools.scene_detect import detect_scenes


def chunk_by_scene(
    video_path: str | Path,
    output_dir: str | Path,
    threshold: float = 0.3,
    min_chunk_duration: float = 2.0,
) -> list[Path]:
    """Split video at scene boundaries. Returns list of output clip paths."""
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    scenes = detect_scenes(video_path, threshold)

    # Get total duration
    dur_r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True,
    )
    total = float(dur_r.stdout.strip() or "0")
    scenes.append(total)

    out_paths: list[Path] = []
    for i in range(len(scenes) - 1):
        start = scenes[i]
        end = scenes[i + 1]
        if end - start < min_chunk_duration:
            continue
        out = output_dir / f"chunk_{i:03d}.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start), "-to", str(end),
            "-i", str(video_path),
            "-c", "copy",
            str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            out_paths.append(out)
    return out_paths


def chunk_by_duration(
    video_path: str | Path,
    output_dir: str | Path,
    chunk_duration: float = 30.0,
) -> list[Path]:
    """Split video into fixed-duration chunks. Returns list of output clip paths."""
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    out_pattern = str(output_dir / "chunk_%03d.mp4")
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-c", "copy",
        "-f", "segment",
        "-segment_time", str(chunk_duration),
        "-reset_timestamps", "1",
        out_pattern,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"chunk failed: {r.stderr[-300:]}")
    return sorted(output_dir.glob("chunk_*.mp4"))
