from __future__ import annotations

from video_compose.data.fetcher import DataFetcher, DataFetchError


class SQLFetcher(DataFetcher):
    source_type = "sql"

    def fetch(self, config: dict):
        try:
            import pandas as pd
            import sqlalchemy
        except ImportError as exc:
            raise DataFetchError(
                "sql", "sql",
                "pandas and sqlalchemy are required for sql sources — pip install pandas sqlalchemy",
            ) from exc

        connection = config.get("connection", "")
        query = config.get("query", "")
        params = config.get("params") or {}

        if not connection:
            raise DataFetchError("sql", "sql", "'connection' is required")
        if not query:
            raise DataFetchError("sql", "sql", "'query' is required")

        engine = None
        try:
            engine = sqlalchemy.create_engine(connection)
            with engine.connect() as conn:
                # If query looks like a plain table name (no spaces), wrap in SELECT *
                if " " not in query.strip():
                    sql = sqlalchemy.text(f"SELECT * FROM {query}")
                else:
                    sql = sqlalchemy.text(query)
                result = pd.read_sql(sql, conn, params=params if params else None)
            return result
        except DataFetchError:
            raise
        except Exception as exc:
            raise DataFetchError(connection, "sql", str(exc)) from exc
        finally:
            if engine is not None:
                engine.dispose()
