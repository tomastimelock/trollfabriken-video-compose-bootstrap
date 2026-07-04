from __future__ import annotations

import copy
import logging
import re

logger = logging.getLogger(__name__)

_MAX_ITEMS = 50
_VAR_RE = re.compile(r"\{\{([^}]+)\}\}")


class IterationExpander:
    """Expands segments that carry an `iterate` field into N cloned segments.

    For each iterated segment, resolves the data source to a list, then clones
    the segment model N times injecting per-item variables into all string fields:
        {{item.field}}   — value of that field in the current row
        {{item_index}}   — 0-based position in the array
        {{item_total}}   — total number of items

    The original segment is replaced by the expanded clones in the returned list.
    Segments without `iterate` pass through unchanged.
    """

    def __init__(self, resolver) -> None:
        self._resolver = resolver

    def expand(self, segments: list) -> list:
        result = []
        for seg in segments:
            iterate_ref = getattr(seg, "iterate", None)
            if not iterate_ref:
                result.append(seg)
                continue

            items = self._resolve_items(iterate_ref)
            if not items:
                logger.warning("iterate ref %r resolved to empty list — skipping segment %r", iterate_ref, seg.id)
                continue

            if len(items) > _MAX_ITEMS:
                logger.warning(
                    "iterate on segment %r: %d items exceeds max %d — clamping",
                    seg.id, len(items), _MAX_ITEMS
                )
                items = items[:_MAX_ITEMS]

            total = len(items)
            for idx, item in enumerate(items):
                clone = copy.deepcopy(seg)
                # Unique ID per clone
                object.__setattr__(clone, "id", f"{seg.id}_{idx}")
                # Inject variables by deep-walking all string fields
                extra = {
                    "item_index": idx,
                    "item_total": total,
                    **{f"item.{k}": v for k, v in _flatten(item).items()},
                }
                _inject_strings(clone, extra)
                result.append(clone)

        return result

    def _resolve_items(self, ref: str) -> list:
        try:
            data = self._resolver.resolve(ref)
        except Exception as exc:
            logger.error("iterate: failed to resolve %r: %s", ref, exc)
            return []

        if data is None:
            return []
        if isinstance(data, list):
            return data
        # pandas DataFrame → list of dicts
        try:
            import pandas as pd
            if isinstance(data, pd.DataFrame):
                return data.to_dict(orient="records")
        except ImportError:
            pass
        logger.warning("iterate: %r resolved to %s, expected list", ref, type(data).__name__)
        return []


def _flatten(item) -> dict[str, object]:
    """Convert a row (dict or object with __dict__) to a flat str→value mapping."""
    if isinstance(item, dict):
        return item
    if hasattr(item, "__dict__"):
        return vars(item)
    return {"value": item}


def _inject_strings(obj, variables: dict) -> None:
    """Recursively substitute {{key}} tokens in all string fields of a Pydantic model."""
    if hasattr(obj, "model_fields"):
        for field_name in obj.model_fields:
            val = getattr(obj, field_name, None)
            if isinstance(val, str):
                new_val = _sub(val, variables)
                try:
                    object.__setattr__(obj, field_name, new_val)
                except Exception:
                    pass
            elif isinstance(val, list):
                for item in val:
                    if hasattr(item, "model_fields"):
                        _inject_strings(item, variables)
            elif hasattr(val, "model_fields"):
                _inject_strings(val, variables)
    elif isinstance(obj, dict):
        for k in list(obj.keys()):
            if isinstance(obj[k], str):
                obj[k] = _sub(obj[k], variables)


def _sub(s: str, variables: dict) -> str:
    def replacer(m: re.Match) -> str:
        key = m.group(1).strip()
        val = variables.get(key)
        return str(val) if val is not None else m.group(0)
    return _VAR_RE.sub(replacer, s)
