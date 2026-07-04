from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from video_compose._codec import codec_params
from video_compose.renderers.base import BaseRenderer


def _ease_in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4.0 * t * t * t
    p = -2.0 * t + 2.0
    return 1.0 - (p * p * p) / 2.0


class ImageRenderer(BaseRenderer):
    """Renders an ImageSegment via ffmpeg (static or Ken Burns motion)."""

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
        motion = getattr(segment, "motion", "static")
        fit = getattr(segment, "fit", "cover")
        output_path = Path(output_path)

        if motion == "static":
            scale_filter = _scale_filter(width, height, fit)
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-framerate", str(fps),
                "-i", str(source),
                "-t", str(segment.duration),
                "-vf", scale_filter,
                *codec_params(crf=20),
                str(output_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg image encode failed: {result.stderr[:500]}")
        else:
            _ken_burns_pil(source, output_path, width, height, fps, segment.duration, motion)

        return output_path


def _ken_burns_pil(
    source: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: float,
    duration: float,
    motion: str,
) -> None:
    """Ease-in-out Ken Burns via PIL per-frame crop — eliminates linear stutter."""
    zoom_start, zoom_end = _motion_zoom(motion)

    src = Image.open(str(source)).convert("RGB")
    # Over-scale the source so cropping at zoom>1 always has pixels to work with
    scale_factor = max(zoom_end, zoom_start) * 1.1
    render_w = int(width * scale_factor)
    render_h = int(height * scale_factor)
    src = src.resize((render_w, render_h), Image.LANCZOS)
    src_arr = np.array(src)
    src_h, src_w = src_arr.shape[:2]

    total_frames = max(2, int(round(duration * fps)))

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{width}x{height}",
        "-pix_fmt", "rgb24",
        "-r", str(fps),
        "-i", "pipe:0",
        *codec_params(crf=20),
        str(output_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        for frame_idx in range(total_frames):
            t_linear = frame_idx / max(total_frames - 1, 1)
            t = _ease_in_out_cubic(t_linear)

            zoom = zoom_start + (zoom_end - zoom_start) * t
            crop_w = int(src_w / zoom)
            crop_h = int(src_h / zoom)

            # Pan direction — for pan_left/pan_right shift the center x
            if motion == "pan_left":
                max_offset = src_w - crop_w
                cx = int(max_offset * t)
                cy = (src_h - crop_h) // 2
            elif motion == "pan_right":
                max_offset = src_w - crop_w
                cx = int(max_offset * (1.0 - t))
                cy = (src_h - crop_h) // 2
            else:
                cx = (src_w - crop_w) // 2
                cy = (src_h - crop_h) // 2

            crop = src_arr[cy:cy + crop_h, cx:cx + crop_w]
            frame_img = Image.fromarray(crop).resize((width, height), Image.LANCZOS)
            proc.stdin.write(np.array(frame_img).tobytes())

    finally:
        proc.stdin.close()
        proc.wait()

    if proc.returncode != 0:
        stderr = proc.stderr.read().decode(errors="replace")
        raise RuntimeError(f"ffmpeg image ken burns encode failed: {stderr[-500:]}")


def _scale_filter(width: int, height: int, fit: str) -> str:
    if fit == "contain":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
    elif fit == "stretch":
        return f"scale={width}:{height}"
    else:  # cover
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )


def _motion_zoom(motion: str) -> tuple[float, float]:
    mapping = {
        "ken_burns": (1.0, 1.25),
        "zoom_in":   (1.0, 1.40),
        "zoom_out":  (1.4, 1.00),
        "pan_left":  (1.1, 1.10),
        "pan_right": (1.1, 1.10),
    }
    return mapping.get(motion, (1.0, 1.0))
