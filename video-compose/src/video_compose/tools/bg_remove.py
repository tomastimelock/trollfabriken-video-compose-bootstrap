from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def remove_bg_image(input_path: str | Path, output_path: str | Path) -> Path:
    """Remove background from a still image using rembg (ONNX U2Net)."""
    try:
        from rembg import remove as rembg_remove
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("rembg and Pillow required — pip install rembg") from exc

    input_path = Path(input_path)
    output_path = Path(output_path)
    img = Image.open(input_path)
    result = rembg_remove(img)
    result.save(output_path)
    return output_path


def remove_bg_video(
    input_path: str | Path,
    output_path: str | Path,
    fps: float | None = None,
    sample_every: int = 1,
) -> Path:
    """Remove background from every N-th frame of a video, rebuild as yuva420p WebM."""
    try:
        from rembg import remove as rembg_remove
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("rembg required — pip install rembg") from exc

    input_path = Path(input_path)
    output_path = Path(output_path)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        frames_dir = tmp / "frames"
        out_frames_dir = tmp / "out_frames"
        frames_dir.mkdir()
        out_frames_dir.mkdir()

        # Extract frames
        fps_arg = ["-r", str(fps)] if fps else []
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(input_path), *fps_arg,
             str(frames_dir / "frame_%05d.png")],
            capture_output=True, check=True,
        )

        frame_files = sorted(frames_dir.glob("frame_*.png"))
        for i, frame_file in enumerate(frame_files):
            out_frame = out_frames_dir / frame_file.name
            if i % sample_every == 0:
                img = Image.open(frame_file).convert("RGBA")
                result = rembg_remove(img)
                result.save(out_frame)
            else:
                # Reuse previous result for skipped frames
                prev = out_frames_dir / frame_files[max(0, i - 1)].name
                if prev.exists():
                    import shutil
                    shutil.copy2(prev, out_frame)

        # Reassemble
        input_fps = fps or 30.0
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(input_fps),
            "-i", str(out_frames_dir / "frame_%05d.png"),
            "-vf", "format=yuva420p",
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
            "-b:v", "0", "-crf", "20", "-an",
            str(output_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"bg_remove video encode failed: {r.stderr[-300:]}")

    return output_path
