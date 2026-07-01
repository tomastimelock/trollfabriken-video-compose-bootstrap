from __future__ import annotations

from pathlib import Path


def render_web_overlay(
    overlay,
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    output_dir: Path,
    index: int,
) -> dict:
    """Render a WebOverlay to a transparent WebM clip.

    Returns:
        dict with keys: path (Path), start (float), end (float), x (str), y (str)
    """
    try:
        from web_overlay import render_to_webm, RenderConfig
    except ImportError as exc:
        raise RuntimeError(
            "web-overlay is required for web overlays — pip install web-overlay"
        ) from exc

    start = overlay.timing.start
    end = overlay.timing.end if overlay.timing.end is not None else segment_duration
    duration = max(end - start, 0.1)

    out_path = output_dir / f"web_overlay_{index}.webm"

    template_path = Path(overlay.template)
    if template_path.exists():
        html_content = template_path.read_text(encoding="utf-8")
    else:
        html_content = overlay.template  # treat as raw HTML / inline HTML string

    # Inject css_vars as CSS custom properties via <style> block
    if overlay.css_vars:
        vars_css = ":root{" + ";".join(f"--{k}:{v}" for k, v in overlay.css_vars.items()) + "}"
        html_content = f"<style>{vars_css}</style>" + html_content

    config = RenderConfig(width=width, height=height, fps=int(fps))
    render_to_webm(html_content, duration=duration, output=out_path, config=config)

    return {"path": out_path, "start": start, "end": end, "x": "0", "y": "0"}
