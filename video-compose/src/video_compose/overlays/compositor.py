from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from video_compose._codec import codec_params


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
    from video_compose.overlays.bar import render_bar_overlay
    from video_compose.overlays.web import render_web_overlay

    # Sort by z_order so higher z_order overlays are composited later (on top)
    sorted_overlays = sorted(overlays, key=lambda o: getattr(o, "z_order", 0))

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        overlay_layers: list[dict] = []

        for i, ov in enumerate(sorted_overlays):
            try:
                if ov.type == "text":
                    layer = render_text_overlay(ov, segment_duration, width, height, fps, td, i)
                elif ov.type == "bar":
                    layer = render_bar_overlay(ov, segment_duration, width, height, fps, td, i)
                elif ov.type == "web":
                    layer = render_web_overlay(ov, segment_duration, width, height, fps, td, i)
                else:
                    continue
                overlay_layers.append(layer)
            except Exception as exc:
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
    """Composite text overlays onto base using ffmpeg filter chain.

    Key design decisions:
    - text-fx renders WebM with yuv420p (no alpha) on this system — VP9 yuva420p
      encoding silently drops the alpha channel.
    - colorkey=black removes the solid-black background from each overlay, making
      text pixels compositable over the base video.
    - setpts delay ensures each animation starts at frame 0 when the overlay fires,
      not mid-animation (which happens without the PTS offset).
    - format=auto on the overlay filter passes alpha from the keyed stream.
    - CRF 16 keeps text edges sharp at 720p.
    """
    inputs = ["-i", str(base)]
    for layer in layers:
        inputs += ["-i", str(layer["path"])]

    filter_parts = []
    prev = "0:v"

    for i, layer in enumerate(layers):
        ov_idx = i + 1
        x = layer.get("x", "0")
        y = layer.get("y", "0")
        start = float(layer.get("start", 0.0))
        end = float(layer.get("end", 999999.0))
        keyed = f"keyed{i}"
        out_label = f"ov{i}"

        # Delay the overlay clip so its frame 0 aligns with `start` in the video timeline,
        # then key out black background to make text transparent.
        filter_parts.append(
            f"[{ov_idx}:v]"
            f"setpts=PTS-STARTPTS+{start}/TB,"
            f"colorkey=black:0.18:0.06,"
            f"format=yuva420p"
            f"[{keyed}]"
        )
        filter_parts.append(
            f"[{prev}][{keyed}]"
            f"overlay={x}:{y}:format=auto:eof_action=pass:"
            f"enable='between(t,{start},{end})'"
            f"[{out_label}]"
        )
        prev = out_label

    filter_graph = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_graph,
        "-map", f"[{prev}]",
        *codec_params(crf=16, profile="high"),
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg overlay composite failed: {result.stderr[-600:]}")
