from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from video_compose._codec import codec_params
from video_compose.renderers.base import BaseRenderer

_MOTION_TO_ZOOM = {
    "ken_burns": (1.0, 1.25),
    "zoom_in": (1.0, 1.4),
    "zoom_out": (1.4, 1.0),
    "pan_left": (1.0, 1.0),
    "pan_right": (1.0, 1.0),
    "static": (1.0, 1.0),
}


class StillRenderer(BaseRenderer):
    """Renders a StillSegment using still-motion KenBurns or static ffmpeg loop."""

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
        source = Path(segment.source)
        motion = getattr(segment, "motion", "ken_burns")
        motion_config = dict(getattr(segment, "motion_config", {}) or {})
        mask = getattr(segment, "mask", "none")
        output_path = Path(output_path)

        if motion == "static":
            raw = output_path.with_stem(output_path.stem + "_raw") if mask != "none" else output_path
            _static_loop(source, raw, width, height, fps, segment.duration)
        else:
            try:
                from still_motion import KenBurns, RenderConfig
            except ImportError as exc:
                raise RuntimeError(
                    "still-motion is required for animated still segments — pip install still-motion"
                ) from exc

            zoom_start, zoom_end = _MOTION_TO_ZOOM.get(motion, (1.0, 1.25))
            zoom_start = float(motion_config.pop("zoom_start", zoom_start))
            zoom_end = float(motion_config.pop("zoom_end", zoom_end))
            focus = tuple(motion_config.pop("focus", (0.5, 0.5)))
            motion_easing = getattr(segment, "motion_easing", "ease-in-out")

            raw = output_path.with_stem(output_path.stem + "_raw") if mask != "none" else output_path
            kb = KenBurns(
                image=source,
                duration=segment.duration,
                width=width,
                height=height,
                fps=int(fps),
                zoom_start=zoom_start,
                zoom_end=zoom_end,
                focus=focus,
                easing=motion_easing,
                **motion_config,
            )
            config = RenderConfig(width=width, height=height, fps=int(fps))
            kb.render(raw, config)

        if mask != "none":
            _apply_mask(
                raw_path=raw,
                output_path=output_path,
                width=width,
                height=height,
                fps=fps,
                duration=segment.duration,
                shape=mask,
                outline_color=getattr(segment, "mask_outline_color", "#ffffff"),
                outline_width=getattr(segment, "mask_outline_width", 4),
                feather=getattr(segment, "mask_feather", 8),
                shadow=getattr(segment, "mask_shadow", True),
            )
            try:
                raw.unlink()
            except OSError:
                pass

        return output_path


def _apply_mask(
    raw_path: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: float,
    duration: float,
    shape: str,
    outline_color: str,
    outline_width: int,
    feather: int,
    shadow: bool,
) -> None:
    """Composite a circle/ellipse mask + ring + drop shadow onto the video.

    Strategy:
      1. Build a PIL mask image (circle or ellipse) with feathered edges.
      2. Optionally build a drop-shadow layer (dark translucent circle, offset).
      3. Build an outline ring PNG.
      4. Composite via ffmpeg filter_complex:
         raw → multiply alpha by mask → overlay ring → overlay shadow (behind).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # --- build mask PNG (grayscale: white = opaque, black = transparent) ---
        mask_img = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(mask_img)
        cx, cy = width // 2, height // 2
        if shape == "circle":
            r = min(cx, cy) - outline_width - 2
            bbox = [cx - r, cy - r, cx + r, cy + r]
        else:  # ellipse
            rx = cx - outline_width - 2
            ry = int(cx * 1.2) - outline_width - 2
            ry = min(ry, cy - outline_width - 2)
            bbox = [cx - rx, cy - ry, cx + rx, cy + ry]
        draw.ellipse(bbox, fill=255)
        if feather > 0:
            mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=feather))
        mask_path = tmp / "mask.png"
        mask_img.save(mask_path)

        # --- build outline ring PNG (RGBA) ---
        ring = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ring_draw = ImageDraw.Draw(ring)
        oc = _hex_to_rgba(outline_color, 255)
        if outline_width > 0:
            ring_draw.ellipse(
                [bbox[0] - outline_width, bbox[1] - outline_width,
                 bbox[2] + outline_width, bbox[3] + outline_width],
                outline=oc, width=outline_width,
            )
        ring_path = tmp / "ring.png"
        ring.save(ring_path)

        # --- build drop-shadow PNG (RGBA) ---
        shadow_path = None
        if shadow:
            sh_offset_x = max(4, int(width * 0.005))
            sh_offset_y = max(6, int(height * 0.007))
            sh_blur = max(8, int(min(width, height) * 0.012))
            sh_img = Image.new("L", (width, height), 0)
            sh_draw = ImageDraw.Draw(sh_img)
            sh_draw.ellipse(
                [bbox[0] + sh_offset_x, bbox[1] + sh_offset_y,
                 bbox[2] + sh_offset_x, bbox[3] + sh_offset_y],
                fill=180,
            )
            sh_img = sh_img.filter(ImageFilter.GaussianBlur(radius=sh_blur))
            sh_rgba = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            sh_rgba.putalpha(sh_img)
            shadow_path = tmp / "shadow.png"
            sh_rgba.save(shadow_path)

        # --- ffmpeg composite ---
        # [0:v] = raw video  [1:v] = mask  [2:v] = shadow  [3:v] = ring
        inputs = ["-i", str(raw_path), "-i", str(mask_path)]
        fc_parts = []

        # Apply alpha mask to raw video: multiply alpha channel by mask
        fc_parts.append(
            "[0:v]format=yuva420p[vid];"
            "[vid][1:v]alphamerge[masked]"
        )
        last = "masked"
        next_input = 2

        # Add drop shadow underneath (blend shadow below masked clip)
        if shadow_path:
            inputs += ["-i", str(shadow_path)]
            fc_parts.append(
                f"[{next_input}:v]format=yuva420p[sh];"
                f"[sh][{last}]overlay=0:0[with_shadow]"
            )
            last = "with_shadow"
            next_input += 1

        # Add ring on top
        inputs += ["-i", str(ring_path)]
        fc_parts.append(
            f"[{next_input}:v]format=yuva420p[ring];"
            f"[{last}][ring]overlay=0:0[final]"
        )

        filter_complex = ";".join(fc_parts)

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[final]",
            "-t", str(duration),
            *codec_params(crf=20),
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Mask composite failed: {result.stderr[-500:]}")


def _static_loop(source: Path, output: Path, width: int, height: int, fps: float, duration: float) -> Path:
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(fps),
        "-i", str(source),
        "-t", str(duration),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        *codec_params(crf=20),
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg static loop failed: {result.stderr[:500]}")
    return output


def _hex_to_rgba(color: str, alpha: int) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha
