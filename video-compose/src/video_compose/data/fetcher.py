"""
DataFetcher base class and DataResolver.

DataFetcher — abstract adapter interface. One subclass per source type.
DataResolver — session-scoped resolver that turns $sources.xxx strings
               into fetched data, with per-session caching.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from video_compose.schema.spec import TVCSSpec

_SOURCE_REF_RE = re.compile(r"^\$sources\.([a-zA-Z_]\w*)$")


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class DataFetcher(ABC):
    """Abstract adapter for a single data source type.

    Subclasses implement fetch() and declare which source type they handle
    via the ``source_type`` class attribute, used for auto-registration.
    """

    source_type: str = ""  # set by each subclass, e.g. "csv"

    @abstractmethod
    def fetch(self, config: dict) -> Any:
        """Fetch data from the source described by *config*.

        Args:
            config: The data source config dict (model_dump of the
                    Pydantic DataSourceConfig for this source).

        Returns:
            pd.DataFrame for tabular sources (CSV, Excel, SQL),
            dict or list for JSON/API sources.

        Raises:
            DataFetchError: On any retrieval or parse failure.
        """


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DataFetchError(RuntimeError):
    """Raised when a DataFetcher cannot retrieve or parse its source."""

    def __init__(self, source_id: str, source_type: str, reason: str) -> None:
        self.source_id = source_id
        self.source_type = source_type
        self.reason = reason
        super().__init__(f"[{source_type}] source '{source_id}': {reason}")


# ---------------------------------------------------------------------------
# DataResolver — session-scoped $sources.xxx resolver
# ---------------------------------------------------------------------------

class DataResolver:
    """Resolves DataRef values for a single render session.

    Usage::

        resolver = DataResolver(parsed_spec)
        data = resolver.resolve(segment.data)   # may be dict, list, or DataFrame
        resolver.prefetch_all()                  # eagerly fetch everything upfront
    """

    def __init__(self, spec: TVCSSpec) -> None:
        self._spec = spec
        self._cache: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def resolve(self, ref: Any, source_id_hint: str = "") -> Any:
        """Resolve a DataRef value.

        If *ref* is a ``$sources.<id>`` string, fetches and caches the
        corresponding data source. Any other value (dict, list, None) is
        returned unchanged — allowing inline data to pass through.

        Args:
            ref: A DataRef value from a segment (e.g. ``"$sources.sales"``
                 or an inline dict/list).
            source_id_hint: Used only in error messages when ref is a
                            bare string that isn't a valid source ref.

        Returns:
            Fetched data (DataFrame / dict / list) or the original value.

        Raises:
            DataFetchError: If the source ref points to an undeclared
                            source or the fetch itself fails.
            ValueError: If ref is a string but not a valid $sources expression.
        """
        if not isinstance(ref, str):
            return ref  # inline data — pass through

        m = _SOURCE_REF_RE.match(ref)
        if not m:
            raise ValueError(
                f"DataRef {ref!r} is not a valid $sources expression "
                f"(expected '$sources.<id>')"
            )

        source_id = m.group(1)
        return self._fetch_cached(source_id)

    def prefetch_all(self) -> None:
        """Eagerly fetch every declared data source.

        Useful for fail-fast validation before a long render starts.

        Raises:
            DataFetchError: On the first source that fails.
        """
        for source_id in self._spec.data_sources:
            self._fetch_cached(source_id)

    def invalidate(self, source_id: str | None = None) -> None:
        """Clear the cache for *source_id*, or all sources if None."""
        if source_id is None:
            self._cache.clear()
        else:
            self._cache.pop(source_id, None)

    def is_source_ref(self, value: Any) -> bool:
        """Return True if *value* is a ``$sources.xxx`` string."""
        return isinstance(value, str) and bool(_SOURCE_REF_RE.match(value))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fetch_cached(self, source_id: str) -> Any:
        if source_id in self._cache:
            return self._cache[source_id]

        if source_id not in self._spec.data_sources:
            declared = ", ".join(sorted(self._spec.data_sources)) or "(none)"
            raise DataFetchError(
                source_id, "unknown",
                f"not declared in data_sources; declared: {declared}",
            )

        source_model = self._spec.data_sources[source_id]
        source_type = source_model.type

        from video_compose.data.registry import get_fetcher
        try:
            fetcher_cls = get_fetcher(source_type)
        except KeyError:
            raise DataFetchError(
                source_id, source_type,
                f"no fetcher registered for type {source_type!r}; "
                f"install video-compose[data] for full data source support",
            ) from None

        config = source_model.model_dump()
        try:
            result = fetcher_cls().fetch(config)
        except DataFetchError:
            raise
        except Exception as exc:
            raise DataFetchError(source_id, source_type, str(exc)) from exc

        self._cache[source_id] = result
        return result
