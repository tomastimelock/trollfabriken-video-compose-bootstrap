from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_BRAND_PATH = Path.home() / ".video_compose" / "brand.toml"


class BrandKit(BaseModel):
    """Persistent brand identity applied as defaults to every render."""
    primary_color: str = Field(default="#ffffff", description="Primary text/element color")
    accent_color: str = Field(default="#ff6b35", description="Accent/highlight color")
    background_color: str = Field(default="#0d0d1a", description="Default background color")
    font_family: str = Field(default="Inter", description="Default font family")
    logo_path: str | None = Field(default=None, description="Path to logo PNG (transparent recommended)")
    logo_position: str = Field(default="top-right", description="Logo position preset")
    logo_opacity: float = Field(default=0.3, ge=0.0, le=1.0)
    logo_scale_pct: float = Field(default=10.0, ge=0.5, le=50.0, description="Logo width as % of canvas")


def load_brand() -> BrandKit | None:
    """Load brand kit from ~/.video_compose/brand.toml. Returns None if not set."""
    if not _BRAND_PATH.exists():
        return None
    try:
        import tomllib
        data = tomllib.loads(_BRAND_PATH.read_text(encoding="utf-8"))
        return BrandKit.model_validate(data)
    except Exception as exc:
        logger.warning("Failed to load brand kit: %s", exc)
        return None


def save_brand(kit: BrandKit) -> None:
    """Persist a BrandKit to ~/.video_compose/brand.toml."""
    _BRAND_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for key, val in kit.model_dump().items():
        if val is None:
            continue
        if isinstance(val, bool):
            lines.append(f"{key} = {'true' if val else 'false'}")
        elif isinstance(val, str):
            lines.append(f'{key} = "{val}"')
        else:
            lines.append(f"{key} = {val}")
    _BRAND_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Brand kit saved to %s", _BRAND_PATH)


def reset_brand() -> None:
    """Delete the brand kit file."""
    _BRAND_PATH.unlink(missing_ok=True)


def apply_brand_to_spec(spec, brand: BrandKit) -> None:
    """Apply brand defaults to a TVCSSpec in-place (only fills gaps, never overrides)."""
    # Theme: fill background + font if still at default
    if spec.theme:
        if spec.theme.background == "#0d0d1a":
            spec.theme.background = brand.background_color
        if spec.theme.font == "default":
            spec.theme.font = brand.font_family
        if spec.theme.text_color == "#ffffff":
            spec.theme.text_color = brand.primary_color

    # Logo: inject as global watermark if not already set
    if brand.logo_path and not getattr(spec, "watermark", None):
        from types import SimpleNamespace
        from video_compose.schema.spec import WatermarkConfig
        try:
            spec.__dict__["watermark"] = WatermarkConfig(
                src=brand.logo_path,
                position=brand.logo_position,
                opacity=brand.logo_opacity,
                scale_pct=brand.logo_scale_pct,
            )
        except Exception:
            pass
