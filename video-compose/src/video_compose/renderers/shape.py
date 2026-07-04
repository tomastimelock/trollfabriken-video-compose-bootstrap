from __future__ import annotations

from pathlib import Path
from typing import Any

from video_compose.renderers.base import BaseRenderer, frames_to_mp4

# Keys that ShapeParams.from_spec() reads from spec["effect"] (not the top level)
_EFFECT_LEVEL_KEYS = frozenset({
    "template", "enter_duration", "hold_duration", "exit_duration",
    "enter_easing", "exit_easing", "effect_params",
    "ai_model", "ai_temperature", "validate_svg",
})


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

        # Derive timing from segment.duration when not explicitly set
        enter = float(params.pop("enter_duration", min(0.5, segment.duration * 0.15)))
        exit_ = float(params.pop("exit_duration", min(0.3, segment.duration * 0.10)))
        hold = float(params.pop("hold_duration", max(0.1, segment.duration - enter - exit_)))

        # Collect effect-level keys from flat config
        effect_spec: dict[str, Any] = {
            "type": segment.effect,
            "enter_duration": enter,
            "hold_duration": hold,
            "exit_duration": exit_,
        }
        for key in _EFFECT_LEVEL_KEYS - {"enter_duration", "hold_duration", "exit_duration"}:
            if key in params:
                effect_spec[key] = params.pop(key)

        # Remaining keys are top-level ShapeParams fields (color, fill, stroke, position, scale, …)
        full_spec: dict[str, Any] = {"effect": effect_spec, **params}

        frames = render_shape(
            effect_type=segment.effect,
            params=full_spec,
            width=width,
            height=height,
            fps=int(fps),
        )

        output_path = Path(output_path)
        frames_to_mp4(frames, output_path, fps)
        return output_path
