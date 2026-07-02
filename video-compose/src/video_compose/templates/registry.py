"""
TemplateRegistry — locates, indexes, and loads TVCS template files.

Scan order (later entries shadow earlier):
  1. <package>/templates/bundled/**/*.json   (bundled templates)
  2. ~/.video_compose/templates/**/*.json    (user templates; id must start with "user.")
  3. Any extra_dirs supplied at construction  (id must start with "user.")
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_BUNDLED_DIR = Path(__file__).parent / "bundled"
_USER_DEFAULT_DIR = Path.home() / ".video_compose" / "templates"
_PREVIEW_DIR = Path(__file__).parent / "previews"

_USER_PREFIX = "user."


@dataclass
class TemplateInfo:
    """Lightweight summary of a template (no full spec loaded)."""
    id: str
    name: str
    category: str
    tags: list[str]
    description: str
    preview_thumbnail: str | None
    preview_full: str | None
    author: str
    version: str
    variables: list[dict]     # [{name, type, label, required, default, description}]
    _path: Path = field(repr=False)

    def variable_names(self) -> list[str]:
        return [v["name"] for v in self.variables]

    def required_variables(self) -> list[dict]:
        return [v for v in self.variables if v.get("required", True) and v.get("default") is None]

    def to_compact_dict(self) -> dict[str, Any]:
        """Compact dict for LLM catalog injection."""
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "tags": self.tags,
            "description": self.description,
            "variables": [
                {"name": v["name"], "type": v.get("type", "string"),
                 "label": v.get("label", ""), "required": v.get("required", True)}
                for v in self.variables
            ],
        }


class TemplateRegistry:
    """Scans and indexes TVCS template files from bundled and user directories."""

    def __init__(self, extra_dirs: list[Path] | None = None) -> None:
        self._extra_dirs: list[Path] = extra_dirs or []
        self._index: dict[str, TemplateInfo] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
        search_query: str | None = None,
    ) -> list[TemplateInfo]:
        """Return all matching templates, sorted by category then name."""
        idx = self._ensure_index()
        results = list(idx.values())

        if category:
            results = [t for t in results if t.category == category]

        if tags:
            tag_set = set(tags)
            results = [t for t in results if tag_set & set(t.tags)]

        if search_query:
            results = _rank_by_query(results, search_query)
        else:
            results.sort(key=lambda t: (t.category, t.name))

        return results

    def get(self, template_id: str) -> dict:
        """Load and return the full template dict for *template_id*.

        Raises:
            KeyError: Template not found.
        """
        idx = self._ensure_index()
        if template_id not in idx:
            available = ", ".join(sorted(idx.keys())[:10])
            raise KeyError(
                f"Template {template_id!r} not found. "
                f"Available (first 10): {available}"
            )
        return json.loads(idx[template_id]._path.read_text(encoding="utf-8"))

    def get_info(self, template_id: str) -> TemplateInfo:
        """Return the TemplateInfo for *template_id*."""
        idx = self._ensure_index()
        if template_id not in idx:
            raise KeyError(f"Template {template_id!r} not found.")
        return idx[template_id]

    def get_preview_path(
        self, template_id: str, size: str = "thumbnail"
    ) -> Path | None:
        """Return the absolute path to a preview image, or None if not found.

        Args:
            template_id: Template id.
            size: "thumbnail" (400×225) or "full" (1920×1080).
        """
        idx = self._ensure_index()
        if template_id not in idx:
            return None
        info = idx[template_id]
        rel = info.preview_thumbnail if size == "thumbnail" else info.preview_full
        if not rel:
            return None

        # rel is something like "previews/thumbnails/foo.jpg" — resolve from templates dir
        candidate = _PREVIEW_DIR.parent / rel
        if candidate.exists():
            return candidate

        # Fallback: just filename inside _PREVIEW_DIR (no subdir)
        candidate2 = _PREVIEW_DIR / Path(rel).name
        if candidate2.exists():
            return candidate2

        return None

    def categories(self) -> list[str]:
        """Return sorted list of unique category names."""
        idx = self._ensure_index()
        return sorted({t.category for t in idx.values()})

    def reload(self) -> None:
        """Force a fresh index scan on next access."""
        self._index = None

    def compact_catalog(self) -> list[dict]:
        """Return compact catalog dicts for all templates (for LLM injection)."""
        return [t.to_compact_dict() for t in self.list()]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_index(self) -> dict[str, TemplateInfo]:
        if self._index is None:
            self._index = self._build_index()
        return self._index

    def _build_index(self) -> dict[str, TemplateInfo]:
        index: dict[str, TemplateInfo] = {}

        # 1. Bundled templates (any id allowed)
        if _BUNDLED_DIR.exists():
            for path in sorted(_BUNDLED_DIR.rglob("*.json")):
                info = _load_info(path, require_user_prefix=False)
                if info:
                    index[info.id] = info

        # 2. User default dir
        if _USER_DEFAULT_DIR.exists():
            for path in sorted(_USER_DEFAULT_DIR.rglob("*.json")):
                info = _load_info(path, require_user_prefix=True)
                if info:
                    index[info.id] = info  # shadows bundled

        # 3. Extra dirs
        for extra in self._extra_dirs:
            if extra.exists():
                for path in sorted(extra.rglob("*.json")):
                    info = _load_info(path, require_user_prefix=True)
                    if info:
                        index[info.id] = info

        return index


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_info(path: Path, require_user_prefix: bool) -> TemplateInfo | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        meta = raw.get("template")
        if not meta or not isinstance(meta, dict):
            return None
        template_id = meta.get("id", "")
        if not template_id:
            return None
        if require_user_prefix and not template_id.startswith(_USER_PREFIX):
            return None
        return TemplateInfo(
            id=template_id,
            name=meta.get("name", template_id),
            category=meta.get("category", "uncategorized"),
            tags=meta.get("tags", []),
            description=meta.get("description", ""),
            preview_thumbnail=meta.get("preview_thumbnail"),
            preview_full=meta.get("preview_full"),
            author=meta.get("author", ""),
            version=meta.get("version", "1.0"),
            variables=meta.get("variables", []),
            _path=path,
        )
    except Exception:
        return None


def _rank_by_query(templates: list[TemplateInfo], query: str) -> list[TemplateInfo]:
    """Simple keyword ranking — no heavy deps."""
    q_tokens = set(re.split(r"\W+", query.lower()))

    def _score(t: TemplateInfo) -> int:
        text = " ".join([t.id, t.name, t.category, t.description] + t.tags).lower()
        return sum(1 for tok in q_tokens if tok and tok in text)

    scored = [(t, _score(t)) for t in templates]
    matched = [(t, s) for t, s in scored if s > 0]
    if not matched:
        return []
    return [t for t, _ in sorted(matched, key=lambda x: x[1], reverse=True)]
