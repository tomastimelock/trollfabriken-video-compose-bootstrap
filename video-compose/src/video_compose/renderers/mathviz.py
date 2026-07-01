from __future__ import annotations

from pathlib import Path
from typing import Any

from video_compose.renderers.base import BaseRenderer


class MathvizRenderer(BaseRenderer):
    """Renders a MathvizSegment using mathviz-fx BackgroundScene."""

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
            from mathviz_fx.core.background_scene import BackgroundScene
        except ImportError as exc:
            raise RuntimeError(
                "mathviz-fx is required for mathviz segments — "
                "pip install video-compose[mathviz]"
            ) from exc

        spec = {
            "id": segment.id,
            "background_type": segment.effect,
            "params": dict(segment.config),
            "animation": {"type": "loop"},
            "render": {
                "width": width,
                "height": height,
                "fps": fps,
                "duration": segment.duration,
                "quality": "standard",
            },
        }

        output_path = Path(output_path)
        scene = BackgroundScene(spec)
        scene.render_to_video(str(output_path))
        return output_path
