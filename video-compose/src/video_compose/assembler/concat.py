from __future__ import annotations

import subprocess
import tempfile
import os
from pathlib import Path


def concat_clips(clip_paths: list[Path], output: Path) -> Path:
    """Concatenate a list of clip files into a single MP4 using ffmpeg concat."""
    if not clip_paths:
        raise ValueError("concat_clips: no clips to concatenate")

    if len(clip_paths) == 1:
        return clip_paths[0]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in clip_paths:
            f.write(f"file '{Path(p).as_posix()}'\n")
        concat_list = f.name

    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", concat_list, "-c", "copy", str(output)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {result.stderr[:500]}")
    finally:
        os.unlink(concat_list)

    return output
