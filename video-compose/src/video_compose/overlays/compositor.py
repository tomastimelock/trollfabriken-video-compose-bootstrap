from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from video_compose._codec import codec_params

logger = logging.getLogger(__name__)


def apply_overlays(
    clip_path: Path,
    overlays: list,
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    condition_evaluator=None,
) -> Path:
    """Composite all overlays onto *clip_path*, return the composited clip Path.

    If there are no overlays (or all are filtered by condition), returns *clip_path* unchanged.
    Produces a new MP4 file next to *clip_path* with suffix ``_overlaid``.
    """
    if not overlays:
        return clip_path

    from video_compose.overlays.text import render_text_overlay
    from video_compose.overlays.bar import render_bar_overlay
    from video_compose.overlays.web import render_web_overlay
    from video_compose.overlays.image import render_image_overlay, render_video_overlay
    from video_compose.overlays.audiogram import render_audiogram_overlay

    # Filter by condition first
    if condition_evaluator is not None:
        overlays = [ov for ov in overlays if condition_evaluator.evaluate(getattr(ov, "condition", None))]

    if not overlays:
        return clip_path

    # Sort by z_order so higher z_order overlays are composited later (on top)
    sorted_overlays = sorted(overlays, key=lambda o: getattr(o, "z_order", 0))

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        overlay_layers: list[dict] = []

        for i, ov in enumerate(sorted_overlays):
            try:
                ov_type = ov.type
                if ov_type == "text":
                    layer = render_text_overlay(ov, segment_duration, width, height, fps, td, i)
                elif ov_type == "bar":
                    layer = render_bar_overlay(ov, segment_duration, width, height, fps, td, i)
                elif ov_type == "web":
                    layer = render_web_overlay(ov, segment_duration, width, height, fps, td, i)
                elif ov_type == "image_overlay":
                    layer = render_image_overlay(ov, segment_duration, width, height, fps, td, i)
                elif ov_type == "video_overlay":
                    layer = render_video_overlay(ov, segment_duration, width, height, fps, td, i)
                elif ov_type == "audiogram":
                    layer = render_audiogram_overlay(ov, clip_path, segment_duration, width, height, fps, td, i)
                else:
                    logger.warning("Unknown overlay type %r — skipping", ov_type)
                    continue
                overlay_layers.append(layer)
            except Exception as exc:
                logger.warning("Overlay %d (type=%r) failed: %s", i, getattr(ov, "type", "?"), exc)

        if not overlay_layers:
            return clip_path

        output_path = clip_path.with_stem(clip_path.stem + "_overlaid")
        _composite_ffmpeg(clip_path, overlay_layers, output_path, fps, width, height)
        return output_path


def _composite_ffmpeg(
    base: Path,
    layers: list[dict],
    output: Path,
    fps: float,
    width: int,
    height: int,
) -> None:
    """Composite overlay layers onto base using ffmpeg filter chain.

    Supports keyframe-animated x/y/opacity/scale via timeline expressions.

    Key design decisions:
    - text/bar/web overlays: rendered as WebM with colorkey=black to remove background.
    - image/video overlays: rendered with alpha channel (yuva420p), composited directly.
    - audiogram overlays: rendered with alpha channel.
    - Keyframe expressions substitute the static x/y in the overlay filter.
    - colorchannelmixer controls opacity for keyframe-animated overlays.
    """
    inputs = ["-i", str(base)]
    for layer in layers:
        inputs += ["-i", str(layer["path"])]

    filter_parts = []
    prev = "0:v"

    for i, layer in enumerate(layers):
        ov_idx = i + 1
        start = float(layer.get("start", 0.0))
        end = float(layer.get("end", 999999.0))
        keyframes = layer.get("keyframes")
        is_media = layer.get("_is_media_overlay", False)  # image/video/audiogram — has real alpha
        is_audiogram = layer.get("_is_audiogram", False)

        # Resolve x/y — prefer keyframe expressions, then static layer values
        if keyframes:
            from video_compose.overlays.keyframes import build_ffmpeg_exprs
            # Extract base values from layer
            base_x = layer.get("_base_x_pct")
            base_y = layer.get("_base_y_pct")
            base_op = float(layer.get("_base_opacity", 1.0))
            base_sc = float(layer.get("_base_scale", 1.0))
            exprs = build_ffmpeg_exprs(
                keyframes, end - start, width, height,
                base_x, base_y, base_op, base_sc
            )
            x_expr = exprs.get("x", layer.get("x", "0"))
            y_expr = exprs.get("y", layer.get("y", "0"))
        else:
            x_expr = layer.get("x", "0")
            y_expr = layer.get("y", "0")

        keyed = f"keyed{i}"
        out_label = f"ov{i}"

        if is_media or is_audiogram:
            # Media overlays already have proper alpha — shift PTS and composite directly
            filter_parts.append(
                f"[{ov_idx}:v]"
                f"setpts=PTS-STARTPTS+{start}/TB"
                f"[{keyed}]"
            )
        else:
            # Text/bar/web — colorkey black background
            filter_parts.append(
                f"[{ov_idx}:v]"
                f"setpts=PTS-STARTPTS+{start}/TB,"
                f"colorkey=black:0.18:0.06,"
                f"format=yuva420p"
                f"[{keyed}]"
            )

        filter_parts.append(
            f"[{prev}][{keyed}]"
            f"overlay={x_expr}:{y_expr}:format=auto:eof_action=pass:"
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
