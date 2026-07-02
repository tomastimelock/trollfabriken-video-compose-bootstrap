"""
SpecValidator — validates a TVCS spec dict and attempts LLM repair on errors.

Repair loop (max 3 attempts):
  1. Validate spec with the TVCS semantic validator.
  2. If valid → return.
  3. If errors → send spec + errors to LLM asking for a corrected JSON.
  4. Parse LLM response → go to 1.
  5. If still invalid after max attempts → raise SpecRepairError.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

_MAX_REPAIR_ROUNDS = 3

_REPAIR_SYSTEM = """\
You are a TVCS (Trollfabriken Video Composition Spec) repair assistant.

You will receive a JSON spec that failed validation and a list of errors.
Return a corrected JSON spec that fixes all errors.

Rules:
- Return ONLY the corrected JSON object. No markdown fences, no explanation.
- Do not add fields not in the TVCS schema.
- Preserve all content that was not causing errors.
- Fix only what is broken.
"""

_REPAIR_USER_TMPL = """\
Spec with errors:
{spec_json}

Validation errors:
{errors}

Return the corrected TVCS spec JSON.
"""


@dataclass
class ValidationRound:
    attempt: int
    errors: list[str]
    warnings: list[str]
    spec_before: dict


class SpecRepairError(RuntimeError):
    """Raised when the spec cannot be repaired within max attempts."""

    def __init__(self, rounds: list[ValidationRound]) -> None:
        self.rounds = rounds
        last_errors = rounds[-1].errors if rounds else []
        super().__init__(
            f"Spec could not be repaired after {len(rounds)} attempt(s). "
            f"Last errors: {'; '.join(last_errors[:3])}"
        )


@dataclass
class ValidatedSpec:
    spec: dict
    warnings: list[str] = field(default_factory=list)
    repair_rounds: int = 0


class SpecValidator:
    """Validates and optionally repairs a TVCS spec dict."""

    def __init__(self, model: str | None = None) -> None:
        self._model = model or _default_model()

    def validate(self, spec: dict, auto_repair: bool = True) -> ValidatedSpec:
        """Validate *spec*, optionally repairing errors with LLM.

        Args:
            spec:         TVCS spec dict.
            auto_repair:  If True, attempt LLM repair on validation errors.

        Returns:
            ValidatedSpec with the (possibly repaired) spec and warnings.

        Raises:
            SpecRepairError: Validation failed and could not be repaired.
            ValueError:      Validation failed and auto_repair=False.
        """
        from video_compose.schema.validator import validate as _tvcs_validate

        rounds: list[ValidationRound] = []
        current = spec

        for attempt in range(1, _MAX_REPAIR_ROUNDS + 1):
            result = _tvcs_validate(current)
            if result.is_valid:
                return ValidatedSpec(
                    spec=current,
                    warnings=result.warnings,
                    repair_rounds=attempt - 1,
                )

            round_info = ValidationRound(
                attempt=attempt,
                errors=list(result.errors),
                warnings=list(result.warnings),
                spec_before=current,
            )
            rounds.append(round_info)

            if not auto_repair:
                raise ValueError(
                    f"Spec validation failed:\n"
                    + "\n".join(f"  {e}" for e in result.errors)
                )

            # Try LLM repair
            try:
                repaired_str = self._repair(current, result.errors)
                current = json.loads(repaired_str)
            except Exception:
                break  # can't parse repair → stop trying

        raise SpecRepairError(rounds)

    def _repair(self, spec: dict, errors: list[str]) -> str:
        user_msg = _REPAIR_USER_TMPL.format(
            spec_json=json.dumps(spec, indent=2),
            errors="\n".join(f"- {e}" for e in errors),
        )
        return _llm_call(_REPAIR_SYSTEM, user_msg, self._model)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
        temperature=0.1,
        max_tokens=4096,
    )
    return response.choices[0].message.content or ""
