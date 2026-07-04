from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from video_compose._codec import codec_params
from video_compose.renderers.base import BaseRenderer, validate_source_asset

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".avif"}


def _source_to_clip(
    source: Path,
    output: Path,
    width: int,
    height: int,
    fps: float,
    duration: float,
) -> None:
    """Scale image or video to exactly *width*×*height* and write a fixed-duration MP4."""
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"
    if source.suffix.lower() in _IMAGE_SUFFIXES:
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-framerate", str(int(fps)),
            "-i", str(source),
            "-t", str(duration),
            "-vf", vf,
            *codec_params(crf=18, profile="high"),
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            str(output),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(source),
            "-t", str(duration),
            "-vf", vf,
            "-r", str(fps),
            *codec_params(crf=18, profile="high"),
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            str(output),
        ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg source prep failed: {result.stderr[-300:]}")


class SplitScreenRenderer(BaseRenderer):
    """Renders a SplitScreenSegment: two sources composited side-by-side or top/bottom."""

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
        output_path = Path(output_path)
        source_a = validate_source_asset(segment.source_a)
        source_b = validate_source_asset(segment.source_b)

        direction = getattr(segment, "split_direction", "horizontal")
        divider_color = getattr(segment, "divider_color", "#ffffff").lstrip("#")
        divider_width = getattr(segment, "divider_width", 4)
        label_a = getattr(segment, "label_a", None)
        label_b = getattr(segment, "label_b", None)
        label_color = getattr(segment, "label_color", "#ffffff").lstrip("#")
        label_font_size = getattr(segment, "label_font_size", 48)
        duration = segment.duration

        if direction == "vertical":
            half_w, half_h = width, height // 2
            stack_filter = "vstack"
        else:
            half_w, half_h = width // 2, height
            stack_filter = "hstack"

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            side_a = td_path / "side_a.mp4"
            side_b = td_path / "side_b.mp4"
            _source_to_clip(source_a, side_a, half_w, half_h, fps, duration)
            _source_to_clip(source_b, side_b, half_w, half_h, fps, duration)

            filter_parts: list[str] = []
            step = 0

            def next_label() -> str:
                nonlocal step
                lbl = f"s{step}"
                step += 1
                return lbl

            # Stack the two clips
            out0 = next_label()
            filter_parts.append(f"[0:v][1:v]{stack_filter}[{out0}]")
            prev = out0

            # Optional centre divider
            if divider_width > 0:
                out1 = next_label()
                if direction == "vertical":
                    box = f"x=0:y={half_h - divider_width // 2}:w={width}:h={divider_width}"
                else:
                    box = f"x={half_w - divider_width // 2}:y=0:w={divider_width}:h={height}"
                filter_parts.append(
                    f"[{prev}]drawbox={box}:color=0x{divider_color}@1.0:t=fill[{out1}]"
                )
                prev = out1

            # Optional label A
            if label_a:
                out_la = next_label()
                lx, ly = _label_position("a", direction, width, height, half_w, half_h, label_font_size)
                filter_parts.append(
                    f"[{prev}]drawtext=text='{_escape(label_a)}':fontsize={label_font_size}"
                    f":fontcolor=0x{label_color}:x={lx}:y={ly}"
                    f":shadowcolor=black@0.6:shadowx=2:shadowy=2[{out_la}]"
                )
                prev = out_la

            # Optional label B
            if label_b:
                out_lb = next_label()
                lx, ly = _label_position("b", direction, width, height, half_w, half_h, label_font_size)
                filter_parts.append(
                    f"[{prev}]drawtext=text='{_escape(label_b)}':fontsize={label_font_size}"
                    f":fontcolor=0x{label_color}:x={lx}:y={ly}"
                    f":shadowcolor=black@0.6:shadowx=2:shadowy=2[{out_lb}]"
                )
                prev = out_lb

            filter_graph = ";".join(filter_parts)

            cmd = [
                "ffmpeg", "-y",
                "-i", str(side_a), "-i", str(side_b),
                "-filter_complex", filter_graph,
                "-map", f"[{prev}]",
                "-t", str(duration),
                *codec_params(crf=18, profile="high"),
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                str(output_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg split-screen failed: {result.stderr[-600:]}")

        return output_path


def _label_position(
    side: str,
    direction: str,
    width: int,
    height: int,
    half_w: int,
    half_h: int,
    font_size: int,
) -> tuple[str, str]:
    margin = 20
    if direction == "vertical":
        x = str(margin)
        y = str(margin) if side == "a" else str(half_h + margin)
    else:
        x = str(margin) if side == "a" else str(half_w + margin)
        y = str(height - font_size - margin)
    return x, y


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
