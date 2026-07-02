"""
TemplateEngine — fills {{var}} placeholders in a TVCS template dict.

Fill semantics:
  - Whole-slot substitution: a field whose entire value is "{{var}}" is replaced
    with the typed variable value (float for number/duration, bool for boolean,
    any type for data_ref/data_source_config).
  - Partial substitution: "Hello {{name}}!" substitutes {{name}} with its string
    representation; the result is always a string.
  - Deep walk: substitution recurses into all dicts and lists.
  - After fill the "template" metadata block is stripped; the result is a plain
    TVCS dict ready for validate() / compose().
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

_WHOLE_RE = re.compile(r"^\{\{(\w+)\}\}$")
_SLOT_RE = re.compile(r"\{\{(\w+)\}\}")

_NUMERIC_TYPES = {"number", "duration"}
_BOOL_TYPE = "boolean"


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass
class MissingVariable:
    name: str
    label: str
    type: str
    description: str


class TemplateFillError(ValueError):
    """Raised when required variables are absent and have no default."""

    def __init__(self, missing: list[MissingVariable]) -> None:
        self.missing = missing
        names = ", ".join(f"{m.name} ({m.label or m.type})" for m in missing)
        super().__init__(f"Missing required template variables: {names}")


class TemplateTypeError(ValueError):
    """Raised when a variable value cannot be coerced to its declared type."""


# ---------------------------------------------------------------------------
# TemplateEngine
# ---------------------------------------------------------------------------

class TemplateEngine:
    """Substitutes {{var}} placeholders and returns a clean TVCS spec dict."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fill(self, template: dict, variables: dict[str, Any]) -> dict:
        """Fill *template* with *variables*.

        Args:
            template:  Raw template dict (may contain {{var}} in string fields).
            variables: User-supplied values; merged with declared defaults.

        Returns:
            Clean TVCS spec dict (template metadata block stripped).

        Raises:
            TemplateFillError: One or more required variables have no value/default.
            TemplateTypeError: A value cannot be coerced to its declared type.
        """
        var_decls = self._declarations(template)
        merged = self._merge(var_decls, variables)
        self._check_required(var_decls, merged)
        merged = self._coerce_all(var_decls, merged)
        result = _deep_sub(copy.deepcopy(template), merged)
        result.pop("template", None)
        return result

    def list_unfilled(
        self,
        template: dict,
        variables: dict[str, Any] | None = None,
    ) -> list[MissingVariable]:
        """Return variables that would be missing if fill() were called now.

        Includes required vars with no default and no value in *variables*.
        Optional vars (required=False) with no provided value are excluded.
        """
        var_decls = self._declarations(template)
        provided = variables or {}
        missing = []
        for name, decl in var_decls.items():
            if name in provided:
                continue
            if decl.get("default") is not None:
                continue
            if decl.get("required", True):
                missing.append(_to_missing(name, decl))
        return missing

    def list_variables(self, template: dict) -> list[dict]:
        """Return all variable declarations from the template metadata."""
        meta = template.get("template") or {}
        return list(meta.get("variables", []))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _declarations(self, template: dict) -> dict[str, dict]:
        meta = template.get("template") or {}
        return {v["name"]: v for v in meta.get("variables", [])}

    def _merge(self, var_decls: dict[str, dict], user: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for name, decl in var_decls.items():
            if name in user:
                merged[name] = user[name]
            elif decl.get("default") is not None:
                merged[name] = decl["default"]
        # Also include any extra user-supplied keys (undeclared overrides)
        for name, value in user.items():
            if name not in merged:
                merged[name] = value
        return merged

    def _check_required(
        self, var_decls: dict[str, dict], merged: dict[str, Any]
    ) -> None:
        missing = [
            _to_missing(name, decl)
            for name, decl in var_decls.items()
            if decl.get("required", True) and name not in merged
        ]
        if missing:
            raise TemplateFillError(missing)

    def _coerce_all(
        self, var_decls: dict[str, dict], merged: dict[str, Any]
    ) -> dict[str, Any]:
        result = {}
        for name, value in merged.items():
            type_hint = var_decls.get(name, {}).get("type", "string")
            result[name] = _coerce(value, type_hint, name)
        return result


# ---------------------------------------------------------------------------
# Deep substitution
# ---------------------------------------------------------------------------

def _deep_sub(obj: Any, merged: dict[str, Any]) -> Any:
    if isinstance(obj, str):
        return _sub_str(obj, merged)
    if isinstance(obj, dict):
        return {k: _deep_sub(v, merged) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_sub(item, merged) for item in obj]
    return obj


def _sub_str(s: str, merged: dict[str, Any]) -> Any:
    # Whole-field: "{{var}}" → typed value (may be non-string)
    m = _WHOLE_RE.match(s)
    if m:
        name = m.group(1)
        return merged.get(name, s)  # already coerced; leave literal if undeclared

    # Partial: "text {{var}} more" → string
    def _repl(match: re.Match) -> str:
        name = match.group(1)
        val = merged.get(name)
        return str(val) if val is not None else match.group(0)

    return _SLOT_RE.sub(_repl, s)


# ---------------------------------------------------------------------------
# Type coercion
# ---------------------------------------------------------------------------

def _coerce(value: Any, type_hint: str, name: str) -> Any:
    if value is None:
        return value
    try:
        if type_hint in _NUMERIC_TYPES:
            return float(value)
        if type_hint == _BOOL_TYPE:
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("true", "1", "yes", "on")
        # string, color, image_path, video_path, audio_path, data_ref,
        # data_source_config — keep as-is (or stringify scalars)
        if type_hint == "string" and not isinstance(value, str):
            return str(value)
        return value
    except (ValueError, TypeError) as exc:
        raise TemplateTypeError(
            f"Variable '{name}': cannot coerce {value!r} to type '{type_hint}': {exc}"
        ) from exc


def _to_missing(name: str, decl: dict) -> MissingVariable:
    return MissingVariable(
        name=name,
        label=decl.get("label") or name,
        type=decl.get("type", "string"),
        description=decl.get("description", ""),
    )
