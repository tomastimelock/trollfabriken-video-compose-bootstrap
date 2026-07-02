"""
PromptBuilder — assembles the LLM system prompt for TVCS spec generation.

Gathers:
  - The full TVCS JSON Schema (from TVCSSpec.model_json_schema())
  - FX catalogs (effects/types) — dynamic where packages are installed,
    static fallback where they are not
  - A concise segment-type reference table

Usage::

    pb = PromptBuilder()
    messages = [
        {"role": "system", "content": pb.build_system_prompt()},
        {"role": "user",   "content": pb.build_user_prompt("30-second product launch video")},
    ]
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Static fallback catalogs — kept in sync with the Pydantic Literal fields
# and the fx-package known-effects sets in the validator.
# ---------------------------------------------------------------------------

_MATHVIZ_EFFECTS: list[str] = [
    "matrix_rain", "kaleidoscope", "plasma", "voronoi", "tunnel",
    "spirograph", "fractal_tree", "lissajous", "fourier", "wave",
    "interference", "reaction_diffusion", "cellular_automata",
    "mandelbrot", "julia", "newton", "burning_ship", "sierpinski",
    "barnsley_fern", "dragon_curve", "hilbert_curve",
    "lorenz", "rossler", "double_pendulum", "particle_flow",
]

_SHAPE_EFFECTS: list[str] = [
    "constellation", "geometric", "kinetic", "reveal", "ambient",
    "pulse", "ripple", "lattice", "helix", "orbit", "prism",
    "bloom", "fracture", "shatter", "assemble", "spiral",
    "vortex", "wave", "grid", "dots", "lines", "rings",
    "polygons", "stars", "flow",
]

_CHART_TYPES: list[str] = [
    "bar", "line", "scatter", "pie", "heatmap",
    "treemap", "sankey", "area", "radar", "bubble",
    "waterfall", "funnel", "gantt", "histogram",
]

_GEOMAP_VIEWS: list[str] = [
    "regions", "municipalities", "region_municipalities",
    "region_valdistrikt", "municipality_valdistrikt",
]

_TEXT_EFFECTS_FALLBACK: list[str] = [
    "fade_in", "slide_up", "slide_down", "slide_left", "slide_right",
    "typewriter", "glow", "neon_pulse", "blur_in", "zoom_in",
    "rotate_in", "bounce", "wave", "flicker",
]

_FRACTAL_EFFECTS: list[str] = [
    "mandelbrot", "julia", "burning_ship", "newton",
    "sierpinski", "barnsley_fern", "dragon_curve",
]

_STILL_MOTIONS: list[str] = [
    "ken_burns", "zoom_in", "zoom_out", "pan_left", "pan_right", "static",
]

_IMAGE_FITS: list[str] = ["cover", "contain", "stretch"]

_POSITIONS: list[str] = [
    "center", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right",
]


# ---------------------------------------------------------------------------
# FXCatalog dataclass — snapshot of what is available at runtime
# ---------------------------------------------------------------------------

@dataclass
class FXCatalog:
    """Runtime snapshot of all available FX effects and types."""
    mathviz_effects: list[str] = field(default_factory=lambda: list(_MATHVIZ_EFFECTS))
    shape_effects: list[str] = field(default_factory=lambda: list(_SHAPE_EFFECTS))
    chart_types: list[str] = field(default_factory=lambda: list(_CHART_TYPES))
    fractal_effects: list[str] = field(default_factory=lambda: list(_FRACTAL_EFFECTS))
    geomap_views: list[str] = field(default_factory=lambda: list(_GEOMAP_VIEWS))
    text_effects: list[str] = field(default_factory=lambda: list(_TEXT_EFFECTS_FALLBACK))
    still_motions: list[str] = field(default_factory=lambda: list(_STILL_MOTIONS))
    image_fits: list[str] = field(default_factory=lambda: list(_IMAGE_FITS))
    overlay_positions: list[str] = field(default_factory=lambda: list(_POSITIONS))
    grade_slugs: list[str] = field(default_factory=list)
    transition_types: list[str] = field(default_factory=list)

    # Which catalogs were populated from live packages vs static fallback
    sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if k != "sources"}


# ---------------------------------------------------------------------------
# PromptBuilder
# ---------------------------------------------------------------------------

class PromptBuilder:
    """Builds LLM prompts for TVCS spec generation.

    Call ``build_system_prompt()`` once and cache it — it does I/O to gather
    dynamic catalogs. ``build_user_prompt()`` is cheap and stateless.
    """

    def __init__(self) -> None:
        self._catalog: FXCatalog | None = None
        self._schema: dict | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Return the full system prompt string to inject as the LLM's system role."""
        catalog = self.get_catalog()
        schema = self._get_schema()
        return _SYSTEM_TEMPLATE.format(
            schema_json=json.dumps(schema, indent=2),
            catalog_json=json.dumps(catalog.to_dict(), indent=2),
            segment_ref=_build_segment_reference(catalog),
        )

    def build_user_prompt(
        self,
        description: str,
        *,
        output_width: int = 1920,
        output_height: int = 1080,
        fps: int = 30,
        total_duration: float | None = None,
        data_context: str | None = None,
        style_hints: str | None = None,
    ) -> str:
        """Return the user-role message that instructs the LLM to generate a spec.

        Args:
            description:    Free-text description of the desired video.
            output_width:   Target video width in pixels.
            output_height:  Target video height in pixels.
            fps:            Target frame rate.
            total_duration: Desired video length in seconds, or None for LLM to decide.
            data_context:   Description of any data sources available (e.g. column names).
            style_hints:    Additional style/branding instructions.
        """
        parts = [f"Video description: {description.strip()}"]

        output_line = f"Output: {output_width}x{output_height} @ {fps} fps"
        if total_duration:
            output_line += f", ~{total_duration:.0f}s total"
        parts.append(output_line)

        if data_context:
            parts.append(f"Available data: {data_context.strip()}")

        if style_hints:
            parts.append(f"Style: {style_hints.strip()}")

        parts.append(
            "\nRespond with a single JSON object that is a valid TVCS spec. "
            "No markdown fences, no explanation — raw JSON only."
        )
        return "\n".join(parts)

    def get_catalog(self) -> FXCatalog:
        """Return the FXCatalog, building it once and caching it."""
        if self._catalog is None:
            self._catalog = _build_catalog()
        return self._catalog

    def invalidate_catalog(self) -> None:
        """Force a fresh catalog build on next call (useful after installing packages)."""
        self._catalog = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_schema(self) -> dict:
        if self._schema is None:
            from video_compose.schema.spec import TVCSSpec
            self._schema = TVCSSpec.model_json_schema()
        return self._schema


# ---------------------------------------------------------------------------
# Catalog builder — dynamic with static fallbacks
# ---------------------------------------------------------------------------

def _build_catalog() -> FXCatalog:
    cat = FXCatalog()

    # mathviz-fx
    try:
        from mathviz_fx.generators.generator_factory import BackgroundGeneratorFactory
        cat.mathviz_effects = sorted(BackgroundGeneratorFactory.list_generators())
        cat.sources["mathviz_effects"] = "mathviz-fx"
    except Exception:
        cat.sources["mathviz_effects"] = "static"

    # text-fx
    try:
        from text_fx import list_effects
        cat.text_effects = sorted(list_effects())
        cat.sources["text_effects"] = "text-fx"
    except Exception:
        cat.sources["text_effects"] = "static"

    # color-fx (grade slugs)
    try:
        from color_fx.engines.grade_recipe import _SLUG_MAP
        cat.grade_slugs = sorted(_SLUG_MAP.keys())
        cat.sources["grade_slugs"] = "color-fx"
    except Exception:
        cat.grade_slugs = []
        cat.sources["grade_slugs"] = "unavailable"

    # cut-fx (transition types)
    try:
        from cut_fx.catalog.loader import load_catalog
        data = load_catalog()
        cat.transition_types = sorted(t["slug"] for t in data["transitions"])
        cat.sources["transition_types"] = "cut-fx"
    except Exception:
        cat.transition_types = ["dissolve_ii", "fade_to_black", "hard_cut", "wipe_left", "wipe_right"]
        cat.sources["transition_types"] = "static"

    # These are schema-derived, always accurate
    cat.sources["chart_types"] = "schema"
    cat.sources["geomap_views"] = "schema"
    cat.sources["fractal_effects"] = "static"
    cat.sources["shape_effects"] = "static"
    cat.sources["still_motions"] = "schema"
    cat.sources["image_fits"] = "schema"
    cat.sources["overlay_positions"] = "schema"

    return cat


# ---------------------------------------------------------------------------
# Segment reference table builder
# ---------------------------------------------------------------------------

def _build_segment_reference(catalog: FXCatalog) -> str:
    rows = [
        ("blank",   "Solid color fill",
         f"color: hex (e.g. '#0d0d1a')"),
        ("mathviz", "Animated generative background (mathviz-fx)",
         f"effect: one of {catalog.mathviz_effects[:6]}..."),
        ("chart",   "Animated data chart (chart-fx)",
         f"chart_type: {catalog.chart_types}; data: inline dict or '$sources.id'"),
        ("geomap",  "Animated choropleth map (geo-map-fx)",
         f"view: {catalog.geomap_views}; data: area_code->float dict or '$sources.id'"),
        ("shape",   "Particle/geometric effect (shape-fx)",
         f"effect: one of {catalog.shape_effects[:6]}..."),
        ("fractal", "Fractal zoom animation (fractal-fx)",
         f"effect: {catalog.fractal_effects}"),
        ("still",   "Animated still image / Ken Burns etc. (still-motion)",
         f"source: path/url; motion: {catalog.still_motions}"),
        ("image",   "Static or lightly animated image",
         f"source: path/url; fit: {catalog.image_fits}; motion: {catalog.still_motions}"),
        ("video",   "Passthrough video clip",
         "source: path; start_time, loop, mute"),
        ("slide",   "Rendered presentation slide (slide-render)",
         "slide_spec: inline deck-spec dict or path to .json; motion: ken_burns|static"),
    ]
    lines = ["| type | description | key fields |",
             "|------|-------------|------------|"]
    for t, desc, keys in rows:
        lines.append(f"| {t} | {desc} | {keys} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

_SYSTEM_TEMPLATE = """\
You are a video composition assistant for the Trollfabriken Video Composition Spec (TVCS) system.

## Your task
Generate a valid TVCS v1.0 JSON spec from the user's description. The spec drives a \
code-based video renderer — every field you write must conform exactly to the schema below.

## Output rules
- Respond with a single raw JSON object. No markdown fences, no commentary.
- The top-level key "tvcs" must be "1.0".
- Every segment must have a unique string "id" and a positive float "duration" (seconds).
- Segment type is set with the "type" field — see the reference table below.
- Data references use "$sources.<id>" pointing to a key in "data_sources".
- Overlay timing uses the "timing" sub-object: {{"start": float, "end": float}}.
- Unknown or extra fields cause validation errors — use only schema-defined fields.

## Segment type reference
{segment_ref}

## Available FX catalog
```json
{catalog_json}
```

## Full TVCS JSON Schema
```json
{schema_json}
```

## Tips
- For title cards, use type "blank" with a "text" overlay.
- For data-driven segments, declare the source in "data_sources" and reference it as "$sources.<id>".
- Keep segment durations realistic (2–8s for most segments).
- Set transitions.default.type to one of the available transition_types in the catalog.
- If grade_slugs is non-empty, you can set theme.grade or per-segment grade for colour grading.
- The "config" field on mathviz/chart/shape/fractal segments accepts arbitrary kwargs passed \
to the underlying FX engine — omit it or leave it {{}} if you have no specific overrides.
"""
