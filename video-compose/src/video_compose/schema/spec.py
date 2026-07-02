"""
TVCS — Trollfabriken Video Composition Spec v1
Pydantic v2 models for the full JSON schema.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Template metadata (for .json template files; not part of TVCSSpec)
# ---------------------------------------------------------------------------

class TemplateVariable(BaseModel):
    """One fillable variable slot declared in a template's 'variables' list."""

    name: str = Field(description="Variable name — referenced as {{name}} in spec fields")
    type: Literal[
        "string", "color", "image_path", "video_path", "audio_path",
        "number", "duration", "boolean", "data_ref", "data_source_config",
    ] = "string"
    label: str = Field(default="", description="Human-readable label for editors and prompts")
    description: str = Field(default="", description="Longer explanation shown to users/AI when filling")
    required: bool = True
    default: Any = None
    choices: list[Any] | None = Field(default=None, description="Allowed values for enum-style string vars")


class TemplateMetadata(BaseModel):
    """Template block present in .json template files; stripped before render."""
    model_config = ConfigDict(extra="allow")

    id: str = Field(description="Unique slug — bundled templates use plain slugs, user templates require 'user.' prefix")
    name: str
    category: str
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    preview_thumbnail: str | None = Field(default=None, description="Relative path to 400×225 JPEG thumbnail")
    preview_full: str | None = Field(default=None, description="Relative path to full-size preview JPEG")
    author: str = "Trollfabriken"
    version: str = "1.0"
    variables: list[TemplateVariable] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------

_SOURCE_REF_RE = re.compile(r"^\$sources\.[a-zA-Z_]\w*$")


def _is_source_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(_SOURCE_REF_RE.match(value))


# Data references: inline data OR "$sources.<id>" pointer
DataRef = Any  # validated semantically by the spec validator


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

class MetaConfig(BaseModel):
    title: str = "Untitled"
    description: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    created: str | None = None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class OutputConfig(BaseModel):
    width: int = Field(default=1280, gt=0)
    height: int = Field(default=720, gt=0)
    fps: int = Field(default=30, gt=0)
    formats: list[Literal["mp4", "png"]] = Field(default_factory=lambda: ["mp4"])
    path: str = "./output/video.mp4"
    quality: int = Field(default=22, ge=0, le=51, description="CRF value for x264/x265 (lower = better)")

    @field_validator("formats")
    @classmethod
    def at_least_one_format(cls, v: list) -> list:
        if not v:
            raise ValueError("output.formats must contain at least one format")
        return v


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

class ThemeConfig(BaseModel):
    palette: str = "neon"
    background: str = "#0d0d1a"
    grade: str | None = None
    font: str = "default"
    font_size: int = Field(default=36, gt=0)
    text_color: str = "#ffffff"


# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------

class CSVDataSource(BaseModel):
    type: Literal["csv"]
    path: str | None = None
    url: str | None = None
    delimiter: str = ","
    encoding: str = "utf-8"
    header: int | None = 0

    @model_validator(mode="after")
    def path_or_url(self) -> "CSVDataSource":
        if not self.path and not self.url:
            raise ValueError("csv data source requires 'path' or 'url'")
        return self


class JSONDataSource(BaseModel):
    type: Literal["json"]
    path: str | None = None
    url: str | None = None
    jmespath: str | None = None

    @model_validator(mode="after")
    def path_or_url(self) -> "JSONDataSource":
        if not self.path and not self.url:
            raise ValueError("json data source requires 'path' or 'url'")
        return self


class ExcelDataSource(BaseModel):
    type: Literal["excel"]
    path: str
    sheet: str | int = 0
    range: str | None = None


class SQLDataSource(BaseModel):
    type: Literal["sql"]
    connection: str = Field(description="SQLAlchemy connection string, e.g. sqlite:///data.db")
    query: str = Field(description="SQL SELECT statement or table name")
    params: dict[str, Any] = Field(default_factory=dict)


class APIDataSource(BaseModel):
    type: Literal["api"]
    url: str
    method: Literal["GET", "POST"] = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    auth: dict[str, str] | None = Field(
        default=None,
        description="Auth config, e.g. {'type': 'bearer', 'token': '...'}"
    )
    jmespath: str | None = Field(default=None, description="JMESPath selector applied to response JSON")
    timeout: int = 30


DataSourceConfig = Annotated[
    Union[CSVDataSource, JSONDataSource, ExcelDataSource, SQLDataSource, APIDataSource],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Overlays
# ---------------------------------------------------------------------------

class OverlayTiming(BaseModel):
    start: float = Field(default=0.0, ge=0.0, description="Seconds from segment start")
    end: float | None = Field(default=None, description="Seconds from segment start; None = until segment end")


class TextOverlay(BaseModel):
    type: Literal["text"]
    text: str
    effect: str = "fade_in"
    position: Literal[
        "center", "top", "bottom",
        "top-left", "top-right", "bottom-left", "bottom-right",
    ] = "center"
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    font_size: int | None = None
    color: str | None = None
    bold: bool = False


class WebOverlay(BaseModel):
    type: Literal["web"]
    template: str = Field(description="Path to Jinja2 HTML template or web-overlay preset name")
    css_vars: dict[str, str] = Field(default_factory=dict)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)


OverlayConfig = Annotated[
    Union[TextOverlay, WebOverlay],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------

class TransitionRef(BaseModel):
    type: str = "dissolve_ii"
    duration: float = Field(default=0.5, gt=0.0)


class TransitionOverride(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_segment: str = Field(alias="from", description="Source segment ID")
    to: str = Field(description="Target segment ID")
    type: str
    duration: float = Field(default=0.5, gt=0.0)


class TransitionsBlock(BaseModel):
    default: TransitionRef = Field(default_factory=TransitionRef)
    overrides: list[TransitionOverride] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

class VoiceoverConfig(BaseModel):
    provider: Literal["talk-cast"] = "talk-cast"
    voice: str = "default"
    script: Literal["auto", "manual"] = "auto"
    text: str | None = Field(
        default=None,
        description="Used when script='manual'; ignored for 'auto' (narration taken from segments)"
    )
    speed: float = Field(default=1.0, gt=0.0, le=4.0)
    pitch: float = Field(default=0.0, ge=-20.0, le=20.0)

    @model_validator(mode="after")
    def text_required_for_manual(self) -> "VoiceoverConfig":
        if self.script == "manual" and not self.text:
            raise ValueError("voiceover.text is required when script='manual'")
        return self


class AudioTrack(BaseModel):
    source: str = Field(description="Path or URL to audio file")
    volume: float = Field(default=0.15, ge=0.0, le=1.0)
    timing: str = Field(
        default="throughout",
        description="'throughout', 'intro', 'outro', or a segment ID"
    )
    loop: bool = True
    fade_in: float = Field(default=1.0, ge=0.0)
    fade_out: float = Field(default=1.0, ge=0.0)


class AudioConfig(BaseModel):
    voiceover: VoiceoverConfig | None = None
    tracks: list[AudioTrack] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Base segment (shared fields)
# ---------------------------------------------------------------------------

class BaseSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Unique segment identifier")
    duration: float = Field(gt=0.0, description="Segment duration in seconds")
    label: str | None = None
    narration: str | None = Field(
        default=None,
        description="Narration text for this segment; fed to talk-cast voiceover"
    )
    overlays: list[OverlayConfig] = Field(default_factory=list)
    grade: str | None = Field(
        default=None,
        description="color-fx grade slug; overrides theme.grade for this segment"
    )
    transition_in: TransitionRef | None = None
    transition_out: TransitionRef | None = None


# ---------------------------------------------------------------------------
# Segment types
# ---------------------------------------------------------------------------

class MathvizSegment(BaseSegment):
    """Background generator from mathviz-fx."""
    type: Literal["mathviz"]
    effect: str = Field(
        default="matrix_rain",
        description="Generator name: matrix_rain, kaleidoscope, plasma, voronoi, tunnel, spirograph, ..."
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Passed directly to BackgroundGeneratorFactory.create(effect, config)"
    )


class ChartSegment(BaseSegment):
    """Animated chart from chart-fx."""
    type: Literal["chart"]
    chart_type: Literal[
        "bar", "line", "scatter", "pie", "heatmap",
        "treemap", "sankey", "area", "radar", "bubble",
        "waterfall", "funnel", "gantt", "histogram",
    ] = "bar"
    data: DataRef = Field(
        description="Inline ChartData dict OR '$sources.<id>' reference. "
                    "Dict format: {title, x_categories, series: [{name, values, labels}], y_label}"
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="ChartParams overrides: palette, background_color, enter_duration, hold_duration, ..."
    )


class GeomapSegment(BaseSegment):
    """Choropleth map from geo-map-fx."""
    type: Literal["geomap"]
    view: Literal[
        "regions", "municipalities",
        "region_municipalities", "region_valdistrikt", "municipality_valdistrikt",
    ] = "municipalities"
    scope: str = Field(
        default="sweden",
        description="'sweden' for national, 2-char lan_kod for county, 4-char for municipality"
    )
    data: DataRef = Field(
        description="Dict of area_code -> float OR '$sources.<id>' reference"
    )
    palette: str = "YlOrRd"
    reverse_palette: bool = False
    title: str | None = None
    animation: Literal["ken_burns_zoom", "static"] = "ken_burns_zoom"
    zoom_factor: float = Field(default=0.4, ge=0.0, le=2.0)


class ShapeSegment(BaseSegment):
    """Particle/geometric effect from shape-fx."""
    type: Literal["shape"]
    effect: str = Field(
        default="constellation",
        description="Effect type: constellation, geometric, kinetic, reveal, ambient, ..."
    )
    config: dict[str, Any] = Field(default_factory=dict)


class FractalSegment(BaseSegment):
    """Fractal generator from fractal-fx."""
    type: Literal["fractal"]
    effect: str = Field(default="mandelbrot")
    config: dict[str, Any] = Field(default_factory=dict)


class SlideSegment(BaseSegment):
    """Rendered slide from slide-render / deck-spec."""
    type: Literal["slide"]
    slide_spec: dict[str, Any] | str = Field(
        description="Inline deck-spec dict OR path to a .json deck-spec file"
    )
    motion: Literal["ken_burns", "zoom_in", "zoom_out", "static"] = "static"


class StillSegment(BaseSegment):
    """Animated still image via still-motion."""
    type: Literal["still"]
    source: str = Field(description="Path or URL to source image")
    motion: Literal["ken_burns", "zoom_in", "zoom_out", "pan_left", "pan_right", "static"] = "ken_burns"
    motion_config: dict[str, Any] = Field(default_factory=dict)


class ImageSegment(BaseSegment):
    """Static or lightly animated image."""
    type: Literal["image"]
    source: str = Field(description="Path or URL to image file")
    fit: Literal["cover", "contain", "stretch"] = "cover"
    motion: Literal["ken_burns", "zoom_in", "zoom_out", "pan_left", "pan_right", "static"] = "static"


class VideoSegment(BaseSegment):
    """Passthrough video clip."""
    type: Literal["video"]
    source: str = Field(description="Path to MP4 or other video file")
    start_time: float = Field(default=0.0, ge=0.0)
    loop: bool = False
    mute: bool = False


class BlankSegment(BaseSegment):
    """Solid colour segment."""
    type: Literal["blank"]
    color: str | None = Field(
        default=None,
        description="Hex colour; falls back to theme.background"
    )


# Discriminated union — the 'type' field routes to the correct model
SegmentUnion = Annotated[
    Union[
        MathvizSegment,
        ChartSegment,
        GeomapSegment,
        ShapeSegment,
        FractalSegment,
        SlideSegment,
        StillSegment,
        ImageSegment,
        VideoSegment,
        BlankSegment,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Root spec
# ---------------------------------------------------------------------------

class TVCSSpec(BaseModel):
    """Trollfabriken Video Composition Spec (TVCS) v1."""
    model_config = ConfigDict(extra="forbid")

    tvcs: str = Field(default="1.0", description="Schema version; must be '1.0'")
    meta: MetaConfig = Field(default_factory=MetaConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    theme: ThemeConfig = Field(default_factory=ThemeConfig)
    data_sources: dict[str, DataSourceConfig] = Field(default_factory=dict)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    segments: list[SegmentUnion] = Field(default_factory=list, min_length=1)
    transitions: TransitionsBlock = Field(default_factory=TransitionsBlock)

    @field_validator("tvcs")
    @classmethod
    def version_supported(cls, v: str) -> str:
        if v != "1.0":
            raise ValueError(f"Unsupported TVCS version {v!r}; only '1.0' is supported")
        return v

    @field_validator("segments")
    @classmethod
    def unique_segment_ids(cls, segments: list) -> list:
        seen: set[str] = set()
        for seg in segments:
            if seg.id in seen:
                raise ValueError(f"Duplicate segment id {seg.id!r}")
            seen.add(seg.id)
        return segments
