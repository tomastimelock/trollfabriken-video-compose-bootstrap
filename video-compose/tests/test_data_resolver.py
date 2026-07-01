"""DataFetcher / DataResolver test suite — run with: python tests/test_data_resolver.py"""
from __future__ import annotations

from video_compose.data.fetcher import DataFetcher, DataFetchError, DataResolver
from video_compose.data.registry import register_fetcher, get_fetcher, list_registered_types
from video_compose.schema.spec import TVCSSpec

PASS = 0
FAIL = 0


def check(label: str, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"PASS  {label}")
    except Exception as exc:
        FAIL += 1
        print(f"FAIL  {label}")
        print(f"      {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Fixtures — mock fetchers registered for the test session
# ---------------------------------------------------------------------------

class _DictFetcher(DataFetcher):
    source_type = "mock_dict"
    def fetch(self, config: dict):
        return {"key": "value", "num": config.get("value", 42)}


class _ListFetcher(DataFetcher):
    source_type = "mock_list"
    def fetch(self, config: dict):
        return [1, 2, 3]


class _BrokenFetcher(DataFetcher):
    source_type = "mock_broken"
    def fetch(self, config: dict):
        raise RuntimeError("connection refused")


register_fetcher("mock_dict", _DictFetcher)
register_fetcher("mock_list", _ListFetcher)
register_fetcher("mock_broken", _BrokenFetcher)


class _MockSourceModel:
    """Minimal stand-in for a DataSourceConfig Pydantic model, used in tests."""
    def __init__(self, type_name: str, **kwargs):
        self.type = type_name
        self._extra = kwargs

    def model_dump(self) -> dict:
        return {"type": self.type, **self._extra}


class _MockSpec:
    """Minimal TVCSSpec stand-in that carries data_sources without Pydantic."""
    def __init__(self, data_sources: dict):
        self.data_sources = data_sources


def _make_spec(data_sources: dict, segments: list | None = None) -> TVCSSpec:
    """Build a real TVCSSpec (only valid source types) for schema-layer tests."""
    return TVCSSpec.model_validate({
        "tvcs": "1.0",
        "data_sources": data_sources,
        "segments": segments or [{"id": "x", "type": "blank", "duration": 1.0}],
    })


def _make_resolver(data_sources: dict) -> DataResolver:
    """Build a DataResolver with mock source models (bypasses schema discriminator)."""
    mock_sources = {
        sid: _MockSourceModel(cfg["type"], **{k: v for k, v in cfg.items() if k != "type"})
        for sid, cfg in data_sources.items()
    }
    return DataResolver(_MockSpec(mock_sources))


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

def test_register_and_retrieve():
    cls = get_fetcher("mock_dict")
    assert cls is _DictFetcher

check("register and retrieve fetcher", test_register_and_retrieve)


def test_list_includes_registered():
    types = list_registered_types()
    assert "mock_dict" in types
    assert "mock_list" in types

check("list_registered_types includes mock fetchers", test_list_includes_registered)


def test_unknown_type_raises():
    try:
        get_fetcher("no_such_type_xyz")
        raise AssertionError("should have raised KeyError")
    except KeyError as e:
        assert "no_such_type_xyz" in str(e)

check("get_fetcher unknown type raises KeyError", test_unknown_type_raises)


# ---------------------------------------------------------------------------
# DataResolver — inline data (pass-through)
# ---------------------------------------------------------------------------

def test_resolve_inline_dict():
    r = _make_resolver({})
    data = {"a": 1, "b": 2}
    assert r.resolve(data) is data

check("resolve inline dict passes through", test_resolve_inline_dict)


def test_resolve_inline_list():
    r = _make_resolver({})
    data = [1, 2, 3]
    assert r.resolve(data) is data

check("resolve inline list passes through", test_resolve_inline_list)


def test_resolve_none():
    r = _make_resolver({})
    assert r.resolve(None) is None

check("resolve None passes through", test_resolve_none)


# ---------------------------------------------------------------------------
# DataResolver — $sources references
# ---------------------------------------------------------------------------

def test_resolve_source_ref_dict():
    r = _make_resolver({"my_data": {"type": "mock_dict", "value": 99}})
    result = r.resolve("$sources.my_data")
    assert isinstance(result, dict)
    assert result["key"] == "value"

check("resolve $sources.xxx returns fetched dict", test_resolve_source_ref_dict)


def test_resolve_source_ref_list():
    r = _make_resolver({"items": {"type": "mock_list"}})
    result = r.resolve("$sources.items")
    assert result == [1, 2, 3]

check("resolve $sources.xxx returns fetched list", test_resolve_source_ref_list)


def test_resolve_is_cached():
    r = _make_resolver({"data": {"type": "mock_dict"}})
    r1 = r.resolve("$sources.data")
    r2 = r.resolve("$sources.data")
    assert r1 is r2  # same object — cache hit

check("second resolve returns cached object", test_resolve_is_cached)


def test_invalidate_clears_cache():
    r = _make_resolver({"data": {"type": "mock_dict"}})
    r1 = r.resolve("$sources.data")
    r.invalidate("data")
    r2 = r.resolve("$sources.data")
    assert r1 is not r2  # re-fetched after invalidation

check("invalidate clears single source cache", test_invalidate_clears_cache)


def test_invalidate_all():
    r = _make_resolver({"a": {"type": "mock_dict"}, "b": {"type": "mock_list"}})
    r.resolve("$sources.a")
    r.resolve("$sources.b")
    r.invalidate()
    assert len(r._cache) == 0

check("invalidate() with no args clears all cache", test_invalidate_all)


# ---------------------------------------------------------------------------
# DataResolver — error cases
# ---------------------------------------------------------------------------

def test_invalid_source_ref_format():
    r = _make_resolver({})
    try:
        r.resolve("$not_a_source_ref")
        raise AssertionError("should have raised")
    except ValueError as e:
        assert "$not_a_source_ref" in str(e)

check("invalid $sources format raises ValueError", test_invalid_source_ref_format)


def test_undeclared_source_raises():
    r = _make_resolver({})
    try:
        r.resolve("$sources.ghost")
        raise AssertionError("should have raised")
    except DataFetchError as e:
        assert "ghost" in str(e)

check("undeclared source raises DataFetchError", test_undeclared_source_raises)


def test_broken_fetcher_raises():
    r = _make_resolver({"broken": {"type": "mock_broken"}})
    try:
        r.resolve("$sources.broken")
        raise AssertionError("should have raised")
    except DataFetchError as e:
        assert "broken" in str(e)
        assert "connection refused" in str(e)

check("failing fetcher wraps as DataFetchError", test_broken_fetcher_raises)


def test_unregistered_type_raises():
    from video_compose.data import registry as _reg
    register_fetcher("temp_missing", _DictFetcher)
    _reg._REGISTRY.pop("temp_missing")
    try:
        get_fetcher("temp_missing")
        raise AssertionError("should have raised")
    except KeyError:
        pass

check("unregistered type raises KeyError from get_fetcher", test_unregistered_type_raises)


def test_unknown_fetcher_in_resolver_raises():
    r = _make_resolver({"src": {"type": "totally_unknown_xyz"}})
    try:
        r.resolve("$sources.src")
        raise AssertionError("should have raised")
    except DataFetchError as e:
        assert "totally_unknown_xyz" in str(e) or "no fetcher" in str(e).lower()

check("resolver with unknown fetcher type raises DataFetchError", test_unknown_fetcher_in_resolver_raises)


# ---------------------------------------------------------------------------
# DataResolver — prefetch_all
# ---------------------------------------------------------------------------

def test_prefetch_all():
    r = _make_resolver({"a": {"type": "mock_dict"}, "b": {"type": "mock_list"}})
    r.prefetch_all()
    assert "a" in r._cache
    assert "b" in r._cache

check("prefetch_all populates cache for all sources", test_prefetch_all)


def test_prefetch_all_raises_on_broken():
    r = _make_resolver({"bad": {"type": "mock_broken"}})
    try:
        r.prefetch_all()
        raise AssertionError("should have raised")
    except DataFetchError:
        pass

check("prefetch_all raises DataFetchError on broken source", test_prefetch_all_raises_on_broken)


# ---------------------------------------------------------------------------
# is_source_ref helper
# ---------------------------------------------------------------------------

def test_is_source_ref():
    r = _make_resolver({})
    assert r.is_source_ref("$sources.sales") is True
    assert r.is_source_ref("$sources.a_b_c") is True
    assert r.is_source_ref({"inline": True}) is False
    assert r.is_source_ref(None) is False
    assert r.is_source_ref("$not_sources.x") is False
    assert r.is_source_ref("$sources.") is False  # empty id — regex requires \w+

check("is_source_ref correctly classifies values", test_is_source_ref)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*40}")
print(f"Results: {PASS} passed, {FAIL} failed")
if FAIL:
    raise SystemExit(1)
