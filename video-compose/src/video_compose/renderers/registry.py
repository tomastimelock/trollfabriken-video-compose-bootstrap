from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.renderers.base import BaseRenderer

_REGISTRY: dict[str, type[BaseRenderer]] = {}


def register(type_name: str, cls: type) -> None:
    _REGISTRY[type_name] = cls


def get(type_name: str) -> type[BaseRenderer]:
    if type_name not in _REGISTRY:
        _load_defaults()
    if type_name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(f"No renderer registered for segment type {type_name!r}. Available: {available}")
    return _REGISTRY[type_name]


def list_types() -> list[str]:
    _load_defaults()
    return sorted(_REGISTRY)


_defaults_loaded = False


def _load_defaults() -> None:
    global _defaults_loaded
    if _defaults_loaded:
        return
    _defaults_loaded = True

    from video_compose.renderers.blank import BlankRenderer
    from video_compose.renderers.image import ImageRenderer
    from video_compose.renderers.video import VideoRenderer
    from video_compose.renderers.still import StillRenderer
    from video_compose.renderers.slide import SlideRenderer
    from video_compose.renderers.mathviz import MathvizRenderer
    from video_compose.renderers.chart import ChartRenderer
    from video_compose.renderers.geomap import GeomapRenderer
    from video_compose.renderers.shape import ShapeRenderer
    from video_compose.renderers.fractal import FractalRenderer
    from video_compose.renderers.split_screen import SplitScreenRenderer

    for type_name, cls in [
        ("blank", BlankRenderer),
        ("image", ImageRenderer),
        ("video", VideoRenderer),
        ("still", StillRenderer),
        ("slide", SlideRenderer),
        ("mathviz", MathvizRenderer),
        ("chart", ChartRenderer),
        ("geomap", GeomapRenderer),
        ("shape", ShapeRenderer),
        ("fractal", FractalRenderer),
        ("split_screen", SplitScreenRenderer),
    ]:
        _REGISTRY[type_name] = cls
