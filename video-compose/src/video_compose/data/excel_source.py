from __future__ import annotations

from video_compose.data.fetcher import DataFetcher, DataFetchError


class ExcelFetcher(DataFetcher):
    source_type = "excel"

    def fetch(self, config: dict):
        try:
            import pandas as pd
        except ImportError as exc:
            raise DataFetchError(
                config.get("path", "?"), "excel",
                "pandas is required for excel sources — pip install pandas openpyxl",
            ) from exc

        path = config.get("path")
        sheet = config.get("sheet", 0)
        cell_range = config.get("range")

        try:
            df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
        except ImportError as exc:
            raise DataFetchError(
                path or "?", "excel",
                "openpyxl is required for excel sources — pip install openpyxl",
            ) from exc
        except Exception as exc:
            raise DataFetchError(path or "?", "excel", str(exc)) from exc

        if cell_range:
            # Parse A1:C10 style range — convert to row/col slices
            try:
                start, end = cell_range.split(":")
                start_col = "".join(c for c in start if c.isalpha())
                start_row = int("".join(c for c in start if c.isdigit())) - 1
                end_col = "".join(c for c in end if c.isalpha())
                end_row = int("".join(c for c in end if c.isdigit()))

                def col_idx(letters: str) -> int:
                    idx = 0
                    for ch in letters.upper():
                        idx = idx * 26 + (ord(ch) - ord("A") + 1)
                    return idx - 1

                df = df.iloc[start_row:end_row, col_idx(start_col):col_idx(end_col) + 1]
            except Exception as exc:
                raise DataFetchError(path or "?", "excel", f"invalid range {cell_range!r}: {exc}") from exc

        return df
