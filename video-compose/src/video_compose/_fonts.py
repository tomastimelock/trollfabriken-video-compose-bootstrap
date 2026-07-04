"""
Font resolution for video-compose.

Maps logical font family names to bundled TTF paths so templates work
on any system without requiring fonts to be installed.

Bundled fonts take priority; system fonts are used as fallback for
families not in the bundle (e.g. custom brand fonts).
"""
from __future__ import annotations

from pathlib import Path

_FONTS_DIR = Path(__file__).parent / "fonts"

_BUNDLED: dict[str, dict[str, str]] = {
    "inter": {
        "regular":  "Inter-Regular.ttf",
        "medium":   "Inter-Medium.ttf",
        "bold":     "Inter-SemiBold.ttf",
        "semibold": "Inter-SemiBold.ttf",
        "black":    "Inter-SemiBold.ttf",
    },
}


def resolve_font_family(family: str, weight: str = "bold") -> str:
    """Return an absolute path to a bundled TTF, or the original family name.

    If the family is bundled (e.g. "Inter"), returns the absolute path so
    text-fx loads it directly without a system font lookup.

    If the family is not bundled, returns it unchanged so text-fx attempts
    its normal matplotlib / filesystem discovery.
    """
    key = family.lower().strip()
    weight_key = weight.lower().strip()

    bundle = _BUNDLED.get(key)
    if bundle is None:
        return family

    filename = bundle.get(weight_key) or bundle.get("regular", "")
    if not filename:
        return family

    path = _FONTS_DIR / filename
    if path.exists():
        return str(path)

    return family
