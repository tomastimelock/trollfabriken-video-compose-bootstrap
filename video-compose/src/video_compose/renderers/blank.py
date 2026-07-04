from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from video_compose._codec import codec_params
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
        *codec_params(crf=16, profile="high"),
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg blank encode failed: {result.stderr[:500]}")


def _animated_gradient_video(
    color: str,
    output_path: Path,
    duration: float,
    fps: float,
    width: int,
    height: int,
) -> None:
    """Encode a slow-breathing animated gradient by piping raw RGB frames to ffmpeg.

    The gradient breathes with a sine-wave luminance oscillation over the duration,
    cycling once per ~3 seconds so it reads as alive rather than looping.
    """
    import math

    rgb = _hex_to_rgb(color) if color.startswith("#") else (13, 13, 26)
    total_frames = max(1, int(duration * fps))

    col = np.linspace(0, 1, height)[:, None, None]
    top_base = np.array(_lighter(rgb, 0.42), dtype=np.float32)
    bot_base = np.array(_darker(rgb, 0.25), dtype=np.float32)

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{width}x{height}",
        "-pix_fmt", "rgb24",
        "-r", str(fps),
        "-i", "pipe:0",
        "-t", str(duration),
        *codec_params(crf=18, profile="high"),
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        str(output_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rng = np.random.default_rng(seed=17)

    for i in range(total_frames):
        t_norm = i / max(total_frames - 1, 1)
        pulse = 0.08 * math.sin(2 * math.pi * t_norm * (duration / 3.0))
        top_c = np.clip(top_base * (1.0 + pulse), 0, 255)
        bot_c = np.clip(bot_base * (1.0 - pulse * 0.5), 0, 255)
        frame = (top_c * (1 - col) + bot_c * col).astype(np.float32)
        grain = rng.normal(0, 6.0, frame.shape).astype(np.float32)
        frame = np.clip(frame + grain * 0.09, 0, 255).astype(np.uint8)
        proc.stdin.write(np.broadcast_to(frame, (height, width, 3)).tobytes())

    proc.stdin.close()
    proc.wait()
    if proc.returncode not in (0, None):
        raise RuntimeError(f"Animated gradient encode failed (code {proc.returncode})")


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

        if bg_style == "gradient_anim":
            _animated_gradient_video(color, output_path, segment.duration, fps, width, height)
        else:
            with tempfile.TemporaryDirectory() as td:
                png_path = Path(td) / "bg.png"
                arr = _make_background(width, height, color, bg_style)
                Image.fromarray(arr, "RGB").save(str(png_path))
                _png_to_video(png_path, output_path, segment.duration, fps, width, height)

        return output_path
