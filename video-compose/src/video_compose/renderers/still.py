from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from video_compose.renderers.base import BaseRenderer

_MOTION_TO_ZOOM = {
    "ken_burns": (1.0, 1.25),
    "zoom_in": (1.0, 1.4),
    "zoom_out": (1.4, 1.0),
    "pan_left": (1.0, 1.0),
    "pan_right": (1.0, 1.0),
    "static": (1.0, 1.0),
}


class StillRenderer(BaseRenderer):
    """Renders a StillSegment using still-motion KenBurns or static ffmpeg loop."""

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
        motion = getattr(segment, "motion", "ken_burns")
        motion_config = dict(getattr(segment, "motion_config", {}) or {})
        output_path = Path(output_path)

        if motion == "static":
            return _static_loop(source, output_path, width, height, fps, segment.duration)

        try:
            from still_motion import KenBurns, RenderConfig
        except ImportError as exc:
            raise RuntimeError(
                "still-motion is required for animated still segments — pip install still-motion"
            ) from exc

        zoom_start, zoom_end = _MOTION_TO_ZOOM.get(motion, (1.0, 1.25))
        zoom_start = float(motion_config.pop("zoom_start", zoom_start))
        zoom_end = float(motion_config.pop("zoom_end", zoom_end))
        focus = tuple(motion_config.pop("focus", (0.5, 0.5)))

        kb = KenBurns(
            image=source,
            duration=segment.duration,
            width=width,
            height=height,
            fps=int(fps),
            zoom_start=zoom_start,
            zoom_end=zoom_end,
            focus=focus,
            **motion_config,
        )
        config = RenderConfig(width=width, height=height, fps=int(fps))
        kb.render(output_path, config)
        return output_path


def _static_loop(source: Path, output: Path, width: int, height: int, fps: float, duration: float) -> Path:
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(fps),
        "-i", str(source),
        "-t", str(duration),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg static loop failed: {result.stderr[:500]}")
    return output
