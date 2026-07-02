"""
TemplateInstantiator — LLM fills template variables from a description.

Fillable by LLM:  string, color, number, duration, boolean
Requires user:    image_path, video_path, audio_path, data_ref, data_source_config

user_overrides always wins over AI-filled values.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.templates.engine import MissingVariable

_AI_FILLABLE = {"string", "color", "number", "duration", "boolean"}
_USER_REQUIRED = {"image_path", "video_path", "audio_path", "data_ref", "data_source_config"}

_FILL_SYSTEM = """\
You are filling variable slots for a TVCS video template.

Given the template's variable declarations and a video description, fill values
for all fillable variables (types: string, color, number, duration, boolean).

Return ONLY a JSON object mapping variable names to their values.
No markdown, no explanation — raw JSON only.

Rules:
- color values must be hex strings like "#rrggbb"
- duration/number values must be JSON numbers (not strings)
- boolean values must be JSON true/false
- string values must be appropriate for their label/description
- Do NOT invent paths for image_path, video_path, audio_path types — skip them
- Do NOT fill data_ref or data_source_config types — skip them
"""

_FILL_USER_TMPL = """\
Video description: {description}

Variables to fill:
{vars_json}

Return a JSON object with the filled values. Skip image_path, video_path, audio_path, data_ref, and data_source_config types.
"""


@dataclass
class FillResult:
    variables: dict[str, Any]                    # all filled values (AI + defaults + overrides)
    missing_required: list["MissingVariable"]     # required vars that need user input
    ai_filled: list[str]                          # names filled by AI
    warnings: list[str] = field(default_factory=list)


class TemplateInstantiator:
    """Uses an LLM to fill template variables from a free-text description."""

    def __init__(self, model: str | None = None) -> None:
        self._model = model or _default_model()

    def fill_from_description(
        self,
        template: dict,
        description: str,
        user_overrides: dict[str, Any] | None = None,
    ) -> FillResult:
        """Fill variables using LLM + user overrides.

        Args:
            template:       Full template dict.
            description:    User description of the desired video.
            user_overrides: Values the user has explicitly provided; always win.

        Returns:
            FillResult with filled variables dict and missing_required list.
        """
        from video_compose.templates.engine import TemplateEngine, MissingVariable

        overrides = user_overrides or {}
        meta = template.get("template") or {}
        var_decls: list[dict] = meta.get("variables", [])

        # Split into AI-fillable and user-required
        ai_targets = [
            v for v in var_decls
            if v.get("type", "string") in _AI_FILLABLE
            and v["name"] not in overrides
        ]
        user_targets = [
            v for v in var_decls
            if v.get("type", "string") in _USER_REQUIRED
            and v["name"] not in overrides
            and v.get("required", True)
            and v.get("default") is None
        ]

        # Ask LLM to fill AI-fillable vars
        ai_filled_names: list[str] = []
        ai_values: dict[str, Any] = {}
        if ai_targets:
            raw = self._ask_llm(description, ai_targets)
            ai_values = _parse_fill_response(raw)
            ai_filled_names = list(ai_values.keys())

        # Merge: defaults < AI < user_overrides
        engine = TemplateEngine()
        merged: dict[str, Any] = {}

        for decl in var_decls:
            name = decl["name"]
            if name in overrides:
                merged[name] = overrides[name]
            elif name in ai_values:
                merged[name] = ai_values[name]
            elif decl.get("default") is not None:
                merged[name] = decl["default"]
            # else: missing — handled below

        # Find still-missing required vars
        missing_required = engine.list_unfilled(template, merged)

        return FillResult(
            variables=merged,
            missing_required=missing_required,
            ai_filled=ai_filled_names,
        )

    def _ask_llm(self, description: str, var_decls: list[dict]) -> str:
        vars_json = json.dumps(
            [
                {
                    "name": v["name"],
                    "type": v.get("type", "string"),
                    "label": v.get("label", ""),
                    "description": v.get("description", ""),
                    "required": v.get("required", True),
                    "choices": v.get("choices"),
                }
                for v in var_decls
            ],
            indent=2,
        )
        user_msg = _FILL_USER_TMPL.format(
            description=description,
            vars_json=vars_json,
        )
        return _llm_call(_FILL_SYSTEM, user_msg, self._model)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_fill_response(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw.strip())
    except Exception:
        return {}


def _default_model() -> str:
    from video_compose.templates.config import load_config
    return load_config().llm_model


def _llm_call(system: str, user: str, model: str) -> str:
    from video_compose.llm.template_picker import _get_client
    client = _get_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
        max_tokens=1024,
    )
    return response.choices[0].message.content or ""
