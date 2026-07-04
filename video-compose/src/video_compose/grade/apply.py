from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from video_compose._codec import codec_params

logger = logging.getLogger(__name__)


def apply_grade(clip_path: Path, grade_slug: str | None) -> Path:
    """Apply a color-fx grade to *clip_path* using the PNG-frame pipeline.

    Returns the graded clip path (a new file next to the original).
    If *grade_slug* is None or empty, returns *clip_path* unchanged.
    """
    if not grade_slug:
        return clip_path

    try:
        from color_fx.engines.grade_recipe import GradeRecipeEngine
        from color_fx.config import GradeConfig
    except ImportError as exc:
        raise RuntimeError(
            "color-fx is required for grade application — pip install color-fx"
        ) from exc

    try:
        engine = GradeRecipeEngine()
        config = GradeConfig(grade=grade_slug)
        color_fn = engine.get_color_fn(grade_slug, config)
    except Exception as exc:
        logger.warning("Grade %r failed to load: %s — skipping", grade_slug, exc)
        return clip_path

    clip_path = Path(clip_path)
    output_path = clip_path.with_stem(clip_path.stem + "_graded")

    from PIL import Image

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # Extract frames
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(clip_path), str(td / "f%06d.png")],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            logger.warning("Frame extraction failed for grade: %s", result.stderr[:200])
            return clip_path

        # Apply grade to each frame
        for png in sorted(td.glob("f*.png")):
            img = Image.open(png).convert("RGB")
            arr = np.array(img, dtype=np.float32) / 255.0
            h, w = arr.shape[:2]
            graded = color_fn(arr.reshape(-1, 3)).reshape(h, w, 3)
            graded_img = Image.fromarray(np.clip(graded * 255, 0, 255).astype(np.uint8), "RGB")
            graded_img.save(png)

        # Re-encode — detect fps from original
        fps = _detect_fps(clip_path)
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-framerate", str(fps),
                "-i", str(td / "f%06d.png"),
                *codec_params(crf=20),
                str(output_path),
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            logger.warning("Grade re-encode failed: %s", result.stderr[:200])
            return clip_path

    logger.debug("Grade %r applied: %s → %s", grade_slug, clip_path, output_path)
    return output_path


def _detect_fps(clip_path: Path) -> str:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate",
         "-of", "default=noprint_wrappers=1:nokey=1", str(clip_path)],
        capture_output=True, text=True,
    )
    raw = result.stdout.strip()
    if "/" in raw:
        num, den = raw.split("/")
        try:
            return str(round(int(num) / int(den), 3))
        except (ValueError, ZeroDivisionError):
            pass
    return raw or "30"
