from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ComposeResult:
    video_path: Path | None = None
    png_dir: Path | None = None
    warnings: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"ComposeResult(video={self.video_path}, warnings={len(self.warnings)})"


def load_spec(spec: "dict | str | Path") -> "TVCSSpec":
    """Parse and validate a TVCS spec, returning the TVCSSpec model object."""
    from video_compose.schema.spec import TVCSSpec
    from video_compose.schema.validator import validate as _validate

    raw = _load_raw(spec)
    vr = _validate(raw)
    if vr.has_errors:
        raise ValueError("Invalid TVCS spec:\n" + "\n".join(vr.errors))
    return TVCSSpec.model_validate(raw)


def compose(
    spec,
    output_dir: str | Path | None = None,
    progress_cb: Callable[[str, float], None] | None = None,
    export_png: bool = False,
) -> ComposeResult:
    """Render a TVCS spec to MP4 and optionally PNG frames.

    Args:
        spec:        TVCS spec as dict, JSON string, or path to a .json file.
        output_dir:  Output directory. Defaults to ./video_compose_output/.
        progress_cb: Optional callback(stage: str, fraction: float).
        export_png:  If True, also extract PNG frames alongside the MP4.

    Returns:
        ComposeResult with paths to rendered outputs and any non-fatal warnings.

    Raises:
        ValueError: If the spec fails structural or semantic validation.
    """
    from video_compose.schema.spec import TVCSSpec
    from video_compose.assembler.assembler import Assembler

    if isinstance(spec, TVCSSpec):
        parsed_spec = spec
        vr_warnings: list[str] = []
    else:
        from video_compose.schema.validator import validate as _validate
        raw = _load_raw(spec)
        vr = _validate(raw)
        if vr.has_errors:
            raise ValueError("Invalid TVCS spec:\n" + "\n".join(vr.errors))
        parsed_spec = TVCSSpec.model_validate(raw)
        vr_warnings = vr.warnings

    out_dir = Path(output_dir) if output_dir else Path("video_compose_output")
    out_dir.mkdir(parents=True, exist_ok=True)

    assembler = Assembler(parsed_spec, output_dir=out_dir, progress_cb=progress_cb)
    video_path = assembler.run()

    png_dir: Path | None = None
    if export_png:
        from video_compose.assembler.png_export import export_frames
        png_dir = out_dir / "frames"
        export_frames(video_path, png_dir)

    output_cfg = getattr(parsed_spec, "output", None)

    # Two-pass target-size encode
    target_mb = getattr(output_cfg, "target_size_mb", None)
    if target_mb:
        video_path = _two_pass_encode(video_path, float(target_mb), out_dir)

    # Multi-format export: WebM
    if getattr(output_cfg, "export_webm", False):
        _export_webm(video_path, out_dir)

    # Multi-format export: GIF
    if getattr(output_cfg, "export_gif", False):
        gif_fps = int(getattr(output_cfg, "gif_fps", 15) or 15)
        gif_width = int(getattr(output_cfg, "gif_width", 640) or 640)
        _export_gif(video_path, out_dir, gif_fps, gif_width)

    # Chapter export
    if getattr(output_cfg, "export_chapters", False):
        try:
            from video_compose.tools.chapters import generate_chapters, export_chapters
            chapters = generate_chapters(video_path)
            export_chapters(chapters, out_dir / "chapters.txt", out_dir / "chapters.ffmeta")
        except Exception as exc:
            vr_warnings.append(f"Chapter export failed: {exc}")

    return ComposeResult(
        video_path=video_path,
        png_dir=png_dir,
        warnings=vr_warnings,
    )


def validate(spec: dict | str | Path):
    """Validate a TVCS spec without rendering.

    Returns:
        ValidationResult with .is_valid, .errors, .warnings.
    """
    from video_compose.schema.validator import validate as _validate
    return _validate(_load_raw(spec))


def preview(
    spec: dict | str | Path,
    segment_id: str,
    output_path: str | Path | None = None,
) -> Path:
    """Render a single segment to a preview MP4.

    Args:
        spec:         TVCS spec.
        segment_id:   ID of the segment to render.
        output_path:  Destination path. Defaults to ./preview_{segment_id}.mp4.

    Returns:
        Path to the rendered preview MP4.
    """
    from video_compose.schema.spec import TVCSSpec
    from video_compose.assembler.assembler import Assembler

    raw = _load_raw(spec)
    parsed_spec = TVCSSpec.model_validate(raw)
    assembler = Assembler(parsed_spec)
    if output_path is None:
        output_path = Path(f"preview_{segment_id}.mp4")
    return assembler.render_segment_preview(segment_id, Path(output_path))


def _load_raw(spec: dict | str | Path) -> dict:
    if isinstance(spec, dict):
        return spec
    text = Path(spec).read_text(encoding="utf-8") if isinstance(spec, Path) else str(spec)
    if text.strip().startswith("{") or text.strip().startswith("["):
        return json.loads(text)
    return json.loads(Path(text).read_text(encoding="utf-8"))


def _two_pass_encode(video_path: Path, target_mb: float, out_dir: Path) -> Path:
    import subprocess
    out = out_dir / (video_path.stem + "_sized.mp4")
    # Probe duration
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True,
    )
    try:
        duration = float(probe.stdout.strip())
    except ValueError:
        return video_path

    # audio ~128kbps, reserve the rest for video
    audio_kbps = 128
    total_kbps = int((target_mb * 8 * 1024) / duration)
    video_kbps = max(100, total_kbps - audio_kbps)

    import tempfile as _tf
    passlog = _tf.mktemp()
    r1 = subprocess.run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-b:v", f"{video_kbps}k", "-pass", "1", "-passlogfile", passlog,
        "-an", "-f", "null", "-",
    ], capture_output=True, text=True)
    if r1.returncode != 0:
        return video_path

    r2 = subprocess.run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-b:v", f"{video_kbps}k", "-pass", "2", "-passlogfile", passlog,
        "-c:a", "aac", "-b:a", f"{audio_kbps}k",
        str(out),
    ], capture_output=True, text=True)
    for f in [passlog + "-0.log", passlog + ".log"]:
        Path(f).unlink(missing_ok=True)

    if r2.returncode != 0:
        raise RuntimeError(f"Two-pass encode failed: {r2.stderr[-400:]}")
    return out


def _export_webm(video_path: Path, out_dir: Path) -> Path:
    import subprocess
    out = out_dir / (video_path.stem + ".webm")
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "30",
        "-c:a", "libopus", "-b:a", "128k",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"WebM export failed: {r.stderr[-400:]}")
    return out


def _export_gif(video_path: Path, out_dir: Path, fps: int, width: int) -> Path:
    import subprocess
    out = out_dir / (video_path.stem + ".gif")
    palette = out_dir / "_palette.png"
    scale = f"scale={width}:-1:flags=lanczos"
    r1 = subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path),
         "-vf", f"{scale},palettegen",
         str(palette)],
        capture_output=True, text=True,
    )
    if r1.returncode != 0:
        raise RuntimeError(f"GIF palettegen failed: {r1.stderr[-300:]}")

    r2 = subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path), "-i", str(palette),
         "-filter_complex", f"{scale}[x];[x][1:v]paletteuse",
         "-r", str(fps),
         str(out)],
        capture_output=True, text=True,
    )
    palette.unlink(missing_ok=True)
    if r2.returncode != 0:
        raise RuntimeError(f"GIF paletteuse failed: {r2.stderr[-300:]}")
    return out
