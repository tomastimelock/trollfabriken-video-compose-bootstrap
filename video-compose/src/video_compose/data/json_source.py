from __future__ import annotations

import json
from pathlib import Path

from video_compose.data.fetcher import DataFetcher, DataFetchError


class JSONFetcher(DataFetcher):
    source_type = "json"

    def fetch(self, config: dict):
        path = config.get("path")
        url = config.get("url")
        jmespath_expr = config.get("jmespath")

        try:
            if url:
                import urllib.request
                with urllib.request.urlopen(url, timeout=30) as resp:
                    data = json.loads(resp.read())
            else:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            raise DataFetchError(path or url or "?", "json", str(exc)) from exc

        if jmespath_expr:
            try:
                import jmespath as _jmespath
                data = _jmespath.search(jmespath_expr, data)
            except ImportError as exc:
                raise DataFetchError(
                    path or url or "?", "json",
                    "jmespath package is required when 'jmespath' config key is set — pip install jmespath",
                ) from exc
            except Exception as exc:
                raise DataFetchError(path or url or "?", "json", f"jmespath error: {exc}") from exc

        return data
