from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import ImageOverlay, VideoOverlay


_POSITION_TO_XY = {
    "center":       ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
    "top":          ("(main_w-overlay_w)/2", "0"),
    "bottom":       ("(main_w-overlay_w)/2", "main_h-overlay_h"),
    "top-left":     ("0", "0"),
    "top-right":    ("main_w-overlay_w", "0"),
    "bottom-left":  ("0", "main_h-overlay_h"),
    "bottom-right": ("main_w-overlay_w", "main_h-overlay_h"),
    "left":         ("0", "(main_h-overlay_h)/2"),
    "right":        ("main_w-overlay_w", "(main_h-overlay_h)/2"),
    "lower_third":  ("(main_w-overlay_w)/2", "main_h*0.78"),
    "lower_third_left": ("main_w*0.05", "main_h*0.78"),
    "lower_third_right": ("main_w*0.95-overlay_w", "main_h*0.78"),
    "lower_third_2": ("(main_w-overlay_w)/2", "main_h*0.86"),
}


def _build_scale_filter(ov, width: int, height: int) -> str:
    """Build ffmpeg scale filter string for image/video overlay sizing."""
    if ov.width_pct and ov.height_pct:
        w = int(width * ov.width_pct / 100)
        h = int(height * ov.height_pct / 100)
        return f"scale={w}:{h}"
    elif ov.width_pct:
        w = int(width * ov.width_pct / 100)
        return f"scale={w}:-1"
    elif ov.height_pct:
        h = int(height * ov.height_pct / 100)
        return f"scale=-1:{h}"
    return "scale=iw:ih"  # natural size


def _build_correction_filter(correction) -> str | None:
    """Build ffmpeg eq filter string from ColorCorrection."""
    if correction is None:
        return None
    return (
        f"eq=brightness={correction.brightness}"
        f":contrast={correction.contrast}"
        f":saturation={correction.saturation}"
        f":gamma={correction.gamma}"
    )


def _build_chromakey_filter(ck) -> str | None:
    """Build ffmpeg chromakey filter string from ChromaKey."""
    if ck is None:
        return None
    color = ck.color.lstrip("#")
    return f"chromakey=0x{color}:{ck.similarity}:{ck.blend}"


def _xy_for_overlay(ov, width: int, height: int) -> tuple[str, str]:
    """Return (x_expr, y_expr) for the overlay filter."""
    if ov.x_pct is not None and ov.y_pct is not None:
        return (str(int(width * ov.x_pct / 100)), str(int(height * ov.y_pct / 100)))
    pos = getattr(ov, "position", "center")
    return _POSITION_TO_XY.get(pos, _POSITION_TO_XY["center"])


def render_image_overlay(
    ov: "ImageOverlay",
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    work_dir: Path,
    index: int,
) -> dict:
    """Render an ImageOverlay to a fixed-duration WebM and return layer dict."""
    src = Path(ov.src)
    if not src.exists():
        raise FileNotFoundError(f"ImageOverlay src not found: {src}")

    out = work_dir / f"img_overlay_{index}.webm"
    start = ov.timing.start
    end = ov.timing.end if ov.timing.end is not None else segment_duration
    dur = end - start

    # Build filter chain for this image
    filters: list[str] = []
    filters.append(_build_scale_filter(ov, width, height))

    corr = _build_correction_filter(ov.correction)
    if corr:
        filters.append(corr)

    ck = _build_chromakey_filter(ov.chroma_key)
    if ck:
        filters.append(ck)

    if ov.opacity < 1.0:
        # Apply opacity via colorchannelmixer alpha scaling
        a = ov.opacity
        filters.append(f"colorchannelmixer=aa={a}")

    filters.append("format=yuva420p")
    vf = ",".join(filters)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(int(fps)),
        "-i", str(src),
        "-t", str(dur),
        "-vf", vf,
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20",
        "-an",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ImageOverlay ffmpeg failed: {result.stderr[-400:]}")

    x, y = _xy_for_overlay(ov, width, height)
    return {"path": out, "x": x, "y": y, "start": start, "end": end,
            "keyframes": ov.keyframes, "z_order": ov.z_order,
            "_is_media_overlay": True}


def render_video_overlay(
    ov: "VideoOverlay",
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    work_dir: Path,
    index: int,
) -> dict:
    """Render a VideoOverlay to a trimmed/processed WebM and return layer dict."""
    src = Path(ov.src)
    if not src.exists():
        raise FileNotFoundError(f"VideoOverlay src not found: {src}")

    out = work_dir / f"vid_overlay_{index}.webm"
    start = ov.timing.start
    end = ov.timing.end if ov.timing.end is not None else segment_duration
    dur = end - start

    filters: list[str] = []
    filters.append(_build_scale_filter(ov, width, height))

    corr = _build_correction_filter(ov.correction)
    if corr:
        filters.append(corr)

    ck = _build_chromakey_filter(ov.chroma_key)
    if ck:
        filters.append(ck)

    if ov.opacity < 1.0:
        filters.append(f"colorchannelmixer=aa={ov.opacity}")

    filters.append("format=yuva420p")
    vf = ",".join(filters)

    loop_args = ["-stream_loop", "-1"] if ov.loop else []
    mute_args = ["-an"] if ov.mute else []

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(ov.start_time),
        *loop_args,
        "-i", str(src),
        "-t", str(dur),
        "-r", str(fps),
        "-vf", vf,
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20",
        *mute_args,
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"VideoOverlay ffmpeg failed: {result.stderr[-400:]}")

    x, y = _xy_for_overlay(ov, width, height)
    return {"path": out, "x": x, "y": y, "start": start, "end": end,
            "keyframes": ov.keyframes, "z_order": ov.z_order,
            "_is_media_overlay": True}
