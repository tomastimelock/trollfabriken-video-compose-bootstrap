from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any

from video_compose.data.fetcher import DataFetcher, DataFetchError


class APIFetcher(DataFetcher):
    source_type = "api"

    def fetch(self, config: dict) -> Any:
        url: str = config.get("url", "")
        method: str = config.get("method", "GET").upper()
        headers: dict = dict(config.get("headers") or {})
        body: dict | None = config.get("body")
        auth: dict | None = config.get("auth")
        jmespath_expr: str | None = config.get("jmespath")
        timeout: int = int(config.get("timeout", 30))

        if not url:
            raise DataFetchError("api", "api", "'url' is required")

        # Build auth header
        if auth:
            auth_type = (auth.get("type") or "bearer").lower()
            if auth_type == "bearer":
                headers["Authorization"] = f"Bearer {auth.get('token', '')}"
            elif auth_type == "basic":
                import base64
                creds = base64.b64encode(
                    f"{auth.get('username','')}:{auth.get('password','')}".encode()
                ).decode()
                headers["Authorization"] = f"Basic {creds}"
            elif auth_type == "api_key":
                key_header = auth.get("header", "X-API-Key")
                headers[key_header] = auth.get("key", "")

        # Encode body
        data: bytes | None = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                content_type = resp.headers.get("Content-Type", "")
                if "json" in content_type or raw.lstrip().startswith(b"{") or raw.lstrip().startswith(b"["):
                    result = json.loads(raw)
                else:
                    result = raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise DataFetchError(url, "api", f"HTTP {exc.code}: {exc.reason}") from exc
        except Exception as exc:
            raise DataFetchError(url, "api", str(exc)) from exc

        if jmespath_expr:
            try:
                import jmespath as _jmespath
                result = _jmespath.search(jmespath_expr, result)
            except ImportError as exc:
                raise DataFetchError(
                    url, "api",
                    "jmespath package required when 'jmespath' is set — pip install jmespath",
                ) from exc
            except Exception as exc:
                raise DataFetchError(url, "api", f"jmespath error: {exc}") from exc

        return result
