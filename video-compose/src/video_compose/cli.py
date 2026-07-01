from __future__ import annotations

import json
import sys
from pathlib import Path

import click


@click.group()
@click.version_option(package_name="video-compose")
def main() -> None:
    """Trollfabriken Video Compose — JSON-driven video renderer."""


@main.command()
@click.argument("spec_file", type=click.Path(exists=True, path_type=Path))
@click.option("--output-dir", "-o", type=click.Path(path_type=Path), default=None,
              help="Override output directory from spec.")
@click.option("--quiet", "-q", is_flag=True, help="Suppress progress output.")
def render(spec_file: Path, output_dir: Path | None, quiet: bool) -> None:
    """Render SPEC_FILE to video."""
    from video_compose.api import compose

    def _progress(stage: str, fraction: float) -> None:
        if not quiet:
            bar = "#" * int(fraction * 30)
            click.echo(f"\r  [{bar:<30}] {stage}", nl=False)

    click.echo(f"Rendering {spec_file.name}...")
    try:
        result = compose(spec_file, output_dir=output_dir, progress_cb=_progress)
        click.echo("")
        if result.video_path:
            mb = result.video_path.stat().st_size / 1_048_576
            click.echo(f"  Done: {result.video_path}  ({mb:.1f} MB)")
        if result.png_dir:
            click.echo(f"  PNGs: {result.png_dir}")
        for w in result.warnings:
            click.echo(f"  warn: {w}", err=True)
    except ValueError as exc:
        click.echo(f"\nError: {exc}", err=True)
        sys.exit(1)


@main.command()
@click.argument("spec_file", type=click.Path(exists=True, path_type=Path))
def validate(spec_file: Path) -> None:
    """Validate SPEC_FILE without rendering."""
    from video_compose.api import validate as _validate

    result = _validate(spec_file)
    if result.is_valid:
        click.echo(f"OK  {spec_file.name}")
        for w in result.warnings:
            click.echo(f"  warn: {w}")
    else:
        click.echo(f"INVALID  {spec_file.name}", err=True)
        for e in result.errors:
            click.echo(f"  error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument("spec_file", type=click.Path(exists=True, path_type=Path))
@click.argument("segment_id")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
def preview(spec_file: Path, segment_id: str, output: Path | None) -> None:
    """Render a single SEGMENT_ID from SPEC_FILE to a preview MP4."""
    from video_compose.api import preview as _preview

    path = _preview(spec_file, segment_id, output)
    click.echo(f"Preview: {path}")


@main.command("schema")
def print_schema() -> None:
    """Print the TVCS JSON Schema to stdout."""
    from video_compose.schema.spec import TVCSSpec

    click.echo(json.dumps(TVCSSpec.model_json_schema(), indent=2))
