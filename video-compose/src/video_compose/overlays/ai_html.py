from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import AiHtmlOverlay

logger = logging.getLogger(__name__)

_CACHE_DIR = Path.home() / ".video_compose" / "cache" / "ai_html"

_HTML_FENCE_RE = re.compile(r"```(?:html)?\s*([\s\S]*?)```", re.IGNORECASE)

_SYSTEM = (
    "You are an expert frontend engineer creating overlays for video production. "
    "Output a COMPLETE, SELF-CONTAINED HTML document — no markdown, no explanation. "
    "Rules: "
    "1. Background must be pure black (#000000) — it will be keyed out by the video compositor. "
    "2. Do NOT use pure black (#000 / rgb(0,0,0)) for any visible element — use #010101 or similar near-black instead. "
    "3. All CSS must be inline (<style> in <head>). No external stylesheets or CDN. "
    "4. Use only system/web-safe fonts. "
    "5. The document renders at the exact video canvas dimensions; use vw/vh units. "
    "6. Include subtle CSS animations for entrance effects."
)


def render_ai_html_overlay(
    ov: "AiHtmlOverlay",
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    work_dir: Path,
    index: int,
) -> dict:
    """Generate HTML/CSS via Claude, render via web-overlay (Playwright)."""
    try:
        from web_overlay import render_to_webm, RenderConfig
    except ImportError as exc:
        raise RuntimeError(
            "web-overlay is required for ai_html overlays — pip install web-overlay"
        ) from exc

    html_content = _get_or_generate(ov, width, height)

    start = ov.timing.start
    end = ov.timing.end if ov.timing.end is not None else segment_duration
    duration = max(end - start, 0.1)

    out_path = work_dir / f"ai_html_overlay_{index}.webm"
    config = RenderConfig(width=width, height=height, fps=int(fps))
    render_to_webm(html_content, duration=duration, output=out_path, config=config)

    return {"path": out_path, "start": start, "end": end, "x": "0", "y": "0"}


def _cache_key(prompt: str, style: str | None, w: int, h: int) -> str:
    raw = f"{prompt}|{style or ''}|{w}x{h}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _get_or_generate(ov: "AiHtmlOverlay", width: int, height: int) -> str:
    key = _cache_key(ov.prompt, ov.style, width, height)
    cache_path = _CACHE_DIR / f"{key}.html"

    if ov.cache and cache_path.exists():
        logger.debug("ai_html cache hit: %s", key)
        return cache_path.read_text(encoding="utf-8")

    html = _generate(ov, width, height)

    if ov.cache:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(html, encoding="utf-8")

    return html


def _generate(ov: "AiHtmlOverlay", width: int, height: int) -> str:
    from auth_api_key import get_key
    import anthropic

    prompt = ov.prompt
    if ov.style:
        prompt += f" Visual style: {ov.style}."
    prompt += f" The canvas is exactly {width}×{height}px."

    logger.info("Generating ai_html via %s…", ov.model)
    client = anthropic.Anthropic(api_key=get_key("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=ov.model,
        max_tokens=8192,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(b.text for b in response.content if hasattr(b, "text"))
    return _extract_html(raw)


def _extract_html(text: str) -> str:
    m = _HTML_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    start = text.lower().find("<!doctype")
    if start == -1:
        start = text.lower().find("<html")
    return text[start:].strip() if start != -1 else text.strip()
