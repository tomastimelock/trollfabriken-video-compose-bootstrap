from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path


def detect_silence(
    path: str | Path,
    noise_floor_db: float = -35.0,
    min_duration: float = 0.5,
) -> list[tuple[float, float]]:
    """Return list of (start, end) silent intervals in seconds."""
    cmd = [
        "ffmpeg", "-i", str(path),
        "-af", f"silencedetect=noise={noise_floor_db}dB:d={min_duration}",
        "-f", "null", "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    silences: list[tuple[float, float]] = []
    start: float | None = None
    for line in r.stderr.splitlines():
        ms = re.search(r"silence_start: ([\d.]+)", line)
        me = re.search(r"silence_end: ([\d.]+)", line)
        if ms:
            start = float(ms.group(1))
        if me and start is not None:
            silences.append((start, float(me.group(1))))
            start = None
    return silences


def remove_silence(
    input_path: str | Path,
    output_path: str | Path,
    noise_floor_db: float = -35.0,
    min_duration: float = 0.5,
    pad_ms: float = 100.0,
) -> Path:
    """Cut silent sections out of a video/audio file using ffmpeg concat demuxer."""
    input_path = Path(input_path)
    output_path = Path(output_path)

    # Get total duration
    dur_r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(input_path)],
        capture_output=True, text=True,
    )
    total_dur = float(dur_r.stdout.strip() or "0")

    silences = detect_silence(input_path, noise_floor_db, min_duration)

    # Build keep-segments: invert silence list
    pad = pad_ms / 1000.0
    keep: list[tuple[float, float]] = []
    prev_end = 0.0
    for s_start, s_end in silences:
        seg_end = max(prev_end, s_start - pad)
        if seg_end > prev_end + 0.05:
            keep.append((prev_end, seg_end))
        prev_end = s_end + pad

    if prev_end < total_dur - 0.05:
        keep.append((prev_end, total_dur))

    if not keep:
        # Nothing to cut — just copy
        subprocess.run(["ffmpeg", "-y", "-i", str(input_path), "-c", "copy", str(output_path)],
                       capture_output=True, check=True)
        return output_path

    # Write concat file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        concat_path = Path(f.name)
        for start, end in keep:
            f.write(f"file '{input_path.as_posix()}'\n")
            f.write(f"inpoint {start:.3f}\n")
            f.write(f"outpoint {end:.3f}\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_path),
        "-c", "copy",
        str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    concat_path.unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError(f"silence removal failed: {r.stderr[-400:]}")
    return output_path
