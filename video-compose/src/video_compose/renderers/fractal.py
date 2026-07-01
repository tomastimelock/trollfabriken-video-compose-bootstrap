from __future__ import annotations

from pathlib import Path
from typing import Any

from video_compose.renderers.base import BaseRenderer, frames_to_mp4


class FractalRenderer(BaseRenderer):
    """Renders a FractalSegment using fractal-fx render_fractal."""

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
        try:
            from fractal_fx.api import render_fractal
        except ImportError as exc:
            raise RuntimeError(
                "fractal-fx is required for fractal segments — pip install video-compose[fractal]"
            ) from exc

        params = dict(segment.config)
        params.setdefault("duration", segment.duration)

        frames = render_fractal(
            effect_type=segment.effect,
            params=params or None,
            width=width,
            height=height,
            fps=int(fps),
        )

        output_path = Path(output_path)
        frames_to_mp4(frames, output_path, fps)
        return output_path
