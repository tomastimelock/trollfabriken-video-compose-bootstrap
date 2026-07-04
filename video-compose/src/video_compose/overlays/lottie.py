from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import LottieOverlay

_POSITION_TO_XY = {
    "center":            ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
    "top":               ("(main_w-overlay_w)/2", "0"),
    "bottom":            ("(main_w-overlay_w)/2", "main_h-overlay_h"),
    "top-left":          ("0", "0"),
    "top-right":         ("main_w-overlay_w", "0"),
    "bottom-left":       ("0", "main_h-overlay_h"),
    "bottom-right":      ("main_w-overlay_w", "main_h-overlay_h"),
    "left":              ("0", "(main_h-overlay_h)/2"),
    "right":             ("main_w-overlay_w", "(main_h-overlay_h)/2"),
    "lower_third":       ("(main_w-overlay_w)/2", "main_h*0.78"),
    "lower_third_left":  ("main_w*0.05", "main_h*0.78"),
    "lower_third_right": ("main_w*0.95-overlay_w", "main_h*0.78"),
    "lower_third_2":     ("(main_w-overlay_w)/2", "main_h*0.86"),
}


def render_lottie_overlay(
    ov: "LottieOverlay",
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    work_dir: Path,
    index: int,
) -> dict:
    """Render a Lottie JSON animation to a yuva420p WebM via lottie-python → PNG frames → ffmpeg."""
    src = Path(ov.src)
    if not src.exists():
        raise FileNotFoundError(f"Lottie JSON not found: {src}")

    start = ov.timing.start
    end = ov.timing.end if ov.timing.end is not None else segment_duration
    dur = max(end - start, 0.1)

    target_w = int(width * ov.width_pct / 100) if ov.width_pct else int(width * 0.25)
    target_h = int(height * ov.height_pct / 100) if ov.height_pct else target_w

    frames_dir = work_dir / f"lottie_{index}_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    _render_lottie_frames(src, frames_dir, dur, fps, target_w, target_h, ov.loop)

    out = work_dir / f"lottie_overlay_{index}.webm"
    opacity_f = f",colorchannelmixer=aa={ov.opacity}" if ov.opacity < 1.0 else ""
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-t", str(dur),
        "-vf", f"format=yuva420p{opacity_f}",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20", "-an",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Lottie ffmpeg encode failed: {r.stderr[-400:]}")

    x, y = (_POSITION_TO_XY.get(ov.position, _POSITION_TO_XY["center"])
            if ov.x_pct is None else (str(int(width * ov.x_pct / 100)), str(int(height * ov.y_pct / 100))))
    return {"path": out, "x": x, "y": y, "start": start, "end": end,
            "keyframes": None, "z_order": ov.z_order, "_is_media_overlay": True}


def _render_lottie_frames(
    src: Path,
    frames_dir: Path,
    dur: float,
    fps: float,
    width: int,
    height: int,
    loop: bool,
) -> None:
    """Render Lottie animation frames using lottie-python library."""
    try:
        import lottie
        from lottie.exporters.gif import export_gif
        from lottie.parsers.lottie import parse_lottie
    except ImportError:
        _render_lottie_frames_fallback(src, frames_dir, dur, fps, width, height, loop)
        return

    try:
        an = parse_lottie(str(src))
        lottie_fps = an.frame_rate or fps
        lottie_dur = (an.out_point - an.in_point) / lottie_fps

        total_frames = int(dur * fps)
        for frame_idx in range(total_frames):
            t = (frame_idx / fps) % lottie_dur if loop else min(frame_idx / fps, lottie_dur)
            lottie_frame = int(t * lottie_fps) + int(an.in_point)

            from lottie.exporters.cairo import export_png
            from io import BytesIO
            buf = BytesIO()
            export_png(an, buf, frame=lottie_frame, width=width, height=height)
            frame_path = frames_dir / f"frame_{frame_idx:05d}.png"
            frame_path.write_bytes(buf.getvalue())
    except Exception as exc:
        raise RuntimeError(f"lottie-python rendering failed: {exc}") from exc


def _render_lottie_frames_fallback(
    src: Path,
    frames_dir: Path,
    dur: float,
    fps: float,
    width: int,
    height: int,
    loop: bool,
) -> None:
    """Fallback: try lottie-convert CLI (lottie-python ships it)."""
    temp_gif = frames_dir / "lottie_temp.gif"
    r = subprocess.run(
        ["lottie_convert.py", str(src), str(temp_gif)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(
            "lottie-python is required for lottie overlays — pip install lottie\n"
            f"Details: {r.stderr[-200:]}"
        )

    # Extract GIF frames with ffmpeg
    total_frames = int(dur * fps)
    loop_arg = ["-stream_loop", "-1"] if loop else []
    r2 = subprocess.run(
        ["ffmpeg", "-y", *loop_arg, "-i", str(temp_gif),
         "-vf", f"scale={width}:{height}",
         "-frames:v", str(total_frames),
         str(frames_dir / "frame_%05d.png")],
        capture_output=True, text=True,
    )
    if r2.returncode != 0:
        raise RuntimeError(f"GIF frame extraction failed: {r2.stderr[-200:]}")
