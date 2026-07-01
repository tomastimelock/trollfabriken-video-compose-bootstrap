from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from video_compose.renderers.base import BaseRenderer


class VideoRenderer(BaseRenderer):
    """Renders a VideoSegment — re-encodes/trims an existing video file."""

    def render(
        self,
        segment,
        data: Any,
        output_path: Path,
        *,
        width: int,
        height: int,
        fps: float,
    ) -> Path:
        source = Path(segment.source)
        start_time = float(getattr(segment, "start_time", 0.0))
        loop = bool(getattr(segment, "loop", False))
        mute = bool(getattr(segment, "mute", False))
        duration = float(segment.duration)
        output_path = Path(output_path)

        input_args = []
        if loop:
            input_args += ["-stream_loop", "-1"]
        input_args += ["-ss", str(start_time), "-i", str(source)]

        audio_args = ["-an"] if mute else ["-c:a", "aac", "-b:a", "128k"]

        cmd = [
            "ffmpeg", "-y",
            *input_args,
            "-t", str(duration),
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
            *audio_args,
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg video encode failed: {result.stderr[:500]}")
        return output_path
