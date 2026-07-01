# Placeholder — implemented in task #27
from __future__ import annotations

from pydantic import BaseModel


class TVCSSpec(BaseModel):
    """Trollfabriken Video Composition Spec — full model defined in task #27."""
    tvcs: str = "1.0"
