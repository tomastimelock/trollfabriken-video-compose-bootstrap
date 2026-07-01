from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any


class ComposeResult:
    def __init__(self, video_path: Path | None, png_dir: Path | None, warnings: list[str]):
        self.video_path = video_path
        self.png_dir = png_dir
        self.warnings = warnings

    def __repr__(self) -> str:
        return f"ComposeResult(video={self.video_path}, warnings={len(self.warnings)})"


def compose(
    spec: dict | str | Path,
    output_dir: str | Path | None = None,
    progress_cb: Callable[[str, float], None] | None = None,
) -> ComposeResult:
    """Render a TVCS spec to MP4 and/or PNG frames.

    Args:
        spec: TVCS spec as dict, JSON string, or path to .json file.
        output_dir: Override the output directory from the spec.
        progress_cb: Optional callback(stage: str, fraction: float).

    Returns:
        ComposeResult with paths to rendered outputs.
    """
    from video_compose.assembler.assembler import Assembler
    from video_compose.schema.validator import validate as _validate

    parsed = _load_spec(spec)

    result = _validate(parsed)
    if result.has_errors:
        raise ValueError(f"Invalid TVCS spec:\n" + "\n".join(result.errors))

    assembler = Assembler(parsed, output_dir=output_dir, progress_cb=progress_cb)
    return assembler.run()


def validate(spec: dict | str | Path) -> Any:
    """Validate a TVCS spec without rendering.

    Returns:
        ValidationResult with .is_valid, .errors, .warnings.
    """
    from video_compose.schema.validator import validate as _validate

    return _validate(_load_spec(spec))


def preview(
    spec: dict | str | Path,
    segment_id: str,
    output_path: str | Path | None = None,
) -> Path:
    """Render a single segment to a preview MP4.

    Args:
        spec: TVCS spec.
        segment_id: ID of the segment to render.
        output_path: Destination path; defaults to ./preview_{segment_id}.mp4.

    Returns:
        Path to the rendered preview MP4.
    """
    from video_compose.assembler.assembler import Assembler

    parsed = _load_spec(spec)
    assembler = Assembler(parsed)
    return assembler.render_segment_preview(segment_id, output_path)


def _load_spec(spec: dict | str | Path) -> dict:
    if isinstance(spec, dict):
        return spec
    if isinstance(spec, Path) or (isinstance(spec, str) and not spec.strip().startswith("{")):
        return json.loads(Path(spec).read_text(encoding="utf-8"))
    return json.loads(spec)
