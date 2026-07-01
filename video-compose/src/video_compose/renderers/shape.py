from __future__ import annotations

from pathlib import Path
from typing import Any

from video_compose.renderers.base import BaseRenderer, frames_to_mp4


class ShapeRenderer(BaseRenderer):
    """Renders a ShapeSegment using shape-fx render_shape."""

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
            from shape_fx.api import render_shape
        except ImportError as exc:
            raise RuntimeError(
                "shape-fx is required for shape segments — pip install video-compose[shape]"
            ) from exc

        params = dict(segment.config)
        params.setdefault("duration", segment.duration)

        frames = render_shape(
            effect_type=segment.effect,
            params=params or None,
            width=width,
            height=height,
            fps=int(fps),
        )

        output_path = Path(output_path)
        frames_to_mp4(frames, output_path, fps)
        return output_path
