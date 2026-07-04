"""
Batch thumbnail extraction for rendered template videos.

Usage:
    python -m video_compose.tools.thumbnail --video-dir E:/VideoCompose/output --out-dir E:/VideoCompose/thumbs
    python -m video_compose.tools.thumbnail --video path/to/clip.mp4 --out path/to/thumb.jpg
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
from pathlib import Path

_log = logging.getLogger(__name__)

_THUMB_W = 400
_THUMB_H = 225
_PORTRAIT_THRESH = 0.8  # aspect ratio < 0.8 → treat as portrait


def extract_thumbnail(
    video_path: Path,
    output_path: Path,
    *,
    timestamp: float = 2.0,
    width: int = _THUMB_W,
    height: int = _THUMB_H,
) -> bool:
    """Extract a JPEG thumbnail from *video_path* at *timestamp* seconds.

    Scales to fit within *width*×*height* preserving aspect ratio (letterbox/pillarbox).
    Returns True on success, False on failure.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Detect portrait orientation and swap dimensions
    try:
        info = _probe_video(video_path)
        ar = info.get("width", 16) / max(info.get("height", 9), 1)
        if ar < _PORTRAIT_THRESH:
            width, height = height, width
    except Exception:
        pass

    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    )
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp),
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", vf,
        "-q:v", "3",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=30)
    if result.returncode != 0:
        _log.warning("Thumbnail failed for %s: %s", video_path.name, result.stderr[-200:])
        return False
    return True


def extract_batch(
    video_dir: Path,
    out_dir: Path,
    *,
    timestamp: float = 2.0,
    pattern: str = "*.mp4",
) -> dict[str, bool]:
    """Extract thumbnails for all MP4s under *video_dir*.

    Returns {relative_stem: success} mapping.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, bool] = {}

    for mp4 in sorted(video_dir.rglob(pattern)):
        rel = mp4.relative_to(video_dir)
        thumb = out_dir / rel.with_suffix(".jpg")
        ok = extract_thumbnail(mp4, thumb, timestamp=timestamp)
        results[str(rel.with_suffix(""))] = ok
        status = "OK" if ok else "FAIL"
        _log.info("[%s] %s → %s", status, mp4.name, thumb)

    return results


def _probe_video(path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    data = json.loads(r.stdout)
    streams = data.get("streams", [{}])
    return streams[0] if streams else {}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Extract preview thumbnails from rendered template videos")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--video-dir", type=Path, help="Batch: directory containing rendered MP4s")
    group.add_argument("--video", type=Path, help="Single: path to an MP4")

    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory for thumbnails (batch mode)")
    parser.add_argument("--out", type=Path, default=None, help="Output JPEG path (single mode)")
    parser.add_argument("--timestamp", type=float, default=2.0, help="Seek position in seconds (default 2.0)")
    args = parser.parse_args()

    if args.video:
        out = args.out or args.video.with_suffix(".jpg")
        ok = extract_thumbnail(args.video, out, timestamp=args.timestamp)
        raise SystemExit(0 if ok else 1)
    else:
        out_dir = args.out_dir or args.video_dir / "thumbnails"
        results = extract_batch(args.video_dir, out_dir, timestamp=args.timestamp)
        n_ok = sum(results.values())
        print(f"Thumbnails: {n_ok}/{len(results)} succeeded → {out_dir}")


if __name__ == "__main__":
    main()
