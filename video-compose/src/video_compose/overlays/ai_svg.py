from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import AiSvgOverlay

logger = logging.getLogger(__name__)

_CACHE_DIR = Path.home() / ".video_compose" / "cache" / "ai_svg"

_SVG_FENCE_RE = re.compile(r"```(?:svg|xml)?\s*([\s\S]*?)```", re.IGNORECASE)

_SYSTEM = (
    "You are an expert SVG artist. Output ONLY the raw SVG element — no markdown, "
    "no explanation, no code fences. Start with <svg and end with </svg>. "
    "Use a transparent background (no <rect fill> covering the whole canvas). "
    "Use clean, minimal code. Ensure all text uses web-safe or embedded fonts."
)

_POSITION_TO_XY = {
    "center":            ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
    "top":               ("(main_w-overlay_w)/2", "0"),
    "bottom":            ("(main_w-overlay_w)/2", "main_h-overlay_h"),
    "top-left":          ("0", "0"),
    "top-right":         ("main_w-overlay_w", "0"),
    "bottom-left":       ("0", "main_h-overlay_h"),
    "bottom-right":      ("main_w-overlay_w", "main_h-overlay_h"),
    "left":              ("0", "(main_h-overlay_h)/2"),
    "right":             ("main_w-overlay_w", "(main_h-overlay_h)/2"),
    "lower_third":       ("(main_w-overlay_w)/2", "main_h*0.78"),
    "lower_third_left":  ("main_w*0.05", "main_h*0.78"),
    "lower_third_right": ("main_w*0.95-overlay_w", "main_h*0.78"),
    "lower_third_2":     ("(main_w-overlay_w)/2", "main_h*0.86"),
}


def render_ai_svg_overlay(
    ov: "AiSvgOverlay",
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    work_dir: Path,
    index: int,
) -> dict:
    """Generate an SVG via Claude, rasterise via cairosvg, composite with alpha."""
    from video_compose.overlays.svg import render_svg_overlay

    svg_content = _get_or_generate(ov, width, height)

    # Build a synthetic SvgOverlay-like object to reuse the svg renderer
    class _FakeSvgOv:
        content = svg_content
        src = None
        position = ov.position
        x_pct = ov.x_pct
        y_pct = ov.y_pct
        width_pct = ov.width_pct
        height_pct = ov.height_pct
        opacity = ov.opacity
        z_order = ov.z_order
        timing = ov.timing

    return render_svg_overlay(_FakeSvgOv(), segment_duration, width, height, fps, work_dir, index)


def _cache_key(prompt: str, style: str | None, w: int, h: int) -> str:
    raw = f"{prompt}|{style or ''}|{w}x{h}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _get_or_generate(ov: "AiSvgOverlay", width: int, height: int) -> str:
    key = _cache_key(ov.prompt, ov.style, width, height)
    cache_path = _CACHE_DIR / f"{key}.svg"

    if ov.cache and cache_path.exists():
        logger.debug("ai_svg cache hit: %s", key)
        return cache_path.read_text(encoding="utf-8")

    svg = _generate(ov, width, height)

    if ov.cache:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(svg, encoding="utf-8")

    return svg


def _generate(ov: "AiSvgOverlay", width: int, height: int) -> str:
    from auth_api_key import get_key
    import anthropic

    prompt = ov.prompt
    if ov.style:
        prompt += f" Style: {ov.style}."
    prompt += f" Canvas size: {width}×{height}px. Use viewBox='0 0 {width} {height}'."

    logger.info("Generating ai_svg via %s…", ov.model)
    client = anthropic.Anthropic(api_key=get_key("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=ov.model,
        max_tokens=4096,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(b.text for b in response.content if hasattr(b, "text"))
    return _extract_svg(raw)


def _extract_svg(text: str) -> str:
    m = _SVG_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    start = text.find("<svg")
    end = text.rfind("</svg>")
    if start != -1 and end != -1:
        return text[start: end + 6]
    return text.strip()
