from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import ComponentOverlay

_BUNDLED_DIR = Path(__file__).parent.parent / "components"
_USER_DIR = Path.home() / ".video_compose" / "components"

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

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)(?:\|default:([^}]*))?\}\}")


def render_component_overlay(
    ov: "ComponentOverlay",
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    work_dir: Path,
    index: int,
) -> dict:
    """Resolve a named component, substitute props, render via web-overlay.

    Components render at full canvas size with position handled by internal CSS.
    Compositor uses colorkey-black to composite — components must have black (#000) bg.
    """
    try:
        from web_overlay import render_to_webm, RenderConfig
    except ImportError as exc:
        raise RuntimeError(
            "web-overlay is required for component overlays — pip install web-overlay"
        ) from exc

    html_content = _load_and_substitute(ov.name, ov.props)

    # Inject props as CSS custom properties as well (for CSS-driven components)
    if ov.props:
        css_vars = ":root{" + ";".join(f"--{k}:{v}" for k, v in ov.props.items()) + "}"
        html_content = f"<style>{css_vars}</style>" + html_content

    start = ov.timing.start
    end = ov.timing.end if ov.timing.end is not None else segment_duration
    duration = max(end - start, 0.1)

    out_path = work_dir / f"component_overlay_{index}.webm"
    config = RenderConfig(width=width, height=height, fps=int(fps))
    render_to_webm(html_content, duration=duration, output=out_path, config=config)

    # Components lay themselves out via CSS; ffmpeg overlay at (0,0) covers full canvas
    return {"path": out_path, "start": start, "end": end, "x": "0", "y": "0"}


def _load_and_substitute(name: str, props: dict) -> str:
    html = _find_component(name)
    return _PLACEHOLDER_RE.sub(lambda m: str(props.get(m.group(1), m.group(2) or "")), html)


def _find_component(name: str) -> str:
    # user-saved components: stored under ~/.video_compose/components/<name>.html
    # bundled components: src/video_compose/components/<name>.html
    slug = name.removeprefix("user.") if name.startswith("user.") else name
    candidates = [_USER_DIR / f"{slug}.html", _BUNDLED_DIR / f"{slug}.html"]
    for p in candidates:
        if p.exists():
            return p.read_text(encoding="utf-8")
    available = sorted(p.stem for p in _BUNDLED_DIR.glob("*.html"))
    raise FileNotFoundError(
        f"Component {name!r} not found. "
        f"Bundled components: {available}. "
        f"User components: {_USER_DIR}"
    )


def list_components() -> list[dict]:
    """Return metadata for all available components (bundled + user)."""
    results = []
    seen: set[str] = set()
    for d, source in [(_USER_DIR, "user"), (_BUNDLED_DIR, "bundled")]:
        if not d.exists():
            continue
        for p in sorted(d.glob("*.html")):
            if p.stem not in seen:
                seen.add(p.stem)
                results.append({"name": p.stem, "source": source, "path": str(p)})
    return results
