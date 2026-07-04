from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import FaceBlurOverlay


def render_face_blur_overlay(
    ov: "FaceBlurOverlay",
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    work_dir: Path,
    index: int,
    clip_path: Path | None = None,
) -> dict:
    """Detect faces in the base clip and render a blurred-faces overlay WebM."""
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("opencv-python required for face_blur — pip install opencv-python") from exc

    start = ov.timing.start
    end = ov.timing.end if ov.timing.end is not None else segment_duration
    dur = max(end - start, 0.1)

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    # If we have the base clip, extract frames and detect faces per-frame
    if clip_path and clip_path.exists():
        return _face_blur_from_clip(ov, clip_path, work_dir, index, width, height, fps, dur, start, end, cascade)

    # Fallback: return empty (pass-through)
    out = work_dir / f"face_blur_{index}.webm"
    # Create empty transparent WebM as placeholder
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=black:size={width}x{height}:rate={fps}",
        "-t", str(dur), "-vf", "format=yuva420p", "-c:v", "libvpx-vp9",
        "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "40", "-an", str(out),
    ], capture_output=True)
    return {"path": out, "x": "0", "y": "0", "start": start, "end": end,
            "keyframes": None, "z_order": ov.z_order, "_is_media_overlay": True}


def _face_blur_from_clip(ov, clip_path, work_dir, index, width, height, fps, dur, start, end, cascade):
    from PIL import Image, ImageFilter
    import numpy as np

    frames_dir = work_dir / f"face_blur_{index}_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    cap = __import__("cv2").VideoCapture(str(clip_path))
    frame_idx = 0
    kernel = ov.strength * 10 + 1  # ensure odd
    if kernel % 2 == 0:
        kernel += 1

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        gray = __import__("cv2").cvtColor(frame, __import__("cv2").COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4)

        pil = Image.fromarray(__import__("cv2").cvtColor(frame, __import__("cv2").COLOR_BGR2RGBA))
        overlay = Image.new("RGBA", pil.size, (0, 0, 0, 0))

        for (x, y, w, h) in faces:
            region = pil.crop((x, y, x + w, y + h))
            if ov.pixelate:
                small = region.resize((max(1, w // kernel), max(1, h // kernel)), Image.NEAREST)
                region = small.resize((w, h), Image.NEAREST)
            else:
                region = region.filter(ImageFilter.GaussianBlur(radius=kernel))
            overlay.paste(region, (x, y))

        overlay.save(frames_dir / f"frame_{frame_idx:05d}.png")
        frame_idx += 1

    cap.release()

    out = work_dir / f"face_blur_{index}.webm"
    r = subprocess.run([
        "ffmpeg", "-y", "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-t", str(dur), "-vf", "format=yuva420p",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20", "-an",
        str(out),
    ], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"face_blur encode failed: {r.stderr[-300:]}")

    return {"path": out, "x": "0", "y": "0", "start": start, "end": end,
            "keyframes": None, "z_order": ov.z_order, "_is_media_overlay": True}
