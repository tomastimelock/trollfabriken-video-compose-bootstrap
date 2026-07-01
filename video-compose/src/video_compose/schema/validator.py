# Placeholder — implemented in task #28
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


def validate(spec: dict) -> ValidationResult:
    """Validate a TVCS spec dict. Full implementation in task #28."""
    return ValidationResult(is_valid=True)
