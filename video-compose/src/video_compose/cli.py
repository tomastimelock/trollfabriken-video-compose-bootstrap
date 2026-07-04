from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click


@click.group()
@click.version_option(package_name="video-compose")
def main() -> None:
    """Trollfabriken Video Compose — JSON-driven video renderer."""


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

@main.command()
@click.argument("spec_file", type=click.Path(exists=True, path_type=Path))
@click.option("--output-dir", "-o", type=click.Path(path_type=Path), default=None,
              help="Override output directory from spec.")
@click.option("--resolution", "-r", default=None,
              help="Resolution preset: hd, full-hd, 4k, squared, instagram-story, tiktok, ...")
@click.option("--async", "async_mode", is_flag=True, default=False,
              help="Submit job for background render; returns job ID immediately.")
@click.option("--quiet", "-q", is_flag=True, help="Suppress progress output.")
def render(
    spec_file: Path,
    output_dir: Path | None,
    resolution: str | None,
    async_mode: bool,
    quiet: bool,
) -> None:
    """Render SPEC_FILE to video.

    With --async the render runs in the background and a job ID is printed.
    Use  vc jobs status <id>  to check progress.
    """
    from video_compose.api import compose, load_spec

    spec = load_spec(spec_file)

    # Apply CLI resolution override
    if resolution:
        from video_compose.schema.spec import RESOLUTION_PRESETS
        if resolution not in RESOLUTION_PRESETS:
            click.echo(f"Unknown resolution {resolution!r}. Valid: {sorted(RESOLUTION_PRESETS)}", err=True)
            sys.exit(1)
        w, h = RESOLUTION_PRESETS[resolution]
        spec.output.width, spec.output.height = w, h

    if async_mode or getattr(spec.output, "async_mode", False):
        from video_compose.jobs.runner import submit_async
        job_id = submit_async(spec, output_dir=output_dir, spec_path=str(spec_file))
        click.echo(f"Job submitted: {job_id}")
        click.echo(f"  Track with: video-compose jobs status {job_id}")
        return

    def _progress(stage: str, fraction: float) -> None:
        if not quiet:
            bar = "#" * int(fraction * 30)
            click.echo(f"\r  [{bar:<30}] {stage}", nl=False)

    click.echo(f"Rendering {spec_file.name}...")
    try:
        result = compose(spec, output_dir=output_dir, progress_cb=_progress)
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


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------

@main.command()
@click.argument("spec_file", type=click.Path(exists=True, path_type=Path))
@click.argument("segment_id")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
def preview(spec_file: Path, segment_id: str, output: Path | None) -> None:
    """Render a single SEGMENT_ID from SPEC_FILE to a preview MP4."""
    from video_compose.api import preview as _preview

    path = _preview(spec_file, segment_id, output)
    click.echo(f"Preview: {path}")


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

@main.command("schema")
def print_schema() -> None:
    """Print the TVCS JSON Schema to stdout."""
    from video_compose.schema.spec import TVCSSpec

    click.echo(json.dumps(TVCSSpec.model_json_schema(), indent=2))


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

@main.command()
@click.argument("description")
@click.option("--no-templates", is_flag=True, default=False,
              help="Always use scratch LLM generation (skip template matching).")
@click.option("--min-confidence", type=float, default=None,
              help="Template match confidence threshold (0.0–1.0). Default: config value (0.6).")
@click.option("--var", "-v", "variables", multiple=True, metavar="KEY=VALUE",
              help="Variable overrides passed to the template filler.")
@click.option("--category", "-c", default=None,
              help="Restrict template search to a category.")
@click.option("--output-dir", "-o", type=click.Path(path_type=Path), default=None)
@click.option("--render", "do_render", is_flag=True, default=False,
              help="Render the generated spec immediately after generation.")
@click.option("--save", type=click.Path(path_type=Path), default=None,
              help="Save the generated spec JSON to this path.")
@click.option("--width", type=int, default=1920)
@click.option("--height", type=int, default=1080)
@click.option("--fps", type=int, default=30)
@click.option("--duration", type=float, default=None, help="Desired total duration in seconds.")
def generate(
    description: str,
    no_templates: bool,
    min_confidence: float | None,
    variables: tuple[str, ...],
    category: str | None,
    output_dir: Path | None,
    do_render: bool,
    save: Path | None,
    width: int,
    height: int,
    fps: int,
    duration: float | None,
) -> None:
    """Generate a TVCS spec from a text DESCRIPTION using AI.

    Examples:

      video-compose generate "30s product launch, dark neon style"

      video-compose generate "quote card for LinkedIn" --category social --render

      video-compose generate "bar chart of sales data" --var accent_color=#ff4400 --save spec.json
    """
    from video_compose.llm.spec_generator import SpecGenerator

    user_overrides = _parse_vars(variables)

    click.echo(f"Generating spec for: {description!r}")
    if not no_templates:
        click.echo("  Mode: template-first (use --no-templates for scratch)")
    else:
        click.echo("  Mode: scratch (LLM generates full spec)")

    try:
        gen = SpecGenerator(min_confidence=min_confidence)
        result = gen.generate(
            description,
            use_templates=not no_templates,
            min_confidence=min_confidence,
            user_overrides=user_overrides,
            output_width=width,
            output_height=height,
            fps=fps,
            total_duration=duration,
            category_filter=category,
        )
    except ImportError as exc:
        click.echo(f"\nError: {exc}", err=True)
        click.echo("  Install LLM support: pip install 'video-compose[llm]'", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"\nError: {exc}", err=True)
        sys.exit(1)

    if result.missing_required:
        click.echo("\nMissing required variables — please provide with --var:")
        for mv in result.missing_required:
            click.echo(f"  --var {mv.name}=<{mv.type}>  ({mv.label})")
            if mv.description:
                click.echo(f"         {mv.description}")
        sys.exit(1)

    spec = result.spec
    assert spec is not None

    # Feedback
    if result.path == "template":
        click.echo(f"  Used template: {result.template_id}")
    else:
        click.echo(f"  Used scratch generation (repair rounds: {result.repair_rounds})")

    for w in result.warnings:
        click.echo(f"  warn: {w}", err=True)

    # Save
    if save:
        save.parent.mkdir(parents=True, exist_ok=True)
        save.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        click.echo(f"  Saved spec: {save}")

    # Render
    if do_render:
        from video_compose.api import compose
        click.echo("  Rendering...")
        render_result = compose(spec, output_dir=output_dir)
        if render_result.video_path:
            mb = render_result.video_path.stat().st_size / 1_048_576
            click.echo(f"  Done: {render_result.video_path}  ({mb:.1f} MB)")
    elif not save:
        click.echo("\nGenerated spec:")
        click.echo(json.dumps(spec, indent=2))


# ---------------------------------------------------------------------------
# template group
# ---------------------------------------------------------------------------

@main.group()
def template() -> None:
    """List, inspect, and use pre-built video templates."""


@template.command("list")
@click.option("--category", "-c", default=None, help="Filter by category.")
@click.option("--tag", "-t", default=None, help="Filter by tag.")
@click.option("--search", "-s", default=None, help="Keyword search.")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def template_list(category: str | None, tag: str | None, search: str | None, as_json: bool) -> None:
    """List available templates."""
    from video_compose.templates.registry import TemplateRegistry

    registry = TemplateRegistry()
    tags = [tag] if tag else None
    results = registry.list(category=category, tags=tags, search_query=search)

    if not results:
        click.echo("No templates found.")
        return

    if as_json:
        click.echo(json.dumps([t.to_compact_dict() for t in results], indent=2))
        return

    # Group by category
    from itertools import groupby
    results.sort(key=lambda t: t.category)
    for cat, group in groupby(results, key=lambda t: t.category):
        click.echo(f"\n{cat.upper().replace('_', ' ')}")
        for t in group:
            req = len(t.required_variables())
            click.echo(f"  {t.id:<35}  {t.name}")
            click.echo(f"    {t.description[:80]}" + ("..." if len(t.description) > 80 else ""))
            click.echo(f"    vars: {len(t.variables)} total, {req} required  |  tags: {', '.join(t.tags)}")


@template.command("info")
@click.argument("template_id")
def template_info(template_id: str) -> None:
    """Show detailed info for TEMPLATE_ID."""
    from video_compose.templates.registry import TemplateRegistry

    registry = TemplateRegistry()
    try:
        info = registry.get_info(template_id)
    except KeyError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    click.echo(f"\n{info.name}  [{info.id}]")
    click.echo(f"  Category : {info.category}")
    click.echo(f"  Tags     : {', '.join(info.tags)}")
    click.echo(f"  Author   : {info.author}  v{info.version}")
    click.echo(f"\n  {info.description}")
    click.echo(f"\n  Variables ({len(info.variables)}):")
    for v in info.variables:
        req_marker = "*" if v.get("required", True) and v.get("default") is None else " "
        default = f"  [default: {v['default']}]" if v.get("default") is not None else ""
        click.echo(f"    {req_marker} {v['name']:<25} {v.get('type','string'):<20} {v.get('label','')}{default}")
    click.echo("\n  (* = required, no default)")


@template.command("use")
@click.argument("template_id")
@click.option("--var", "-v", "variables", multiple=True, metavar="KEY=VALUE",
              help="Variable values. Repeat for multiple. JSON values are auto-parsed.")
@click.option("--ai-fill", default=None, metavar="DESCRIPTION",
              help="Use AI to fill remaining variables from DESCRIPTION.")
@click.option("--output-dir", "-o", type=click.Path(path_type=Path), default=None)
@click.option("--save", type=click.Path(path_type=Path), default=None,
              help="Save filled spec to file.")
@click.option("--render", "do_render", is_flag=True, default=False,
              help="Render immediately after filling.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show filled spec without rendering or saving.")
def template_use(
    template_id: str,
    variables: tuple[str, ...],
    ai_fill: str | None,
    output_dir: Path | None,
    save: Path | None,
    do_render: bool,
    dry_run: bool,
) -> None:
    """Fill TEMPLATE_ID with variables and optionally render.

    Examples:

      video-compose template use social_quote_card \\
          --var quote_text="Work hard, dream big." \\
          --var author_name="Trollfabriken"

      video-compose template use data_story_bar_chart \\
          --ai-fill "Q4 revenue by region, dark neon style" --render
    """
    from video_compose.templates.registry import TemplateRegistry
    from video_compose.templates.engine import TemplateEngine, TemplateFillError

    registry = TemplateRegistry()
    try:
        tmpl = registry.get(template_id)
    except KeyError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    user_vars = _parse_vars(variables)

    # AI fill remaining variables
    if ai_fill:
        try:
            from video_compose.llm.template_instantiator import TemplateInstantiator
            inst = TemplateInstantiator()
            fill_result = inst.fill_from_description(tmpl, ai_fill, user_vars)
            user_vars = fill_result.variables
            if fill_result.ai_filled:
                click.echo(f"  AI filled: {', '.join(fill_result.ai_filled)}")
        except ImportError as exc:
            click.echo(f"  warn: AI fill unavailable ({exc}); using provided vars only", err=True)

    # Fill template
    engine = TemplateEngine()
    try:
        spec = engine.fill(tmpl, user_vars)
    except TemplateFillError as exc:
        click.echo(f"Missing required variables:", err=True)
        for mv in exc.missing:
            click.echo(f"  --var {mv.name}=<{mv.type}>  ({mv.label})", err=True)
        sys.exit(1)

    if dry_run:
        click.echo(json.dumps(spec, indent=2))
        return

    if save:
        save.parent.mkdir(parents=True, exist_ok=True)
        save.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        click.echo(f"  Saved: {save}")

    if do_render:
        from video_compose.api import compose
        click.echo(f"  Rendering {template_id}...")
        result = compose(spec, output_dir=output_dir)
        if result.video_path:
            mb = result.video_path.stat().st_size / 1_048_576
            click.echo(f"  Done: {result.video_path}  ({mb:.1f} MB)")
        for w in result.warnings:
            click.echo(f"  warn: {w}", err=True)
    elif not save:
        click.echo(json.dumps(spec, indent=2))


@template.command("preview")
@click.argument("template_id")
@click.option("--size", type=click.Choice(["thumbnail", "full"]), default="thumbnail")
@click.option("--open", "open_file", is_flag=True, default=False,
              help="Open the preview image after printing the path.")
def template_preview(template_id: str, size: str, open_file: bool) -> None:
    """Show the path to the preview image for TEMPLATE_ID."""
    from video_compose.templates.registry import TemplateRegistry

    registry = TemplateRegistry()
    path = registry.get_preview_path(template_id, size=size)
    if not path:
        click.echo(f"No preview available for {template_id!r}.", err=True)
        sys.exit(1)

    click.echo(str(path))
    if open_file:
        import subprocess
        import platform
        if platform.system() == "Windows":
            subprocess.Popen(["start", str(path)], shell=True)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])


@template.command("validate")
@click.argument("template_id")
def template_validate(template_id: str) -> None:
    """Validate the template structure for TEMPLATE_ID."""
    from video_compose.templates.registry import TemplateRegistry
    from video_compose.templates.engine import TemplateEngine

    registry = TemplateRegistry()
    try:
        tmpl = registry.get(template_id)
    except KeyError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)

    engine = TemplateEngine()
    unfilled = engine.list_unfilled(tmpl)
    all_vars = engine.list_variables(tmpl)
    info = registry.get_info(template_id)

    click.echo(f"OK  {template_id}")
    click.echo(f"  {len(all_vars)} variables, {len(unfilled)} required with no default")
    if unfilled:
        click.echo("  Required (no default):")
        for mv in unfilled:
            click.echo(f"    {mv.name}  ({mv.type})  {mv.label}")


# ---------------------------------------------------------------------------
# jobs group — async render job management
# ---------------------------------------------------------------------------

@main.group()
def jobs() -> None:
    """Manage background render jobs."""


@jobs.command("list")
@click.option("--limit", default=20, help="Max number of jobs to show.")
def jobs_list(limit: int) -> None:
    """List recent render jobs."""
    from video_compose.jobs.manager import JobManager

    mgr = JobManager()
    rows = mgr.list_jobs(limit=limit)
    if not rows:
        click.echo("No jobs found.")
        return

    click.echo(f"{'ID':<10} {'STATUS':<10} {'CREATED':<26} {'OUTPUT'}")
    click.echo("-" * 80)
    for r in rows:
        out = (r.get("output_path") or "")[:40]
        click.echo(f"{r['id']:<10} {r['status']:<10} {r['created_at']:<26} {out}")


@jobs.command("status")
@click.argument("job_id")
def jobs_status(job_id: str) -> None:
    """Show full detail for JOB_ID."""
    from video_compose.jobs.manager import JobManager

    mgr = JobManager()
    job = mgr.get_job(job_id)
    if not job:
        click.echo(f"Job {job_id!r} not found.", err=True)
        sys.exit(1)

    click.echo(f"Job:      {job['id']}")
    click.echo(f"Status:   {job['status']}")
    click.echo(f"Created:  {job['created_at']}")
    if job.get("started_at"):
        click.echo(f"Started:  {job['started_at']}")
    if job.get("finished_at"):
        click.echo(f"Finished: {job['finished_at']}")
    if job.get("output_path"):
        click.echo(f"Output:   {job['output_path']}")
    if job.get("spec_path"):
        click.echo(f"Spec:     {job['spec_path']}")
    if job.get("webhook_url"):
        click.echo(f"Webhook:  {job['webhook_url']}")
    if job.get("error"):
        click.echo(f"Error:    {job['error']}", err=True)


@jobs.command("cancel")
@click.argument("job_id")
def jobs_cancel(job_id: str) -> None:
    """Cancel a pending or running job JOB_ID."""
    from video_compose.jobs.manager import JobManager

    mgr = JobManager()
    ok = mgr.cancel_job(job_id)
    if ok:
        click.echo(f"Job {job_id} cancelled.")
    else:
        click.echo(f"Job {job_id!r} not found or already finished.", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_vars(raw: tuple[str, ...]) -> dict[str, Any]:
    """Parse KEY=VALUE pairs, auto-parsing JSON values."""
    result: dict[str, Any] = {}
    for item in raw:
        if "=" not in item:
            click.echo(f"  warn: ignoring malformed --var {item!r} (expected KEY=VALUE)", err=True)
            continue
        key, _, val = item.partition("=")
        result[key.strip()] = _parse_val(val)
    return result


def _parse_val(s: str) -> Any:
    """Try JSON parse; fall back to string."""
    stripped = s.strip()
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return stripped
