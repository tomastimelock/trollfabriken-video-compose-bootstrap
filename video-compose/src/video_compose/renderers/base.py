from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import numpy as np

from video_compose._codec import codec_params

_log = logging.getLogger(__name__)

# Fallback: 5-second black blank segment used when a renderer fails catastrophically
_FFMPEG_TIMEOUT_SEC = 300


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
            *codec_params(crf=20),
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT_SEC)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg encode failed: {result.stderr[:500]}")


def _render_error_fallback(output_path: Path, width: int, height: int, fps: float, duration: float) -> Path:
    """Produce a solid dark-gray blank clip as a last-resort fallback when a renderer fails."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x1a1a1a:size={width}x{height}:rate={fps}",
        "-t", str(duration),
        *codec_params(crf=28),
        str(output_path),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30, check=True)
    except Exception:
        pass
    return output_path


def validate_source_asset(path: str | Path) -> Path:
    """Check that a source asset file exists and is non-empty.

    Raises:
        FileNotFoundError: Asset does not exist at path.
        ValueError: Asset exists but is zero bytes.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Asset not found: {p}")
    if p.stat().st_size == 0:
        raise ValueError(f"Asset is empty (0 bytes): {p}")
    return p


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

    def render_safe(
        self,
        segment,
        data: Any,
        output_path: Path,
        *,
        width: int,
        height: int,
        fps: float,
    ) -> Path:
        """Call render() with error handling: OOM guard, timeout, and fallback blank.

        On MemoryError or subprocess.TimeoutExpired, logs an error and returns a
        dark-gray fallback blank clip so the pipeline can continue.
        """
        try:
            return self.render(
                segment, data, output_path,
                width=width, height=height, fps=fps,
            )
        except MemoryError as exc:
            _log.error(
                "OOM rendering segment %r (%s) — falling back to blank. Details: %s",
                segment.id, type(segment).__name__, exc,
            )
        except subprocess.TimeoutExpired as exc:
            _log.error(
                "ffmpeg timeout rendering segment %r (%s) after %ss — falling back to blank.",
                segment.id, type(segment).__name__, _FFMPEG_TIMEOUT_SEC,
            )
        except FileNotFoundError as exc:
            _log.error(
                "Missing asset for segment %r: %s — falling back to blank.", segment.id, exc
            )
        except Exception as exc:
            _log.error(
                "Renderer error for segment %r (%s): %s — falling back to blank.",
                segment.id, type(segment).__name__, exc,
            )

        return _render_error_fallback(
            output_path, width, height, fps, getattr(segment, "duration", 3.0)
        )
