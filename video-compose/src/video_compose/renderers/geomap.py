from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from video_compose.renderers.base import BaseRenderer


def _cosine_ease(t: float) -> float:
    return (1.0 - math.cos(t * math.pi)) / 2.0


class GeomapRenderer(BaseRenderer):
    """Renders a GeomapSegment using geo-map-fx render_static + PIL Ken Burns zoom."""

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
            from geo_map_fx.base import MapParams
        except ImportError as exc:
            raise RuntimeError(
                "geo-map-fx is required for geomap segments — pip install video-compose[geomap]"
            ) from exc

        if hasattr(data, "to_dict"):
            df = data
            cols = list(df.columns)
            values = dict(zip(df[cols[0]].astype(str), df[cols[1]].astype(float)))
        elif isinstance(data, dict):
            values = {str(k): float(v) for k, v in data.items()}
        else:
            values = {}

        animation = getattr(segment, "animation", "ken_burns_zoom")
        zoom_factor = float(getattr(segment, "zoom_factor", 0.4))
        max_zoom = 1.0 + zoom_factor

        # Render map at 2× resolution for crisp zoom
        render_w = int(width * max_zoom * 1.15)
        render_h = int(height * max_zoom * 1.15)

        params = MapParams(
            view=segment.view,
            scope=segment.scope,
            values=values,
            palette=segment.palette,
            reverse_palette=segment.reverse_palette,
            title=segment.title or "",
            width=render_w,
            height=render_h,
        )

        from geo_map_fx.renderers.static import render_static
        with tempfile.TemporaryDirectory() as td:
            png_path = Path(td) / "map.png"
            render_static(params, output_path=png_path)

            output_path = Path(output_path)

            if animation == "static":
                _static_loop(png_path, output_path, width, height, fps, segment.duration)
            else:
                _ken_burns_pil(
                    png_path, output_path, width, height, fps,
                    segment.duration, zoom_factor,
                )

        return output_path


def _static_loop(
    source: Path, output: Path, width: int, height: int, fps: float, duration: float
) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(fps),
        "-i", str(source),
        "-t", str(duration),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg geomap static encode failed: {result.stderr[:500]}")


def _ken_burns_pil(
    png_path: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: float,
    duration: float,
    zoom_factor: float,
) -> None:
    """Smooth Ken Burns zoom via PIL per-frame crop with cosine easing."""
    src = Image.open(str(png_path)).convert("RGB")
    src_w, src_h = src.size
    src_arr = np.array(src)

    total_frames = max(2, int(round(duration * fps)))
    max_zoom = 1.0 + zoom_factor

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{width}x{height}",
        "-pix_fmt", "rgb24",
        "-r", str(fps),
        "-i", "pipe:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        str(output_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        for frame_idx in range(total_frames):
            t_linear = frame_idx / max(total_frames - 1, 1)
            t = _cosine_ease(t_linear)
            zoom = 1.0 + zoom_factor * t

            # Crop size in source pixels — larger crop = zoomed out, smaller = zoomed in
            crop_w = int(src_w / zoom)
            crop_h = int(src_h / zoom)
            crop_w = min(crop_w, src_w)
            crop_h = min(crop_h, src_h)

            cx, cy = src_w // 2, src_h // 2
            x1 = max(0, cx - crop_w // 2)
            y1 = max(0, cy - crop_h // 2)
            x2 = min(src_w, x1 + crop_w)
            y2 = min(src_h, y1 + crop_h)

            crop = src_arr[y1:y2, x1:x2]
            frame_img = Image.fromarray(crop).resize((width, height), Image.BICUBIC)
            frame_arr = np.array(frame_img, dtype=np.float32)

            # Subtle per-frame film grain (seeded for reproducibility)
            rng = np.random.default_rng(seed=frame_idx)
            grain = rng.normal(0, 4.5, frame_arr.shape).astype(np.float32)
            frame_arr = np.clip(frame_arr + grain * 0.06, 0, 255).astype(np.uint8)

            proc.stdin.write(frame_arr.tobytes())
    finally:
        proc.stdin.close()

    _, stderr = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg geomap ken burns failed: {stderr.decode()[:500]}")
