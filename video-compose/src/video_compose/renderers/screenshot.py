from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from video_compose.renderers.base import BaseRenderer
from video_compose._codec import codec_params


class ScreenshotRenderer(BaseRenderer):
    """Renders a ScreenshotSegment — Playwright screenshot of a URL → still or Ken Burns video."""

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
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright is required for screenshot segments — pip install playwright && playwright install"
            ) from exc

        url = segment.url
        wait_ms = int(getattr(segment, "wait_ms", 2000))
        full_page = bool(getattr(segment, "full_page", False))
        selector = getattr(segment, "selector", None)
        fit = getattr(segment, "fit", "cover")
        motion = getattr(segment, "motion", "none")
        duration = float(segment.duration)
        output_path = Path(output_path)

        png = output_path.with_suffix(".screenshot.png")

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(url, wait_until="networkidle")
            if wait_ms > 0:
                page.wait_for_timeout(wait_ms)

            if selector:
                element = page.query_selector(selector)
                if element is None:
                    raise RuntimeError(f"Selector {selector!r} not found on {url}")
                element.screenshot(path=str(png))
            else:
                page.screenshot(path=str(png), full_page=full_page)
            browser.close()

        # Build ffmpeg vf for fit
        if fit == "contain":
            scale_vf = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
            )
        else:  # cover (default)
            scale_vf = (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}"
            )

        # Ken Burns motion
        if motion == "zoom_in":
            motion_vf = f",zoompan=z='zoom+0.001':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(duration*fps)}:s={width}x{height}:fps={fps}"
        elif motion == "zoom_out":
            motion_vf = f",zoompan=z='if(eq(on\\,1)\\,1.3\\,max(1.0\\,zoom-0.001))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(duration*fps)}:s={width}x{height}:fps={fps}"
        elif motion == "pan_left":
            motion_vf = f",zoompan=z=1.0:x='iw*0.1*(on/{int(duration*fps)})':y=0:d={int(duration*fps)}:s={width}x{height}:fps={fps}"
        elif motion == "pan_right":
            motion_vf = f",zoompan=z=1.0:x='iw*0.1*(1-on/{int(duration*fps)})':y=0:d={int(duration*fps)}:s={width}x{height}:fps={fps}"
        else:
            motion_vf = ""

        vf = f"{scale_vf}{motion_vf}"

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-framerate", str(int(fps)), "-i", str(png),
            "-t", str(duration),
            "-vf", vf,
            *codec_params(crf=20),
            "-an",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"screenshot ffmpeg encode failed: {result.stderr[:500]}")

        png.unlink(missing_ok=True)
        return output_path
