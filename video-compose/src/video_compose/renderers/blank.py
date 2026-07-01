from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from video_compose.renderers.base import BaseRenderer


class BlankRenderer(BaseRenderer):
    """Renders a BlankSegment — solid colour via ffmpeg lavfi."""

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
        color = segment.color or "black"
        # Normalise hex: "#rrggbb" → "0xrrggbb"
        if color.startswith("#"):
            color = "0x" + color[1:]

        output_path = Path(output_path)
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c={color}:size={width}x{height}:rate={fps}:duration={segment.duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg blank encode failed: {result.stderr[:500]}")
        return output_path
