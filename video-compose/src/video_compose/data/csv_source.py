from __future__ import annotations

from video_compose.data.fetcher import DataFetcher, DataFetchError


class CSVFetcher(DataFetcher):
    source_type = "csv"

    def fetch(self, config: dict):
        try:
            import pandas as pd
        except ImportError as exc:
            raise DataFetchError(
                config.get("path") or config.get("url", "?"),
                "csv",
                "pandas is required for csv sources — pip install pandas",
            ) from exc

        path = config.get("path")
        url = config.get("url")
        delimiter = config.get("delimiter", ",")
        encoding = config.get("encoding", "utf-8")
        header = config.get("header", 0)

        source = url if url else path
        try:
            return pd.read_csv(source, sep=delimiter, encoding=encoding, header=header)
        except Exception as exc:
            raise DataFetchError(source or "?", "csv", str(exc)) from exc
