"""
SpecGenerator — routes a description to a TVCS spec via template or scratch.

Routing logic:
  1. If use_templates=True:
       a. TemplatePicker selects best template (with confidence score)
       b. If confidence >= min_confidence:
            TemplateInstantiator fills variables
            If no missing_required → TemplateEngine fills → validate → return
            If missing_required → return FillResult with missing list (caller prompts user)
       c. If confidence < min_confidence → fall through to scratch
  2. Scratch path:
       PromptBuilder builds system prompt → LLM generates spec → SpecValidator validates

CLI flag --no-templates forces the scratch path.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.templates.engine import MissingVariable


@dataclass
class GenerateResult:
    spec: dict | None                             # None if missing_required is non-empty
    path: str                                     # "template" | "scratch"
    template_id: str | None = None               # set when path="template"
    missing_required: list["MissingVariable"] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    repair_rounds: int = 0


class SpecGenerator:
    """Routes a description to a TVCS spec via template-first or scratch fallback."""

    def __init__(
        self,
        model: str | None = None,
        min_confidence: float | None = None,
    ) -> None:
        self._model = model or _default_model()
        self._min_confidence = min_confidence  # None → use config

    def generate(
        self,
        description: str,
        *,
        use_templates: bool = True,
        min_confidence: float | None = None,
        user_overrides: dict[str, Any] | None = None,
        output_width: int = 1920,
        output_height: int = 1080,
        fps: int = 30,
        total_duration: float | None = None,
        data_context: str | None = None,
        style_hints: str | None = None,
        category_filter: str | None = None,
        auto_repair: bool = True,
    ) -> GenerateResult:
        """Generate a TVCS spec from a free-text description.

        Args:
            description:     Free-text description of the desired video.
            use_templates:   If False, always use scratch generation.
            min_confidence:  Override registry/config threshold.
            user_overrides:  Variable values the user has supplied (for template path).
            output_width/height/fps: Output dimensions.
            total_duration:  Desired video length hint.
            data_context:    Data source description for scratch generation.
            style_hints:     Style/branding hints.
            category_filter: Restrict template search to one category.
            auto_repair:     Auto-repair validation errors with LLM.

        Returns:
            GenerateResult — check .missing_required before rendering.
        """
        conf_threshold = min_confidence or self._min_confidence or _default_min_confidence()

        if use_templates:
            result = self._try_template_path(
                description=description,
                min_confidence=conf_threshold,
                user_overrides=user_overrides or {},
                category_filter=category_filter,
                auto_repair=auto_repair,
            )
            if result is not None:
                return result

        return self._scratch_path(
            description=description,
            output_width=output_width,
            output_height=output_height,
            fps=fps,
            total_duration=total_duration,
            data_context=data_context,
            style_hints=style_hints,
            auto_repair=auto_repair,
        )

    # ------------------------------------------------------------------
    # Template path
    # ------------------------------------------------------------------

    def _try_template_path(
        self,
        description: str,
        min_confidence: float,
        user_overrides: dict[str, Any],
        category_filter: str | None,
        auto_repair: bool,
    ) -> GenerateResult | None:
        from video_compose.templates.registry import TemplateRegistry
        from video_compose.llm.template_picker import TemplatePicker
        from video_compose.llm.template_instantiator import TemplateInstantiator
        from video_compose.templates.engine import TemplateEngine
        from video_compose.llm.spec_validator import SpecValidator

        registry = TemplateRegistry()
        picker = TemplatePicker(registry=registry, model=self._model)
        pick = picker.pick(description, min_confidence=min_confidence, category_filter=category_filter)

        if not pick.matched:
            return None  # fall back to scratch

        template = registry.get(pick.template_id)
        instantiator = TemplateInstantiator(model=self._model)
        fill_result = instantiator.fill_from_description(template, description, user_overrides)

        if fill_result.missing_required:
            return GenerateResult(
                spec=None,
                path="template",
                template_id=pick.template_id,
                missing_required=fill_result.missing_required,
                warnings=fill_result.warnings,
            )

        engine = TemplateEngine()
        spec_dict = engine.fill(template, fill_result.variables)

        try:
            validator = SpecValidator(model=self._model)
            validated = validator.validate(spec_dict, auto_repair=auto_repair)
            return GenerateResult(
                spec=validated.spec,
                path="template",
                template_id=pick.template_id,
                warnings=validated.warnings + fill_result.warnings,
                repair_rounds=validated.repair_rounds,
            )
        except Exception as exc:
            # Template path failed validation — fall through to scratch
            import warnings
            warnings.warn(f"Template {pick.template_id!r} fill failed validation: {exc}")
            return None

    # ------------------------------------------------------------------
    # Scratch path
    # ------------------------------------------------------------------

    def _scratch_path(
        self,
        description: str,
        output_width: int,
        output_height: int,
        fps: int,
        total_duration: float | None,
        data_context: str | None,
        style_hints: str | None,
        auto_repair: bool,
    ) -> GenerateResult:
        from video_compose.llm.prompt_builder import PromptBuilder
        from video_compose.llm.spec_validator import SpecValidator

        pb = PromptBuilder()
        system_prompt = pb.build_system_prompt()
        user_prompt = pb.build_user_prompt(
            description,
            output_width=output_width,
            output_height=output_height,
            fps=fps,
            total_duration=total_duration,
            data_context=data_context,
            style_hints=style_hints,
        )

        raw = _llm_call(system_prompt, user_prompt, self._model)
        try:
            spec_dict = json.loads(raw.strip())
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM did not return valid JSON: {exc}\nRaw output:\n{raw[:500]}") from exc

        validator = SpecValidator(model=self._model)
        validated = validator.validate(spec_dict, auto_repair=auto_repair)
        return GenerateResult(
            spec=validated.spec,
            path="scratch",
            warnings=validated.warnings,
            repair_rounds=validated.repair_rounds,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_model() -> str:
    from video_compose.templates.config import load_config
    return load_config().llm_model


def _default_min_confidence() -> float:
    from video_compose.templates.config import load_config
    return load_config().min_confidence


def _llm_call(system: str, user: str, model: str) -> str:
    from video_compose.llm.template_picker import _get_client
    client = _get_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.4,
        max_tokens=4096,
    )
    return response.choices[0].message.content or ""
