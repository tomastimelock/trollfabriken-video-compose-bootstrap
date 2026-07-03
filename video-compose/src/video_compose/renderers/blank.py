from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from video_compose.renderers.base import BaseRenderer


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lerp_color(c1: tuple, c2: tuple, t: float) -> tuple[int, int, int]:
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _lighter(rgb: tuple[int, int, int], factor: float = 0.45) -> tuple[int, int, int]:
    return _lerp_color(rgb, (255, 255, 255), factor)


def _darker(rgb: tuple[int, int, int], factor: float = 0.5) -> tuple[int, int, int]:
    return _lerp_color(rgb, (0, 0, 0), factor)


def _add_grain(arr: np.ndarray, sigma: float = 8.0, strength: float = 0.10) -> np.ndarray:
    rng = np.random.default_rng(seed=42)
    grain = rng.normal(0, sigma, arr.shape).astype(np.float32)
    return np.clip(arr.astype(np.float32) + grain * strength, 0, 255).astype(np.uint8)


def _make_background(
    width: int,
    height: int,
    color: str,
    bg_style: str,
) -> np.ndarray:
    rgb = _hex_to_rgb(color) if color.startswith("#") else (13, 13, 26)

    if bg_style == "gradient_v":
        top = _lighter(rgb, 0.40)
        bottom = _darker(rgb, 0.20)
        col = np.linspace(0, 1, height)[:, None, None]
        base = (
            np.array(top)[None, None, :] * (1 - col) + np.array(bottom)[None, None, :] * col
        )
        arr = np.broadcast_to(base, (height, width, 3)).copy().astype(np.uint8)

    elif bg_style == "gradient_v_dark":
        top = _darker(rgb, 0.55)
        bottom = _lighter(rgb, 0.15)
        col = np.linspace(0, 1, height)[:, None, None]
        base = (
            np.array(top)[None, None, :] * (1 - col) + np.array(bottom)[None, None, :] * col
        )
        arr = np.broadcast_to(base, (height, width, 3)).copy().astype(np.uint8)

    elif bg_style == "gradient_d":
        top_left = _lighter(rgb, 0.35)
        bot_right = _darker(rgb, 0.30)
        gy = np.linspace(0, 1, height)[:, None]
        gx = np.linspace(0, 1, width)[None, :]
        t = (gy + gx) / 2.0
        arr = np.zeros((height, width, 3), dtype=np.float32)
        for ch in range(3):
            arr[:, :, ch] = top_left[ch] * (1 - t) + bot_right[ch] * t
        arr = arr.astype(np.uint8)

    elif bg_style == "radial":
        cy, cx = height / 2, width / 2
        yy, xx = np.ogrid[:height, :width]
        dist = np.sqrt(((yy - cy) / (height * 0.6)) ** 2 + ((xx - cx) / (width * 0.6)) ** 2)
        t = np.clip(dist, 0, 1)[:, :, None]
        center_c = np.array(_lighter(rgb, 0.30), dtype=np.float32)
        edge_c = np.array(_darker(rgb, 0.45), dtype=np.float32)
        arr = (center_c * (1 - t) + edge_c * t).astype(np.uint8)

    else:  # solid or noise
        arr = np.full((height, width, 3), rgb, dtype=np.uint8)

    return _add_grain(arr, sigma=7.0, strength=0.09)


def _png_to_video(png_path: Path, output_path: Path, duration: float, fps: float, width: int, height: int) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(int(fps)),
        "-i", str(png_path),
        "-t", str(duration),
        "-vf", f"scale={width}:{height}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg blank encode failed: {result.stderr[:500]}")


class BlankRenderer(BaseRenderer):
    """Renders a BlankSegment with PIL gradient backgrounds and film grain."""

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
        color = segment.color or "#0d0d1a"
        bg_style = getattr(segment, "bg_style", "gradient_v")

        output_path = Path(output_path)

        with tempfile.TemporaryDirectory() as td:
            png_path = Path(td) / "bg.png"
            arr = _make_background(width, height, color, bg_style)
            Image.fromarray(arr, "RGB").save(str(png_path))
            _png_to_video(png_path, output_path, segment.duration, fps, width, height)

        return output_path
