from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any


def apply_overlays(
    clip_path: Path,
    overlays: list,
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
) -> Path:
    """Composite all overlays onto *clip_path*, return the composited clip Path.

    If there are no overlays, returns *clip_path* unchanged.
    Produces a new MP4 file next to *clip_path* with suffix ``_overlaid``.
    """
    if not overlays:
        return clip_path

    from video_compose.overlays.text import render_text_overlay
    from video_compose.overlays.web import render_web_overlay

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        overlay_layers: list[dict] = []

        for i, ov in enumerate(overlays):
            try:
                if ov.type == "text":
                    layer = render_text_overlay(ov, segment_duration, width, height, fps, td, i)
                elif ov.type == "web":
                    layer = render_web_overlay(ov, segment_duration, width, height, fps, td, i)
                else:
                    continue
                overlay_layers.append(layer)
            except Exception as exc:
                # Non-fatal: skip broken overlay but log it
                import logging
                logging.getLogger(__name__).warning("Overlay %d failed: %s", i, exc)

        if not overlay_layers:
            return clip_path

        output_path = clip_path.with_stem(clip_path.stem + "_overlaid")
        _composite_ffmpeg(clip_path, overlay_layers, output_path, fps)
        return output_path


def _composite_ffmpeg(
    base: Path,
    layers: list[dict],
    output: Path,
    fps: float,
) -> None:
    """Apply overlay clips onto base using ffmpeg overlay filter chain."""
    # Build filter graph:
    #   [0:v] — base video
    #   [1:v] — first overlay
    #   ...
    # overlay filter: enable='between(t,start,end)'
    inputs = ["-i", str(base)]
    for layer in layers:
        inputs += ["-i", str(layer["path"])]

    filter_parts = []
    prev = "0:v"
    for i, layer in enumerate(layers):
        ov_idx = i + 1
        x = layer.get("x", "(W-w)/2")
        y = layer.get("y", "(H-h)/2")
        start = layer.get("start", 0.0)
        end = layer.get("end", 999999.0)
        out_label = f"ov{i}"
        filter_parts.append(
            f"[{prev}][{ov_idx}:v]overlay={x}:{y}:enable='between(t,{start},{end})'[{out_label}]"
        )
        prev = out_label

    filter_graph = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_graph,
        "-map", f"[{prev}]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg overlay composite failed: {result.stderr[:500]}")
