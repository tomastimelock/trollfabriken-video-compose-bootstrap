from __future__ import annotations

import tempfile
from pathlib import Path

from video_compose.audio.transcription import WordTiming

_DEFAULT_FILLERS = frozenset({
    "um", "uh", "er", "ah", "like", "basically", "literally",
    "you know", "i mean", "sort of", "kind of", "right",
})


def find_fillers(
    words: list[WordTiming],
    filler_set: set[str] | None = None,
) -> list[WordTiming]:
    """Return list of word timings that match the filler word set."""
    fillers = filler_set or _DEFAULT_FILLERS
    return [w for w in words if w.word.lower().strip(".,!?") in fillers]


def remove_fillers_from_video(
    input_path: str | Path,
    output_path: str | Path,
    words: list[WordTiming],
    filler_set: set[str] | None = None,
    pad_ms: float = 50.0,
) -> Path:
    """Cut filler words out of a video/audio file using ffmpeg concat demuxer."""
    import subprocess

    input_path = Path(input_path)
    output_path = Path(output_path)
    filler_timings = find_fillers(words, filler_set)

    if not filler_timings:
        subprocess.run(["ffmpeg", "-y", "-i", str(input_path), "-c", "copy", str(output_path)],
                       capture_output=True, check=True)
        return output_path

    # Build keep-ranges (invert filler positions)
    pad = pad_ms / 1000.0
    dur_r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(input_path)],
        capture_output=True, text=True,
    )
    total_dur = float(dur_r.stdout.strip() or "999")

    exclude = [(max(0.0, w.start - pad), w.end + pad) for w in filler_timings]
    exclude.sort()

    keep: list[tuple[float, float]] = []
    pos = 0.0
    for s, e in exclude:
        if s > pos + 0.02:
            keep.append((pos, s))
        pos = e
    if pos < total_dur - 0.02:
        keep.append((pos, total_dur))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        concat_path = Path(f.name)
        for start, end in keep:
            f.write(f"file '{input_path.as_posix()}'\n")
            f.write(f"inpoint {start:.3f}\n")
            f.write(f"outpoint {end:.3f}\n")

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path),
           "-c", "copy", str(output_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    concat_path.unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError(f"filler removal failed: {r.stderr[-400:]}")
    return output_path
