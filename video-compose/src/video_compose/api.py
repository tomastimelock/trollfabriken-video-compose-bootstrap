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


def compose(
    spec: dict | str | Path,
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
    from video_compose.schema.validator import validate as _validate
    from video_compose.assembler.assembler import Assembler

    raw = _load_raw(spec)
    vr = _validate(raw)
    if vr.has_errors:
        raise ValueError("Invalid TVCS spec:\n" + "\n".join(vr.errors))

    parsed_spec = TVCSSpec.model_validate(raw)

    out_dir = Path(output_dir) if output_dir else Path("video_compose_output")
    out_dir.mkdir(parents=True, exist_ok=True)

    assembler = Assembler(parsed_spec, output_dir=out_dir, progress_cb=progress_cb)
    video_path = assembler.run()

    png_dir: Path | None = None
    if export_png:
        from video_compose.assembler.png_export import export_frames
        png_dir = out_dir / "frames"
        export_frames(video_path, png_dir)

    return ComposeResult(
        video_path=video_path,
        png_dir=png_dir,
        warnings=vr.warnings,
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
