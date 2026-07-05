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
@click.option("--social-preset", default=None,
              help="Social platform preset: reels, tiktok, shorts, instagram-post, twitter, linkedin, youtube.")
def render(
    spec_file: Path,
    output_dir: Path | None,
    resolution: str | None,
    async_mode: bool,
    quiet: bool,
    social_preset: str | None,
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

    # Apply social platform preset (overrides resolution + injects loudnorm target)
    if social_preset:
        try:
            from video_compose.social import apply_social_to_spec
            apply_social_to_spec(spec, social_preset)
        except ValueError as exc:
            click.echo(str(exc), err=True)
            sys.exit(1)

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
# component group — HTML component library management
# ---------------------------------------------------------------------------

@main.group()
def component() -> None:
    """Browse and generate reusable HTML overlay components."""


@component.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def component_list(as_json: bool) -> None:
    """List all available bundled and user-saved components."""
    from video_compose.overlays.component import list_components

    items = list_components()
    if not items:
        click.echo("No components found.")
        return

    if as_json:
        click.echo(json.dumps(items, indent=2))
        return

    for c in items:
        source_tag = f"[{c['source']}]"
        click.echo(f"  {c['name']:<30}  {source_tag}")


@component.command("generate")
@click.argument("description")
@click.option("--name", "-n", default=None, help="Component slug to save as (default: slugified description).")
@click.option("--style", "-s", default=None, help="Visual style hint, e.g. 'neon', 'glassmorphism', 'minimal'.")
@click.option("--model", default="claude-opus-4-7", show_default=True)
@click.option("--overwrite", is_flag=True, default=False)
def component_generate(
    description: str,
    name: str | None,
    style: str | None,
    model: str,
    overwrite: bool,
) -> None:
    """Generate a new HTML component via Claude and save to user library.

    Examples:

      video-compose component generate "sports lower third with team colours"

      video-compose component generate "glassmorphism price card" --style glassmorphism --name price_glass
    """
    import re as _re
    from auth_api_key import get_key
    import anthropic
    from video_compose.overlays.ai_html import _SYSTEM

    user_dir = Path.home() / ".video_compose" / "components"
    user_dir.mkdir(parents=True, exist_ok=True)

    slug = name or _re.sub(r"[^\w]+", "_", description.lower()).strip("_")[:40]
    out_path = user_dir / f"{slug}.html"

    if out_path.exists() and not overwrite:
        click.echo(f"Component {slug!r} already exists at {out_path}")
        click.echo("Use --overwrite to replace it.")
        sys.exit(1)

    prompt = description
    if style:
        prompt += f" Visual style: {style}."
    prompt += " Canvas is 1920×1080px. Make it versatile — use CSS variables for easy customisation."

    click.echo(f"Generating component {slug!r} via {model}…")

    client = anthropic.Anthropic(api_key=get_key("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(b.text for b in response.content if hasattr(b, "text"))

    # Strip code fences if present
    import re as _re2
    fence_m = _re2.search(r"```(?:html)?\s*([\s\S]*?)```", raw, _re2.IGNORECASE)
    html = fence_m.group(1).strip() if fence_m else raw.strip()

    out_path.write_text(html, encoding="utf-8")
    click.echo(f"  Saved: {out_path}")
    click.echo(f"\nUse in a spec:")
    click.echo(f'  {{ "type": "component", "name": "{slug}", "props": {{}} }}')


@component.command("show")
@click.argument("component_name")
def component_show(component_name: str) -> None:
    """Print the HTML source of COMPONENT_NAME."""
    from video_compose.overlays.component import _find_component

    try:
        html = _find_component(component_name)
        click.echo(html)
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# serve — REST API server
# ---------------------------------------------------------------------------

@main.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8765, show_default=True, type=int)
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload for development.")
@click.option("--workers", default=1, show_default=True, type=int)
def serve(host: str, port: int, reload: bool, workers: int) -> None:
    """Start the video-compose REST API server.

    The server exposes POST /render, GET /jobs/{id}, POST /validate, and more.

    Examples:

      video-compose serve --port 8765

      video-compose serve --host 127.0.0.1 --port 9000 --workers 2
    """
    try:
        import uvicorn
    except ImportError:
        click.echo("uvicorn is required — pip install 'video-compose[server]'", err=True)
        sys.exit(1)

    click.echo(f"Starting video-compose API server on http://{host}:{port}")
    click.echo("  Docs: http://{}:{}/docs".format(host if host != "0.0.0.0" else "localhost", port))
    uvicorn.run(
        "video_compose.server.app:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,
    )


# ---------------------------------------------------------------------------
# brand group — persistent brand kit
# ---------------------------------------------------------------------------

@main.group()
def brand() -> None:
    """Manage the persistent brand kit (colors, fonts, logo)."""


@brand.command("show")
def brand_show() -> None:
    """Show the current brand kit settings."""
    from video_compose.brand import load_brand, _BRAND_PATH

    kit = load_brand()
    if kit is None:
        click.echo(f"No brand kit set. File: {_BRAND_PATH}")
        click.echo("Use: video-compose brand set --help")
        return

    click.echo(f"Brand kit ({_BRAND_PATH}):")
    for k, v in kit.model_dump().items():
        click.echo(f"  {k:<20} {v}")


@brand.command("set")
@click.option("--primary", default=None, help="Primary text color (hex)")
@click.option("--accent", default=None, help="Accent color (hex)")
@click.option("--bg", default=None, help="Background color (hex)")
@click.option("--font", default=None, help="Default font family")
@click.option("--logo", default=None, help="Path to logo PNG")
@click.option("--logo-position", default=None, help="Logo position preset")
@click.option("--logo-opacity", type=float, default=None, help="Logo opacity (0.0–1.0)")
@click.option("--logo-scale", type=float, default=None, help="Logo width as % of canvas")
def brand_set(
    primary: str | None, accent: str | None, bg: str | None,
    font: str | None, logo: str | None, logo_position: str | None,
    logo_opacity: float | None, logo_scale: float | None,
) -> None:
    """Set brand kit properties. Unspecified fields keep their current values."""
    from video_compose.brand import load_brand, save_brand, BrandKit

    kit = load_brand() or BrandKit()

    if primary:
        kit = kit.model_copy(update={"primary_color": primary})
    if accent:
        kit = kit.model_copy(update={"accent_color": accent})
    if bg:
        kit = kit.model_copy(update={"background_color": bg})
    if font:
        kit = kit.model_copy(update={"font_family": font})
    if logo:
        kit = kit.model_copy(update={"logo_path": logo})
    if logo_position:
        kit = kit.model_copy(update={"logo_position": logo_position})
    if logo_opacity is not None:
        kit = kit.model_copy(update={"logo_opacity": logo_opacity})
    if logo_scale is not None:
        kit = kit.model_copy(update={"logo_scale_pct": logo_scale})

    save_brand(kit)
    click.echo("Brand kit saved:")
    for k, v in kit.model_dump().items():
        click.echo(f"  {k:<20} {v}")


@brand.command("reset")
@click.confirmation_option(prompt="Reset brand kit to defaults?")
def brand_reset() -> None:
    """Delete the brand kit, reverting to system defaults."""
    from video_compose.brand import reset_brand
    reset_brand()
    click.echo("Brand kit reset.")


# ---------------------------------------------------------------------------
# scene-detect
# ---------------------------------------------------------------------------

@main.command("scene-detect")
@click.argument("video_file", type=click.Path(exists=True, path_type=Path))
@click.option("--threshold", "-t", type=float, default=0.3, show_default=True,
              help="Scene change sensitivity (0.0–1.0).")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON array.")
def scene_detect(video_file: Path, threshold: float, as_json: bool) -> None:
    """Detect scene cut timestamps in VIDEO_FILE."""
    from video_compose.tools.scene_detect import detect_scenes

    times = detect_scenes(video_file, threshold=threshold)
    if as_json:
        click.echo(json.dumps(times))
    else:
        click.echo(f"Detected {len(times)} scene(s):")
        for t in times:
            click.echo(f"  {t:.3f}s")


# ---------------------------------------------------------------------------
# chunk
# ---------------------------------------------------------------------------

@main.command()
@click.argument("video_file", type=click.Path(exists=True, path_type=Path))
@click.option("--output-dir", "-o", type=click.Path(path_type=Path), default=None)
@click.option("--mode", type=click.Choice(["scene", "duration"]), default="scene", show_default=True)
@click.option("--duration", "-d", type=float, default=30.0, show_default=True,
              help="Chunk duration in seconds (duration mode only).")
@click.option("--threshold", type=float, default=0.3, show_default=True,
              help="Scene sensitivity (scene mode only).")
def chunk(video_file: Path, output_dir: Path | None, mode: str, duration: float, threshold: float) -> None:
    """Split VIDEO_FILE into chunks by scene or fixed duration."""
    from video_compose.tools.chunker import chunk_by_scene, chunk_by_duration

    out_dir = output_dir or Path("chunks") / video_file.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    if mode == "scene":
        clips = chunk_by_scene(video_file, out_dir, threshold=threshold)
    else:
        clips = chunk_by_duration(video_file, out_dir, duration=duration)

    click.echo(f"Created {len(clips)} chunk(s) in {out_dir}:")
    for c in clips:
        click.echo(f"  {c.name}")


# ---------------------------------------------------------------------------
# beats
# ---------------------------------------------------------------------------

@main.command()
@click.argument("audio_file", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Output beat times as JSON array.")
def beats(audio_file: Path, as_json: bool) -> None:
    """Detect BPM and beat timestamps in AUDIO_FILE."""
    try:
        from video_compose.audio.beats import detect_beats
    except ImportError:
        click.echo("librosa is required — pip install 'video-compose[audio-ai]'", err=True)
        sys.exit(1)

    result = detect_beats(audio_file)
    if as_json:
        click.echo(json.dumps({"bpm": result.bpm, "beats": result.beat_times.tolist()}))
    else:
        click.echo(f"BPM: {result.bpm:.1f}")
        click.echo(f"Beats: {len(result.beat_times)} detected")
        click.echo(f"First 10: {[round(t, 3) for t in result.beat_times[:10].tolist()]}")


# ---------------------------------------------------------------------------
# remove-bg
# ---------------------------------------------------------------------------

@main.command("remove-bg")
@click.argument("input_file", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
def remove_bg(input_file: Path, output: Path | None) -> None:
    """Remove background from an image or video file."""
    try:
        from video_compose.tools.bg_remove import remove_bg_image, remove_bg_video
    except ImportError:
        click.echo("rembg is required — pip install 'video-compose[visual-ai]'", err=True)
        sys.exit(1)

    suffix = input_file.suffix.lower()
    if suffix in (".mp4", ".mov", ".avi", ".webm", ".mkv"):
        out = output or input_file.with_stem(input_file.stem + "_nobg").with_suffix(".webm")
        click.echo(f"Removing background from video: {input_file.name}...")
        remove_bg_video(input_file, out)
    else:
        out = output or input_file.with_stem(input_file.stem + "_nobg").with_suffix(".png")
        click.echo(f"Removing background from image: {input_file.name}...")
        remove_bg_image(input_file, out)

    click.echo(f"  Done: {out}")


# ---------------------------------------------------------------------------
# highlight
# ---------------------------------------------------------------------------

@main.command()
@click.argument("video_file", type=click.Path(exists=True, path_type=Path))
@click.option("--output-dir", "-o", type=click.Path(path_type=Path), default=None)
@click.option("--max-duration", type=float, default=60.0, show_default=True,
              help="Target total highlight reel duration (seconds).")
@click.option("--n-clips", type=int, default=None, help="Maximum number of highlight clips.")
def highlight(video_file: Path, output_dir: Path | None, max_duration: float, n_clips: int | None) -> None:
    """Extract a highlight reel from VIDEO_FILE using AI scoring."""
    try:
        from video_compose.tools.highlight import extract_highlights, render_highlight_reel
    except ImportError as exc:
        click.echo(f"Missing dependency: {exc}", err=True)
        sys.exit(1)

    out_dir = output_dir or Path("highlights") / video_file.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"Extracting highlights from {video_file.name}...")
    clips = extract_highlights(video_file, max_duration=max_duration, n_clips=n_clips)
    click.echo(f"  Selected {len(clips)} clip(s)")

    reel = render_highlight_reel(video_file, clips, out_dir / "highlight_reel.mp4")
    click.echo(f"  Reel: {reel}")


# ---------------------------------------------------------------------------
# repurpose
# ---------------------------------------------------------------------------

@main.command()
@click.argument("video_file", type=click.Path(exists=True, path_type=Path))
@click.option("--output-dir", "-o", type=click.Path(path_type=Path), default=None)
@click.option("--n-clips", type=int, default=5, show_default=True,
              help="Number of short clips to extract.")
@click.option("--clip-duration", type=float, default=30.0, show_default=True,
              help="Target duration per clip (seconds).")
def repurpose(video_file: Path, output_dir: Path | None, n_clips: int, clip_duration: float) -> None:
    """Repurpose a long video into N short-form clips with TVCS spec JSONs."""
    try:
        from video_compose.tools.repurpose import repurpose as _repurpose
    except ImportError as exc:
        click.echo(f"Missing dependency: {exc}", err=True)
        sys.exit(1)

    out_dir = output_dir or Path("repurposed") / video_file.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"Repurposing {video_file.name} → {n_clips} clip(s)...")
    specs = _repurpose(video_file, out_dir, n_clips=n_clips, clip_duration=clip_duration)
    click.echo(f"  Generated {len(specs)} spec file(s):")
    for s in specs:
        click.echo(f"    {s}")


# ---------------------------------------------------------------------------
# chapters
# ---------------------------------------------------------------------------

@main.command()
@click.argument("video_file", type=click.Path(exists=True, path_type=Path))
@click.option("--output-dir", "-o", type=click.Path(path_type=Path), default=None)
@click.option("--embed", is_flag=True, default=False, help="Embed chapters into the MP4 file.")
@click.option("--json", "as_json", is_flag=True, help="Output chapters as JSON.")
def chapters(video_file: Path, output_dir: Path | None, embed: bool, as_json: bool) -> None:
    """Generate chapter markers for VIDEO_FILE via AI transcript analysis."""
    try:
        from video_compose.tools.chapters import generate_chapters, export_chapters, embed_chapters_in_mp4
    except ImportError as exc:
        click.echo(f"Missing dependency: {exc}", err=True)
        sys.exit(1)

    click.echo(f"Generating chapters for {video_file.name}...")
    chapter_list = generate_chapters(video_file)

    if as_json:
        click.echo(json.dumps([{"start": c.start_sec, "title": c.title} for c in chapter_list], indent=2))
        return

    out_dir = output_dir or video_file.parent
    txt_out = out_dir / (video_file.stem + "_chapters.txt")
    ffmeta_out = out_dir / (video_file.stem + "_chapters.ffmeta")
    export_chapters(chapter_list, txt_out, ffmeta_out)
    click.echo(f"  YouTube chapters: {txt_out}")
    click.echo(f"  FFMETADATA:       {ffmeta_out}")

    if embed:
        embedded = embed_chapters_in_mp4(video_file, ffmeta_out)
        click.echo(f"  Embedded in:      {embedded}")


# ---------------------------------------------------------------------------
# check-captions
# ---------------------------------------------------------------------------

@main.command("check-captions")
@click.argument("srt_file", type=click.Path(exists=True, path_type=Path))
@click.option("--max-cps", type=float, default=20.0, show_default=True,
              help="Maximum characters per second.")
@click.option("--max-line-length", type=int, default=42, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Output violations as JSON.")
def check_captions(srt_file: Path, max_cps: float, max_line_length: int, as_json: bool) -> None:
    """Check SRT_FILE for caption compliance violations."""
    from video_compose.tools.caption_check import check_srt_file

    violations = check_srt_file(srt_file, max_cps=max_cps, max_line_length=max_line_length)

    if as_json:
        click.echo(json.dumps([
            {"cue": v.cue_index, "type": v.violation_type, "message": v.message}
            for v in violations
        ], indent=2))
        return

    if not violations:
        click.echo(f"OK  {srt_file.name}  — no compliance violations")
    else:
        click.echo(f"VIOLATIONS  {len(violations)} found in {srt_file.name}:", err=True)
        for v in violations:
            click.echo(f"  Cue {v.cue_index}: [{v.violation_type}] {v.message}", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# translate-captions
# ---------------------------------------------------------------------------

@main.command("translate-captions")
@click.argument("srt_file", type=click.Path(exists=True, path_type=Path))
@click.option("--to", "target_lang", required=True, help="Target language (e.g. 'sv', 'de', 'fr').")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
def translate_captions(srt_file: Path, target_lang: str, output: Path | None) -> None:  # noqa: F811
    """Translate SRT_FILE captions to another language via LLM."""
    try:
        from video_compose.audio.caption_translate import translate_srt_file
    except ImportError as exc:
        click.echo(f"Missing dependency: {exc}", err=True)
        sys.exit(1)

    out = output or srt_file.with_stem(srt_file.stem + f"_{target_lang}")
    click.echo(f"Translating {srt_file.name} → {target_lang}...")
    translate_srt_file(srt_file, out, target_lang=target_lang)
    click.echo(f"  Done: {out}")


# ---------------------------------------------------------------------------
# batch — parallel multi-spec render
# ---------------------------------------------------------------------------

@main.command()
@click.argument("spec_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--output-dir", "-o", type=click.Path(path_type=Path), default=None,
              help="Root output directory; each spec gets its own sub-folder.")
@click.option("--workers", "-w", type=int, default=1, show_default=True,
              help="Number of parallel render workers.")
@click.option("--pattern", default="*.json", show_default=True,
              help="Glob pattern to match spec files inside SPEC_DIR.")
@click.option("--fail-fast", is_flag=True, default=False,
              help="Abort the batch on the first failure.")
@click.option("--social-preset", default=None,
              help="Apply a social platform preset to every spec: reels, tiktok, shorts, ...")
def batch(
    spec_dir: Path,
    output_dir: Path | None,
    workers: int,
    pattern: str,
    fail_fast: bool,
    social_preset: str | None,
) -> None:
    """Render all spec JSON files found in SPEC_DIR.

    Each spec is rendered into its own sub-folder inside OUTPUT_DIR (or
    ./batch_output/<spec_stem>/ by default).

    Examples:

      video-compose batch ./specs/ --workers 4

      video-compose batch ./specs/ --social-preset reels -o ./reels_output/
    """
    import concurrent.futures
    import time
    from video_compose.api import compose, load_spec

    specs = sorted(spec_dir.glob(pattern))
    if not specs:
        click.echo(f"No files matching {pattern!r} found in {spec_dir}.", err=True)
        sys.exit(1)

    root_out = output_dir or Path("batch_output")
    click.echo(f"Batch rendering {len(specs)} spec(s) with {workers} worker(s)...")

    results: list[dict] = []
    lock = __import__("threading").Lock()

    def _render_one(spec_path: Path) -> dict:
        t0 = time.monotonic()
        out_dir = root_out / spec_path.stem
        try:
            spec = load_spec(spec_path)
            if social_preset:
                from video_compose.social import apply_social_to_spec
                apply_social_to_spec(spec, social_preset)
            result = compose(spec, output_dir=out_dir)
            elapsed = round(time.monotonic() - t0, 1)
            return {"spec": spec_path.name, "status": "ok", "elapsed_s": elapsed,
                    "output": str(result.video_path), "warnings": result.warnings}
        except Exception as exc:
            elapsed = round(time.monotonic() - t0, 1)
            return {"spec": spec_path.name, "status": "error", "elapsed_s": elapsed,
                    "error": str(exc)}

    failed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_render_one, s): s for s in specs}
        for future in concurrent.futures.as_completed(futures):
            r = future.result()
            with lock:
                results.append(r)
                if r["status"] == "ok":
                    click.echo(f"  OK   {r['spec']}  ({r['elapsed_s']}s)")
                    for w in r.get("warnings", []):
                        click.echo(f"       warn: {w}", err=True)
                else:
                    failed += 1
                    click.echo(f"  FAIL {r['spec']}  — {r['error']}", err=True)
                    if fail_fast:
                        pool.shutdown(wait=False, cancel_futures=True)
                        click.echo("Aborted (--fail-fast).", err=True)
                        sys.exit(1)

    ok = len(results) - failed
    click.echo(f"\nDone: {ok}/{len(specs)} succeeded, {failed} failed → {root_out}")
    if failed:
        sys.exit(1)


# ---------------------------------------------------------------------------
# report — quality report for a single rendered video
# ---------------------------------------------------------------------------

@main.command("report")
@click.argument("video_file", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None,
              help="Save report JSON to this path.")
@click.option("--json", "as_json", is_flag=True, help="Print report as JSON.")
def report_cmd(video_file: Path, output: Path | None, as_json: bool) -> None:
    """Generate a quality report for a rendered video file.

    Probes the video with ffprobe and prints duration, resolution, codec,
    bitrate, and file size.

    Examples:

      video-compose report output/video.mp4

      video-compose report output/video.mp4 --json --output report.json
    """
    from video_compose.tools.report import generate_single_report

    data = generate_single_report(video_file)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        click.echo(f"Report saved: {output}")

    if as_json:
        click.echo(json.dumps(data, indent=2))
        return

    click.echo(f"\nVideo report: {video_file.name}")
    click.echo(f"  File size   : {data.get('file_size_mb')} MB")
    click.echo(f"  Duration    : {data.get('duration_s')} s")
    click.echo(f"  Resolution  : {data.get('width')}×{data.get('height')}")
    click.echo(f"  FPS         : {data.get('fps')}")
    click.echo(f"  Codec       : {data.get('codec')}")
    click.echo(f"  Bitrate     : {data.get('bitrate_kbps')} kbps")
    if data.get("error"):
        click.echo(f"  Error       : {data['error']}", err=True)


# ---------------------------------------------------------------------------
# social-presets — list available social format presets
# ---------------------------------------------------------------------------

@main.command("social-presets")
def social_presets_cmd() -> None:
    """List available social platform presets for --social-preset."""
    from video_compose.social import SOCIAL_PRESETS

    click.echo("Available social presets:\n")
    click.echo(f"  {'PRESET':<20} {'RESOLUTION':<14} {'FPS':<6} {'LUFS':<8} {'SAFE ZONE'}")
    click.echo("  " + "-" * 60)
    for name, cfg in sorted(SOCIAL_PRESETS.items()):
        res = f"{cfg['width']}×{cfg['height']}"
        fps = str(cfg["fps"])
        lufs = str(cfg.get("loudnorm_lufs", "—"))
        safe = f"{cfg.get('safe_zone_pct', 0)}%" if cfg.get("safe_zone_pct") else "—"
        click.echo(f"  {name:<20} {res:<14} {fps:<6} {lufs:<8} {safe}")

    click.echo(f"\nUsage: video-compose render spec.json --social-preset reels")
    click.echo(f"       video-compose batch ./specs/ --social-preset tiktok")


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
