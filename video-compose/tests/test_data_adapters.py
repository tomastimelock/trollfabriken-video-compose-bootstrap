"""Adapter smoke tests — uses only stdlib; pandas/openpyxl/sqlalchemy are optional."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

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
# JSON adapter
# ---------------------------------------------------------------------------

def test_json_file():
    from video_compose.data.json_source import JSONFetcher
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "data.json"
        p.write_text(json.dumps({"items": [1, 2, 3]}), encoding="utf-8")
        result = JSONFetcher().fetch({"type": "json", "path": str(p)})
    assert result == {"items": [1, 2, 3]}


check("JSONFetcher reads file", test_json_file)


def test_json_jmespath():
    try:
        import jmespath as _j  # noqa: F401
    except ImportError:
        print("SKIP  JSONFetcher jmespath (jmespath not installed)")
        return
    from video_compose.data.json_source import JSONFetcher
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "data.json"
        p.write_text(json.dumps({"a": {"b": 42}}), encoding="utf-8")
        result = JSONFetcher().fetch({"type": "json", "path": str(p), "jmespath": "a.b"})
    assert result == 42


check("JSONFetcher with jmespath selector", test_json_jmespath)


def test_json_missing_path():
    from video_compose.data.fetcher import DataFetchError
    from video_compose.data.json_source import JSONFetcher
    try:
        JSONFetcher().fetch({"type": "json", "path": "/no/such/file.json"})
        raise AssertionError("should have raised")
    except DataFetchError:
        pass


check("JSONFetcher missing file raises DataFetchError", test_json_missing_path)


# ---------------------------------------------------------------------------
# CSV adapter (requires pandas)
# ---------------------------------------------------------------------------

def test_csv_file():
    try:
        import pandas as pd
    except ImportError:
        print("SKIP  CSVFetcher (pandas not installed)")
        return
    from video_compose.data.csv_source import CSVFetcher
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "data.csv"
        p.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
        df = CSVFetcher().fetch({"type": "csv", "path": str(p)})
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 2


check("CSVFetcher reads file", test_csv_file)


def test_csv_custom_delimiter():
    try:
        import pandas as pd
    except ImportError:
        print("SKIP  CSVFetcher delimiter (pandas not installed)")
        return
    from video_compose.data.csv_source import CSVFetcher
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "data.csv"
        p.write_text("a;b\n1;2\n", encoding="utf-8")
        df = CSVFetcher().fetch({"type": "csv", "path": str(p), "delimiter": ";"})
    assert list(df.columns) == ["a", "b"]


check("CSVFetcher custom delimiter", test_csv_custom_delimiter)


# ---------------------------------------------------------------------------
# Excel adapter (requires pandas + openpyxl)
# ---------------------------------------------------------------------------

def test_excel_file():
    try:
        import pandas as pd
        import openpyxl
    except ImportError:
        print("SKIP  ExcelFetcher (pandas or openpyxl not installed)")
        return
    from video_compose.data.excel_source import ExcelFetcher
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "data.xlsx"
        df_in = pd.DataFrame({"x": [10, 20], "y": [30, 40]})
        df_in.to_excel(str(p), index=False, engine="openpyxl")
        df_out = ExcelFetcher().fetch({"type": "excel", "path": str(p)})
    assert list(df_out.columns) == ["x", "y"]
    assert len(df_out) == 2


check("ExcelFetcher reads file", test_excel_file)


# ---------------------------------------------------------------------------
# SQL adapter (sqlite via sqlalchemy — stdlib sqlite3 available everywhere)
# ---------------------------------------------------------------------------

def test_sql_sqlite():
    try:
        import pandas as pd
        import sqlalchemy
    except ImportError:
        print("SKIP  SQLFetcher (pandas or sqlalchemy not installed)")
        return
    from video_compose.data.sql_source import SQLFetcher
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "test.db"
        engine = sqlalchemy.create_engine(f"sqlite:///{db}")
        pd.DataFrame({"name": ["Alice", "Bob"], "score": [95, 87]}).to_sql(
            "results", engine, index=False
        )
        engine.dispose()
        df = SQLFetcher().fetch({
            "type": "sql",
            "connection": f"sqlite:///{db}",
            "query": "SELECT * FROM results",
        })
    assert list(df.columns) == ["name", "score"]
    assert len(df) == 2


check("SQLFetcher sqlite query", test_sql_sqlite)


def test_sql_table_shorthand():
    try:
        import pandas as pd
        import sqlalchemy
    except ImportError:
        print("SKIP  SQLFetcher table shorthand (pandas or sqlalchemy not installed)")
        return
    from video_compose.data.sql_source import SQLFetcher
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "test2.db"
        engine = sqlalchemy.create_engine(f"sqlite:///{db}")
        pd.DataFrame({"val": [1, 2, 3]}).to_sql("items", engine, index=False)
        engine.dispose()
        df = SQLFetcher().fetch({
            "type": "sql",
            "connection": f"sqlite:///{db}",
            "query": "items",  # table name only
        })
    assert len(df) == 3


check("SQLFetcher table-name shorthand", test_sql_table_shorthand)


# ---------------------------------------------------------------------------
# API adapter — mock with a real URL (httpbin is public but may be slow)
# We test the no-url error path which requires no network.
# ---------------------------------------------------------------------------

def test_api_no_url():
    from video_compose.data.fetcher import DataFetchError
    from video_compose.data.api_source import APIFetcher
    try:
        APIFetcher().fetch({"type": "api"})
        raise AssertionError("should have raised")
    except DataFetchError as e:
        assert "'url' is required" in str(e)


check("APIFetcher missing url raises DataFetchError", test_api_no_url)


def test_api_bad_url():
    from video_compose.data.fetcher import DataFetchError
    from video_compose.data.api_source import APIFetcher
    try:
        APIFetcher().fetch({"type": "api", "url": "http://localhost:19999/no-server", "timeout": 2})
        raise AssertionError("should have raised")
    except DataFetchError:
        pass


check("APIFetcher unreachable host raises DataFetchError", test_api_bad_url)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print(f"\n{'='*40}")
print(f"Results: {PASS} passed, {FAIL} failed")
if FAIL:
    sys.exit(1)
