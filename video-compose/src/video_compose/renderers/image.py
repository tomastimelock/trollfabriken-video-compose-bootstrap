from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from video_compose.renderers.base import BaseRenderer


class ImageRenderer(BaseRenderer):
    """Renders an ImageSegment via ffmpeg (static or Ken Burns motion)."""

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
        motion = getattr(segment, "motion", "static")
        fit = getattr(segment, "fit", "cover")
        output_path = Path(output_path)

        if motion == "static":
            scale_filter = _scale_filter(width, height, fit)
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-framerate", str(fps),
                "-i", str(source),
                "-t", str(segment.duration),
                "-vf", scale_filter,
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                str(output_path),
            ]
        else:
            # Ken Burns / zoom / pan via ffmpeg zoompan
            zoom_start, zoom_end = _motion_zoom(motion)
            total_frames = int(segment.duration * fps)
            zoom_step = (zoom_end - zoom_start) / max(total_frames - 1, 1)
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-framerate", str(fps),
                "-i", str(source),
                "-t", str(segment.duration),
                "-vf", (
                    f"scale={width * 2}:{height * 2},"
                    f"zoompan=z='min(max(zoom,{zoom_start:.4f})+{zoom_step:.8f},{zoom_end:.4f})':"
                    f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                    f"d={total_frames}:s={width}x{height}:fps={fps}"
                ),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                str(output_path),
            ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg image encode failed: {result.stderr[:500]}")
        return output_path


def _scale_filter(width: int, height: int, fit: str) -> str:
    if fit == "contain":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
    elif fit == "stretch":
        return f"scale={width}:{height}"
    else:  # cover
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )


def _motion_zoom(motion: str) -> tuple[float, float]:
    mapping = {
        "ken_burns": (1.0, 1.25),
        "zoom_in": (1.0, 1.4),
        "zoom_out": (1.4, 1.0),
        "pan_left": (1.1, 1.1),
        "pan_right": (1.1, 1.1),
    }
    return mapping.get(motion, (1.0, 1.0))
