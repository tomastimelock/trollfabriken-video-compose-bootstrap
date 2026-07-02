from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from video_compose.renderers.base import BaseRenderer


class SlideRenderer(BaseRenderer):
    """Renders a SlideSegment: slide-render → HTML → Playwright PNG → video."""

    def render(
        self,
        segment,
        data: Any,
        output_path: Path,
        *,
        width: int,
        height: int,
        fps: float,
    ) -> Path:
        try:
            from slide_render import render_html, RenderConfig
            from deck_spec.models import Deck
        except ImportError as exc:
            raise RuntimeError(
                "slide-render is required for slide segments — pip install slide-render"
            ) from exc

        slide_spec = segment.slide_spec
        if isinstance(slide_spec, str):
            p = Path(slide_spec)
            if p.exists():
                slide_spec = json.loads(p.read_text(encoding="utf-8"))
            else:
                # Try parsing as JSON or as a Python literal (e.g. from str(dict))
                try:
                    slide_spec = json.loads(slide_spec)
                except json.JSONDecodeError:
                    import ast
                    slide_spec = ast.literal_eval(slide_spec)

        motion = getattr(segment, "motion", "static")
        output_path = Path(output_path)

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            html_path = td / "slide.html"

            deck = Deck.model_validate(slide_spec)
            config = RenderConfig(html_standalone=True)
            render_html(deck, html_path, config)

            # Screenshot via Playwright
            png_path = td / "slide.png"
            _screenshot_html(html_path, png_path, width, height)

            if motion == "static":
                _static_loop(png_path, output_path, width, height, fps, segment.duration)
            else:
                try:
                    from still_motion import KenBurns, RenderConfig as SMConfig
                    zoom_start, zoom_end = _motion_zoom(motion)
                    kb = KenBurns(
                        image=png_path,
                        duration=segment.duration,
                        width=width, height=height, fps=int(fps),
                        zoom_start=zoom_start, zoom_end=zoom_end,
                    )
                    kb.render(output_path, SMConfig(width=width, height=height, fps=int(fps)))
                except ImportError:
                    _static_loop(png_path, output_path, width, height, fps, segment.duration)

        return output_path


def _screenshot_html(html_path: Path, png_path: Path, width: int, height: int) -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(f"file:///{html_path.as_posix()}")
        page.wait_for_timeout(500)
        page.screenshot(path=str(png_path), full_page=False)
        browser.close()


def _static_loop(source: Path, output: Path, width: int, height: int, fps: float, duration: float) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(fps),
        "-i", str(source),
        "-t", str(duration),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg slide encode failed: {result.stderr[:500]}")


def _motion_zoom(motion: str) -> tuple[float, float]:
    return {
        "ken_burns": (1.0, 1.2),
        "zoom_in": (1.0, 1.3),
        "zoom_out": (1.3, 1.0),
    }.get(motion, (1.0, 1.0))
