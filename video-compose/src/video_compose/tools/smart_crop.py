from __future__ import annotations

import subprocess
from pathlib import Path


def get_face_crop(
    video_path: str | Path,
    target_w: int,
    target_h: int,
    sample_frames: int = 5,
) -> str:
    """Return ffmpeg crop filter string that keeps detected faces in frame.

    Falls back to center crop if no face is found.
    """
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("opencv-python required — pip install opencv-python") from exc

    video_path = Path(video_path)

    cap = cv2.VideoCapture(str(video_path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cx_sum, cy_sum, count = 0, 0, 0

    step = max(1, total // (sample_frames + 1))
    for i in range(sample_frames):
        cap.set(cv2.CAP_PROP_POS_FRAMES, step * (i + 1))
        ret, frame = cap.read()
        if not ret:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, 1.1, 4)
        for (x, y, w, h) in faces:
            cx_sum += x + w // 2
            cy_sum += y + h // 2
            count += 1

    cap.release()

    if count > 0:
        cx = cx_sum // count
        cy = cy_sum // count
    else:
        cx = src_w // 2
        cy = src_h // 2

    # Compute crop rectangle keeping subject centered, clamped to frame
    crop_w = min(src_w, int(src_h * target_w / target_h))
    crop_h = min(src_h, int(src_w * target_h / target_w))
    if src_w / src_h > target_w / target_h:
        crop_w = int(crop_h * target_w / target_h)
    else:
        crop_h = int(crop_w * target_h / target_w)

    x = max(0, min(cx - crop_w // 2, src_w - crop_w))
    y = max(0, min(cy - crop_h // 2, src_h - crop_h))
    return f"crop={crop_w}:{crop_h}:{x}:{y},scale={target_w}:{target_h}"
