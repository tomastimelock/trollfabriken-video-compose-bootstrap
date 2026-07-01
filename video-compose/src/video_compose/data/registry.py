"""
DataFetcher registry.

Built-in fetchers are registered lazily on first access so that missing
optional dependencies (pandas, openpyxl, sqlalchemy, requests) only raise
at the moment a spec actually uses that source type — not at import time.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.data.fetcher import DataFetcher

_REGISTRY: dict[str, type[DataFetcher]] = {}
_BUILTINS_LOADED = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_fetcher(type_name: str, cls: type) -> None:
    """Register a DataFetcher subclass for *type_name*.

    Can be called by third-party packages to add custom source types::

        from video_compose.data.registry import register_fetcher
        from my_pkg import NotionFetcher
        register_fetcher("notion", NotionFetcher)
    """
    _REGISTRY[type_name] = cls


def get_fetcher(type_name: str) -> type:
    """Return the DataFetcher class for *type_name*.

    Loads built-in fetchers on first call (lazy).

    Raises:
        KeyError: If no fetcher is registered for *type_name*.
    """
    _ensure_builtins()
    if type_name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(
            f"No fetcher registered for source type {type_name!r}. "
            f"Available: {available}"
        )
    return _REGISTRY[type_name]


def list_registered_types() -> list[str]:
    """Return all currently registered source type names."""
    _ensure_builtins()
    return sorted(_REGISTRY)


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _ensure_builtins() -> None:
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    _BUILTINS_LOADED = True
    _register_builtins()


def _register_builtins() -> None:
    """Register each built-in fetcher, skipping any whose deps are absent."""

    _try_register("csv",   "video_compose.data.csv_source",   "CSVFetcher")
    _try_register("json",  "video_compose.data.json_source",  "JSONFetcher")
    _try_register("excel", "video_compose.data.excel_source", "ExcelFetcher")
    _try_register("sql",   "video_compose.data.sql_source",   "SQLFetcher")
    _try_register("api",   "video_compose.data.api_source",   "APIFetcher")


def _try_register(type_name: str, module_path: str, class_name: str) -> None:
    """Import *module_path.class_name* and register it; silently skip on ImportError."""
    import importlib
    try:
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        register_fetcher(type_name, cls)
    except ImportError:
        pass  # optional dep not installed; fetcher unavailable until dep is added
    except Exception:
        pass  # adapter module has a bug; don't crash the whole registry
