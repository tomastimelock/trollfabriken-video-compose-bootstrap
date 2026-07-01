from __future__ import annotations

import os
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np


def frames_to_mp4(frames: list[np.ndarray], output_path: Path, fps: float) -> None:
    """Encode RGBA or RGB numpy frames to H.264 MP4 at *output_path*."""
    from PIL import Image
    with tempfile.TemporaryDirectory() as td:
        for i, frame in enumerate(frames):
            img = Image.fromarray(frame)
            if img.mode == "RGBA":
                img = img.convert("RGB")
            img.save(os.path.join(td, f"f{i:06d}.png"))
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", os.path.join(td, "f%06d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg encode failed: {result.stderr[:500]}")


class BaseRenderer(ABC):
    """Abstract renderer for a single TVCS segment type.

    Each subclass handles one segment ``type`` (e.g. "mathviz", "chart") and
    is responsible for producing a silent MP4 clip at *output_path*.

    Args:
        segment: The typed Pydantic segment model (e.g. MathvizSegment).
        data:    Resolved data from DataResolver (DataFrame / dict / list / None).
        output_path: Where to write the rendered MP4.
        width:   Frame width in pixels.
        height:  Frame height in pixels.
        fps:     Frames per second.

    Returns:
        The resolved output Path (same as *output_path*).
    """

    @abstractmethod
    def render(
        self,
        segment,
        data: Any,
        output_path: Path,
        *,
        width: int,
        height: int,
        fps: float,
    ) -> Path: ...
