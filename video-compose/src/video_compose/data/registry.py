# Placeholder — implemented in task #29
from __future__ import annotations

from video_compose.data.fetcher import DataFetcher

_REGISTRY: dict[str, type[DataFetcher]] = {}


def register_fetcher(type_name: str, cls: type[DataFetcher]) -> None:
    _REGISTRY[type_name] = cls


def get_fetcher(type_name: str) -> type[DataFetcher]:
    if type_name not in _REGISTRY:
        raise KeyError(f"No data fetcher registered for type {type_name!r}")
    return _REGISTRY[type_name]
