"""
TVCS semantic validator.

Two-pass validation:
  Pass 1 — Pydantic structural parse (type/shape correctness).
  Pass 2 — Semantic checks (cross-references, catalog membership, etc.).

Semantic checks degrade gracefully: if an fx package is not installed the
check is skipped with a warning rather than a hard error.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_SOURCE_REF_RE = re.compile(r"^\$sources\.([a-zA-Z_]\w*)$")

# Known effects per segment type — used when the backing package is not
# installed so we can still flag obvious typos.
_MATHVIZ_EFFECTS = frozenset({
    "matrix_rain", "kaleidoscope", "plasma", "voronoi", "tunnel",
    "spirograph", "fractal_tree", "lissajous", "fourier", "wave",
    "interference", "reaction_diffusion", "cellular_automata",
    "mandelbrot", "julia", "newton", "burning_ship", "sierpinski",
    "barnsley_fern", "dragon_curve", "hilbert_curve", "lorenz",
    "rossler", "double_pendulum", "particle_flow",
})

_SHAPE_EFFECTS = frozenset({
    "constellation", "geometric", "kinetic", "reveal", "ambient",
    "pulse", "ripple", "lattice", "helix", "orbit", "prism",
    "bloom", "fracture", "shatter", "assemble", "spiral",
    "vortex", "wave", "grid", "dots", "lines", "rings",
    "polygons", "stars", "flow",
})

_STILL_MOTIONS = frozenset({
    "ken_burns", "zoom_in", "zoom_out", "pan_left", "pan_right", "static",
})

_GEOMAP_VIEWS = frozenset({
    "regions", "municipalities", "region_municipalities",
    "region_valdistrikt", "municipality_valdistrikt",
})


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def error(self, msg: str) -> None:
        self.errors.append(msg)
        self.is_valid = False

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def __str__(self) -> str:
        lines = []
        for e in self.errors:
            lines.append(f"  ERROR   {e}")
        for w in self.warnings:
            lines.append(f"  WARNING {w}")
        status = "VALID" if self.is_valid else "INVALID"
        return f"{status} ({len(self.errors)} errors, {len(self.warnings)} warnings)\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate(spec: dict) -> ValidationResult:
    """Validate a raw TVCS dict. Returns a ValidationResult."""
    result = ValidationResult()

    # Pass 1 — structural (Pydantic)
    parsed = _structural_parse(spec, result)
    if parsed is None:
        return result  # can't proceed without a parsed model

    # Pass 2 — semantic
    declared_sources = set(parsed.data_sources.keys())
    segment_ids = [seg.id for seg in parsed.segments]

    _check_source_refs(parsed, declared_sources, result)
    _check_transition_overrides(parsed, segment_ids, result)
    _check_grade_slugs(parsed, result)
    _check_transition_slugs(parsed, result)
    _check_segment_effects(parsed, result)
    _check_overlay_effects(parsed, result)
    _check_audio_consistency(parsed, result)
    _check_output_path(parsed, result)

    return result


# ---------------------------------------------------------------------------
# Pass 1
# ---------------------------------------------------------------------------

def _structural_parse(spec: dict, result: ValidationResult):
    try:
        from pydantic import ValidationError
        from video_compose.schema.spec import TVCSSpec
        return TVCSSpec.model_validate(spec)
    except Exception as exc:
        # ImportError means spec.py itself has a bug — surface it
        try:
            from pydantic import ValidationError
            if isinstance(exc, ValidationError):
                for err in exc.errors():
                    loc = " -> ".join(str(p) for p in err["loc"])
                    result.error(f"{loc}: {err['msg']}")
            else:
                result.error(f"Parse error: {exc}")
        except ImportError:
            result.error(f"Parse error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Pass 2 helpers
# ---------------------------------------------------------------------------

def _iter_data_refs(parsed) -> list[tuple[str, str]]:
    """Yield (segment_id, ref_string) for every $sources.xxx DataRef found."""
    pairs = []
    for seg in parsed.segments:
        data = getattr(seg, "data", None)
        if isinstance(data, str):
            m = _SOURCE_REF_RE.match(data)
            if m:
                pairs.append((seg.id, data))
    return pairs


def _check_source_refs(parsed, declared: set[str], result: ValidationResult) -> None:
    for seg_id, ref in _iter_data_refs(parsed):
        m = _SOURCE_REF_RE.match(ref)
        if not m:
            result.error(f"segment '{seg_id}': data ref {ref!r} is not a valid $sources expression")
            continue
        source_id = m.group(1)
        if source_id not in declared:
            known = ", ".join(sorted(declared)) or "(none)"
            result.error(
                f"segment '{seg_id}': data ref '$sources.{source_id}' is not declared; "
                f"declared sources: {known}"
            )


def _check_transition_overrides(parsed, segment_ids: list[str], result: ValidationResult) -> None:
    id_set = set(segment_ids)
    for i, override in enumerate(parsed.transitions.overrides):
        if override.from_segment not in id_set:
            result.error(
                f"transitions.overrides[{i}].from: segment id {override.from_segment!r} not found"
            )
        if override.to not in id_set:
            result.error(
                f"transitions.overrides[{i}].to: segment id {override.to!r} not found"
            )


def _get_color_fx_grades() -> frozenset[str] | None:
    try:
        from color_fx.engines.grade_recipe import _SLUG_MAP
        return frozenset(_SLUG_MAP.keys())
    except ImportError:
        return None


def _check_grade_slugs(parsed, result: ValidationResult) -> None:
    valid_grades = _get_color_fx_grades()
    if valid_grades is None:
        if parsed.theme.grade:
            result.warn(
                "color-fx not installed — cannot validate grade slugs "
                "(install color-fx to enable grade validation)"
            )
        return

    def _check_slug(slug: str, location: str) -> None:
        if slug and slug not in valid_grades:
            close = _closest(slug, valid_grades)
            hint = f"; did you mean {close!r}?" if close else ""
            result.error(f"{location}: unknown color-fx grade {slug!r}{hint}")

    if parsed.theme.grade:
        _check_slug(parsed.theme.grade, "theme.grade")

    for seg in parsed.segments:
        if seg.grade:
            _check_slug(seg.grade, f"segment '{seg.id}'.grade")


def _get_cutfx_slug_set() -> frozenset[str] | None:
    """Return all valid cut-fx slugs for fuzzy suggestions."""
    try:
        from cut_fx.catalog.loader import load_catalog
        cat = load_catalog()
        return frozenset(t["slug"] for t in cat["transitions"])
    except Exception:
        return None


def _resolve_cutfx(name: str) -> bool:
    """Return True if cut-fx can resolve this transition name (slug or display)."""
    try:
        from cut_fx.catalog.loader import get_transition_info
        get_transition_info(name)
        return True
    except Exception:
        return False


def _check_transition_slugs(parsed, result: ValidationResult) -> None:
    try:
        from cut_fx.catalog.loader import load_catalog  # noqa: F401 — availability check
    except ImportError:
        result.warn(
            "cut-fx not installed — cannot validate transition slugs "
            "(install cut-fx to enable transition validation)"
        )
        return

    slug_set = _get_cutfx_slug_set() or frozenset()

    def _check(t_type: str, location: str) -> None:
        if not t_type:
            return
        if not _resolve_cutfx(t_type):
            close = _closest(t_type, slug_set)
            hint = f"; did you mean {close!r}?" if close else ""
            result.error(f"{location}: unknown cut-fx transition {t_type!r}{hint}")

    _check(parsed.transitions.default.type, "transitions.default.type")

    for i, override in enumerate(parsed.transitions.overrides):
        _check(override.type, f"transitions.overrides[{i}].type")

    for seg in parsed.segments:
        if seg.transition_in:
            _check(seg.transition_in.type, f"segment '{seg.id}'.transition_in.type")
        if seg.transition_out:
            _check(seg.transition_out.type, f"segment '{seg.id}'.transition_out.type")


def _check_segment_effects(parsed, result: ValidationResult) -> None:
    from video_compose.schema.spec import (
        ChartSegment, FractalSegment, GeomapSegment,
        ImageSegment, MathvizSegment, ShapeSegment,
        StillSegment, VideoSegment,
    )

    for seg in parsed.segments:
        sid = seg.id

        if isinstance(seg, MathvizSegment):
            _check_known_effect(seg.effect, _MATHVIZ_EFFECTS, f"segment '{sid}' (mathviz)", result,
                                package="mathviz-fx", dynamic_loader=_get_mathviz_effects)

        elif isinstance(seg, ShapeSegment):
            _check_known_effect(seg.effect, _SHAPE_EFFECTS, f"segment '{sid}' (shape)", result,
                                package="shape-fx", dynamic_loader=None)

        elif isinstance(seg, ChartSegment):
            # chart_type is already Literal-validated by Pydantic — nothing extra needed
            if not seg.data:
                result.error(f"segment '{sid}' (chart): 'data' is required")

        elif isinstance(seg, GeomapSegment):
            if not seg.data:
                result.error(f"segment '{sid}' (geomap): 'data' is required")

        elif isinstance(seg, StillSegment):
            if seg.motion not in _STILL_MOTIONS:
                result.error(f"segment '{sid}' (still): unknown motion {seg.motion!r}")

        elif isinstance(seg, (ImageSegment, VideoSegment)):
            if not getattr(seg, "source", None):
                result.error(f"segment '{sid}' ({seg.type}): 'source' is required")


def _check_known_effect(
    effect: str,
    fallback_set: frozenset[str],
    location: str,
    result: ValidationResult,
    package: str,
    dynamic_loader,
) -> None:
    known = dynamic_loader() if dynamic_loader else None
    effective_set = known if known is not None else fallback_set

    if effect not in effective_set:
        if known is None:
            # package not installed — only warn, don't hard-error
            result.warn(
                f"{location}: effect {effect!r} not in known list "
                f"(install {package} to enable full effect validation)"
            )
        else:
            close = _closest(effect, effective_set)
            hint = f"; did you mean {close!r}?" if close else ""
            result.error(f"{location}: unknown effect {effect!r}{hint}")


def _get_mathviz_effects() -> frozenset[str] | None:
    try:
        from mathviz_fx.generators.generator_factory import BackgroundGeneratorFactory
        return frozenset(BackgroundGeneratorFactory.list_generators())
    except Exception:
        return None


def _check_overlay_effects(parsed, result: ValidationResult) -> None:
    from video_compose.schema.spec import TextOverlay

    text_effects = _get_textfx_effects()

    for seg in parsed.segments:
        for i, overlay in enumerate(seg.overlays):
            loc = f"segment '{seg.id}'.overlays[{i}]"
            if isinstance(overlay, TextOverlay):
                if not overlay.text.strip():
                    result.error(f"{loc}: text overlay has empty 'text'")
                if text_effects is not None and overlay.effect not in text_effects:
                    close = _closest(overlay.effect, text_effects)
                    hint = f"; did you mean {close!r}?" if close else ""
                    result.error(f"{loc}: unknown text-fx effect {overlay.effect!r}{hint}")
                elif text_effects is None and overlay.effect != "fade_in":
                    result.warn(
                        f"{loc}: cannot validate text-fx effect {overlay.effect!r} "
                        "(install text-fx to enable validation)"
                    )


def _get_textfx_effects() -> frozenset[str] | None:
    try:
        from text_fx import list_effects
        return frozenset(list_effects())
    except Exception:
        return None


def _check_audio_consistency(parsed, result: ValidationResult) -> None:
    audio = parsed.audio
    if audio.voiceover and audio.voiceover.script == "auto":
        has_narration = any(
            getattr(seg, "narration", None) for seg in parsed.segments
        )
        if not has_narration:
            result.warn(
                "audio.voiceover.script is 'auto' but no segments have 'narration' text; "
                "voiceover will be silent"
            )

    for i, track in enumerate(audio.tracks):
        timing = track.timing
        if timing not in ("throughout", "intro", "outro"):
            seg_ids = {seg.id for seg in parsed.segments}
            if timing not in seg_ids:
                result.error(
                    f"audio.tracks[{i}].timing: {timing!r} is not a valid segment id "
                    f"or one of 'throughout', 'intro', 'outro'"
                )


def _check_output_path(parsed, result: ValidationResult) -> None:
    import os
    path = parsed.output.path
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.exists(parent):
        result.warn(
            f"output.path parent directory does not exist: {parent!r} "
            "(will be created at render time)"
        )

    total_duration = sum(seg.duration for seg in parsed.segments)
    if total_duration < 1.0:
        result.warn(f"Total segment duration is only {total_duration:.1f}s; video will be very short")
    if total_duration > 600.0:
        result.warn(f"Total segment duration is {total_duration:.0f}s (>10min); render may take a long time")


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _closest(name: str, candidates: frozenset[str]) -> str | None:
    import difflib
    matches = difflib.get_close_matches(name.lower(), [c.lower() for c in candidates], n=1, cutoff=0.5)
    if not matches:
        return None
    target = matches[0]
    for c in candidates:
        if c.lower() == target:
            return c
    return None
