"""
TemplatePicker — LLM selects the best template from the catalog.

Sends a compact catalog (id/name/category/description/tags) to the LLM and
asks it to return the best-matching template id with a confidence score.

If confidence < min_confidence the caller should fall back to scratch generation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.templates.registry import TemplateRegistry


@dataclass
class TemplatePickResult:
    template_id: str
    confidence: float        # 0.0–1.0
    reasoning: str
    matched: bool            # False if no good match found


_PICK_SYSTEM = """\
You are a video template selector for the Trollfabriken video composition system.
You have access to a catalog of pre-built TVCS templates.

Given a video description, select the single best matching template.

Respond with ONLY a JSON object — no markdown, no explanation:
{
  "template_id": "<id from catalog or null if no good match>",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<one sentence>"
}

Confidence guide:
  0.8-1.0 = strong match — template fits the request well
  0.6-0.79 = reasonable match — template needs filling but fits the use case
  0.4-0.59 = weak match — template is in the right ballpark
  0.0-0.39 = no good match — set template_id to null
"""

_PICK_USER_TMPL = """\
Video description: {description}

Available templates:
{catalog_json}

Select the best template and return the JSON object.
"""


class TemplatePicker:
    """Picks the best template from the registry for a given description."""

    def __init__(
        self,
        registry: "TemplateRegistry | None" = None,
        model: str | None = None,
    ) -> None:
        from video_compose.templates.registry import TemplateRegistry as _Reg
        self._registry = registry or _Reg()
        self._model = model or _default_model()

    def pick(
        self,
        description: str,
        min_confidence: float = 0.6,
        category_filter: str | None = None,
    ) -> TemplatePickResult:
        """Return the best matching template, or matched=False if below threshold.

        Args:
            description:     User description of the desired video.
            min_confidence:  If best match confidence < this, matched=False.
            category_filter: Restrict search to one category.
        """
        templates = self._registry.list(category=category_filter)
        if not templates:
            return TemplatePickResult(
                template_id="", confidence=0.0,
                reasoning="No templates in registry.", matched=False,
            )

        catalog_json = json.dumps(
            [t.to_compact_dict() for t in templates],
            indent=2,
        )
        user_msg = _PICK_USER_TMPL.format(
            description=description,
            catalog_json=catalog_json,
        )

        raw = _llm_call(_PICK_SYSTEM, user_msg, self._model)
        result = _parse_pick_response(raw)

        if not result.template_id or result.confidence < min_confidence:
            result.matched = False
        else:
            # Verify the id actually exists
            try:
                self._registry.get_info(result.template_id)
                result.matched = True
            except KeyError:
                result.matched = False
                result.reasoning += f" (id {result.template_id!r} not found in registry)"

        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_pick_response(raw: str) -> TemplatePickResult:
    try:
        data = json.loads(raw.strip())
        template_id = data.get("template_id") or ""
        confidence = float(data.get("confidence", 0.0))
        reasoning = str(data.get("reasoning", ""))
        return TemplatePickResult(
            template_id=template_id,
            confidence=max(0.0, min(1.0, confidence)),
            reasoning=reasoning,
            matched=False,  # caller sets this
        )
    except Exception as exc:
        return TemplatePickResult(
            template_id="",
            confidence=0.0,
            reasoning=f"Failed to parse LLM response: {exc}",
            matched=False,
        )


def _default_model() -> str:
    from video_compose.templates.config import load_config
    return load_config().llm_model


def _llm_call(system: str, user: str, model: str) -> str:
    client = _get_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
        max_tokens=256,
    )
    return response.choices[0].message.content or ""


def _get_client():
    try:
        import openai
    except ImportError as exc:
        raise ImportError(
            "openai package required for template picking. "
            "Install with: pip install 'video-compose[llm]'"
        ) from exc

    import os
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        try:
            from auth_api_key import get_key
            key = get_key("OPENAI_API_KEY")
        except Exception:
            pass
    if not key:
        raise ValueError("OPENAI_API_KEY not found in environment or auth_api_key vault")
    return openai.OpenAI(api_key=key)
