from __future__ import annotations

from pathlib import Path
from typing import Any

from video_compose.renderers import registry


def dispatch(
    segment,
    data: Any,
    output_path: Path,
    *,
    width: int,
    height: int,
    fps: float,
) -> Path:
    """Look up and invoke the renderer for *segment.type*, return output Path."""
    renderer_cls = registry.get(segment.type)
    renderer = renderer_cls()
    return renderer.render(segment, data, output_path, width=width, height=height, fps=fps)
