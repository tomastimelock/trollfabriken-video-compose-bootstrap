"""
GPU-accelerated codec selection with automatic h264_nvenc → libx264 fallback.

Usage:
    from video_compose._codec import codec_params

    cmd = ["ffmpeg", "-y", "-i", "input.mp4", *codec_params(crf=18), "output.mp4"]

Codec selection order:
    1. VIDEO_COMPOSE_CODEC env var  (e.g. "libx264", "h264_nvenc", "hevc_nvenc")
    2. h264_nvenc if detected via ffmpeg -encoders
    3. libx264 as fallback
"""
from __future__ import annotations

import functools
import os
import subprocess


def _probe_nvenc() -> bool:
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=5,
        )
        return "h264_nvenc" in r.stdout
    except Exception:
        return False


@functools.lru_cache(maxsize=1)
def get_codec() -> str:
    """Return the active codec name (detected once, then cached)."""
    forced = os.environ.get("VIDEO_COMPOSE_CODEC", "").strip()
    if forced:
        return forced
    if _probe_nvenc():
        return "h264_nvenc"
    return "libx264"


def codec_params(crf: int = 20, *, profile: str | None = None) -> list[str]:
    """Return ffmpeg -c:v … quality arguments for the active codec.

    Args:
        crf:     Quality level (0–51, lower = better). Maps to -crf for libx264
                 and -cq for h264_nvenc — same perceptual scale.
        profile: H.264 profile ("high", "main", "baseline"). Applied for both
                 libx264 and h264_nvenc when specified.
    """
    codec = get_codec()
    is_nvenc = codec == "h264_nvenc"

    params: list[str] = ["-c:v", codec, "-pix_fmt", "yuv420p"]

    if is_nvenc:
        params += ["-cq", str(crf), "-preset", "p4"]
    else:
        params += ["-crf", str(crf)]

    if profile:
        params += ["-profile:v", profile]

    return params
