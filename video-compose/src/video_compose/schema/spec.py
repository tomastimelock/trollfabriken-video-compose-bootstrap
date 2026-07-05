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
# Output — resolution presets + async/webhook
# ---------------------------------------------------------------------------

RESOLUTION_PRESETS: dict[str, tuple[int, int]] = {
    "sd": (854, 480),
    "hd": (1280, 720),
    "full-hd": (1920, 1080),
    "4k": (3840, 2160),
    "squared": (1080, 1080),
    "instagram-story": (1080, 1920),
    "tiktok": (1080, 1920),
    "youtube-short": (1080, 1920),
    "twitter-landscape": (1280, 720),
    "facebook-story": (1080, 1920),
    "linkedin-landscape": (1920, 1080),
}


class OutputConfig(BaseModel):
    resolution: str | None = Field(
        default=None,
        description=f"Named preset; overrides width/height. Options: {sorted(RESOLUTION_PRESETS)}"
    )
    width: int = Field(default=1280, gt=0)
    height: int = Field(default=720, gt=0)
    fps: int = Field(default=30, gt=0)
    formats: list[Literal["mp4", "png"]] = Field(default_factory=lambda: ["mp4"])
    path: str = "./output/video.mp4"
    quality: int = Field(default=22, ge=0, le=51, description="CRF value for x264/x265 (lower = better)")
    webhook_url: str | None = Field(
        default=None,
        description="URL that receives a POST with the job result after async render completes"
    )
    async_mode: bool = Field(
        default=False,
        description="Return job ID immediately; render in background thread"
    )
    draft: bool = Field(
        default=False,
        description="Fast low-quality preview: half resolution, CRF 40, ultrafast preset"
    )
    export_gif: bool = Field(default=False, description="Also export an animated GIF alongside the MP4")
    export_webm: bool = Field(default=False, description="Also export a VP9 WebM alongside the MP4")
    gif_fps: int = Field(default=12, ge=1, le=30, description="Frame rate for GIF export")
    gif_width: int = Field(default=640, gt=0, description="Width for GIF export (height auto-scaled)")
    target_size_mb: float | None = Field(default=None, gt=0.0, description="Target output file size in MB; triggers two-pass encode")
    export_chapters: bool = Field(default=False, description="Export chapter markers as YouTube .txt and FFMETADATA .ini")
    social_preset: str | None = Field(
        default=None,
        description="Social platform preset applied at render time: reels, tiktok, shorts, instagram-post, twitter, linkedin, youtube",
    )

    @field_validator("formats")
    @classmethod
    def at_least_one_format(cls, v: list) -> list:
        if not v:
            raise ValueError("output.formats must contain at least one format")
        return v

    @model_validator(mode="after")
    def apply_resolution_preset(self) -> "OutputConfig":
        if self.resolution is not None:
            if self.resolution not in RESOLUTION_PRESETS:
                raise ValueError(
                    f"Unknown resolution preset {self.resolution!r}. "
                    f"Valid presets: {sorted(RESOLUTION_PRESETS)}"
                )
            self.width, self.height = RESOLUTION_PRESETS[self.resolution]
        return self


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
# Overlay primitives — correction, chroma-key, keyframes
# ---------------------------------------------------------------------------

class ColorCorrection(BaseModel):
    """Per-element brightness/contrast/saturation/gamma adjustments (ffmpeg eq filter)."""
    brightness: float = Field(default=0.0, ge=-1.0, le=1.0)
    contrast: float = Field(default=1.0, ge=0.0, le=3.0)
    saturation: float = Field(default=1.0, ge=0.0, le=3.0)
    gamma: float = Field(default=1.0, ge=0.1, le=10.0)


class ChromaKey(BaseModel):
    """Green-screen / chroma-key removal (ffmpeg chromakey filter)."""
    color: str = Field(default="#00ff00", description="Color to key out (hex)")
    similarity: float = Field(default=0.3, ge=0.01, le=1.0, description="How close a color must be to match")
    blend: float = Field(default=0.1, ge=0.0, le=1.0, description="Blend range at key edges")


class Keyframe(BaseModel):
    """Single keyframe for overlay animation. Unset properties hold their previous value."""
    time: float = Field(ge=0.0, description="Seconds from segment start")
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0, description="Canvas X position as %")
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0, description="Canvas Y position as %")
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)
    scale: float | None = Field(default=None, ge=0.0, le=5.0, description="Uniform scale multiplier")
    rotation: float | None = Field(
        default=None, ge=-360.0, le=360.0,
        description="Rotation in degrees; reserved — not yet composited by ffmpeg backend"
    )


# ---------------------------------------------------------------------------
# Overlays
# ---------------------------------------------------------------------------

class OverlayTiming(BaseModel):
    start: float = Field(default=0.0, ge=0.0, description="Seconds from segment start")
    end: float | None = Field(default=None, description="Seconds from segment start; None = until segment end")


_POSITION_LITERALS = Literal[
    "center", "top", "bottom",
    "top-left", "top-right", "bottom-left", "bottom-right",
    "left", "right",
    "lower_third", "lower_third_left", "lower_third_right",
    "lower_third_2",
]


class TextOverlay(BaseModel):
    type: Literal["text"]
    text: str
    effect: str = "fade_in"
    role: Literal["title", "subtitle", "body", "caption", "label"] | None = Field(
        default=None,
        description="Semantic role — drives default font size when font_size is unset"
    )
    position: _POSITION_LITERALS = "center"
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    font_size: int | None = None
    color: str | None = None
    bold: bool = False
    font_family: str = "Inter"
    font_weight: Literal["regular", "medium", "bold", "black"] = "bold"
    stroke_color: str | None = None
    stroke_width: int = Field(default=0, ge=0)
    shadow: bool = True
    shadow_dx: int = Field(default=0, description="Shadow horizontal offset in pixels")
    shadow_dy: int = Field(default=4, description="Shadow vertical offset in pixels")
    shadow_blur: int = Field(default=8, ge=0, description="Shadow blur radius in pixels")
    shadow_opacity: float = Field(default=0.5, ge=0.0, le=1.0, description="Shadow opacity")
    intensity: float = Field(default=1.0, ge=0.0, le=2.0)
    margin_x: int = Field(default=60, ge=0)
    margin_y: int = Field(default=50, ge=0)
    max_width_pct: float | None = Field(
        default=None, ge=1.0, le=100.0,
        description="Max text block width as % of video width; enables word-wrap"
    )
    text_align: Literal["left", "center", "right"] = Field(
        default="center", description="Text alignment within the text block"
    )
    x_pct: float | None = Field(
        default=None, ge=0.0, le=100.0,
        description="Absolute X position as % of canvas width; overrides position preset"
    )
    y_pct: float | None = Field(
        default=None, ge=0.0, le=100.0,
        description="Absolute Y position as % of canvas height; overrides position preset"
    )
    z_order: int = Field(
        default=0,
        description="Stacking order relative to other overlays on this segment; higher = on top"
    )
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    easing: Literal[
        "linear", "ease-in", "ease-out", "ease-in-out",
        "ease-out-cubic", "ease-out-back", "ease-out-elastic",
        "spring", "bounce",
    ] = "ease-out-cubic"
    aa_mode: Literal["none", "supersample"] = "none"
    keyframes: list[Keyframe] | None = Field(
        default=None,
        description="Keyframe animation; overrides x_pct/y_pct/opacity/scale at specified times"
    )
    condition: str | None = Field(
        default=None,
        description="Python expression; overlay is skipped when falsy. Use {{var}} for spec variables"
    )


class BarOverlay(BaseModel):
    """Solid-color background bar or pill — for lower-third backing strips."""
    type: Literal["bar"]
    color: str = Field(default="#000000", description="Fill color (hex)")
    opacity: float = Field(default=0.7, ge=0.0, le=1.0)
    position: Literal[
        "center", "top", "bottom",
        "lower_third", "lower_third_left", "lower_third_right", "lower_third_2",
    ] = "lower_third"
    width_pct: float = Field(default=100.0, ge=1.0, le=100.0, description="Bar width as % of canvas")
    height_pct: float = Field(default=12.0, ge=0.5, le=50.0, description="Bar height as % of canvas")
    border_radius: int = Field(default=0, ge=0, description="Corner radius in pixels; 0=rectangle, >0=pill")
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    keyframes: list[Keyframe] | None = Field(default=None)
    condition: str | None = Field(default=None)


class WebOverlay(BaseModel):
    type: Literal["web"]
    template: str | None = Field(default=None, description="Path to HTML file or web-overlay preset name")
    html_content: str | None = Field(default=None, description="Inline HTML/CSS string; takes priority over template")
    css_vars: dict[str, str] = Field(default_factory=dict)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    condition: str | None = Field(default=None)

    @model_validator(mode="after")
    def require_template_or_content(self) -> "WebOverlay":
        if not self.template and not self.html_content:
            raise ValueError("WebOverlay requires either 'template' or 'html_content'")
        return self


class ImageOverlay(BaseModel):
    """Composite an external image (PNG/JPG/WebP) on top of the segment."""
    type: Literal["image_overlay"]
    src: str = Field(description="Path or URL to image file (PNG, JPG, WebP, GIF)")
    position: _POSITION_LITERALS = "center"
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    width_pct: float | None = Field(default=None, ge=0.1, le=100.0, description="Width as % of canvas; None = natural size")
    height_pct: float | None = Field(default=None, ge=0.1, le=100.0, description="Height as % of canvas; None = maintain aspect")
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_order: int = Field(default=0)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    correction: ColorCorrection | None = None
    chroma_key: ChromaKey | None = None
    keyframes: list[Keyframe] | None = None
    condition: str | None = None
    remove_bg: bool = Field(default=False, description="Remove background from image before compositing (requires rembg)")


class VideoOverlay(BaseModel):
    """Composite an external video clip on top of the segment."""
    type: Literal["video_overlay"]
    src: str = Field(description="Path to video file")
    position: _POSITION_LITERALS = "center"
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    width_pct: float | None = Field(default=None, ge=0.1, le=100.0)
    height_pct: float | None = Field(default=None, ge=0.1, le=100.0)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_order: int = Field(default=0)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    mute: bool = Field(default=False, description="Strip audio from the overlay video")
    loop: bool = Field(default=False, description="Loop the overlay video if shorter than the segment")
    start_time: float = Field(default=0.0, ge=0.0, description="Start offset into the source video")
    trim_end: float | None = Field(default=None, ge=0.0, description="End time in source video")
    speed: float = Field(default=1.0, gt=0.0, le=16.0, description="Playback speed multiplier")
    reverse: bool = Field(default=False, description="Reverse video playback")
    correction: ColorCorrection | None = None
    chroma_key: ChromaKey | None = None
    keyframes: list[Keyframe] | None = None
    condition: str | None = None
    remove_bg: bool = Field(default=False, description="Remove background from video frames before compositing (requires rembg)")
    border_color: str | None = Field(default=None, description="PiP border/outline color (hex). None = no border")
    border_width: int = Field(default=0, ge=0, le=50, description="PiP border width in pixels")


class AudiogramOverlay(BaseModel):
    """Animated audio waveform / frequency visualization."""
    type: Literal["audiogram"]
    style: Literal["bars", "waveform", "line"] = Field(
        default="bars",
        description="bars=frequency spectrum, waveform=oscilloscope, line=smooth waveform"
    )
    color: str = Field(default="#ffffff", description="Waveform color (hex)")
    opacity: float = Field(default=0.85, ge=0.0, le=1.0)
    width_pct: float = Field(default=80.0, ge=1.0, le=100.0)
    height_pct: float = Field(default=15.0, ge=1.0, le=50.0)
    position: Literal["center", "top", "bottom", "top-left", "top-right", "bottom-left", "bottom-right"] = "bottom"
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    amplitude: float = Field(default=5.0, ge=0.1, le=10.0, description="Wave amplitude scale (0.1–10)")
    z_order: int = Field(default=0)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    audio_source: str | None = Field(
        default=None,
        description="Path to audio file to visualize; defaults to the segment's own embedded audio"
    )
    condition: str | None = None


class SvgOverlay(BaseModel):
    """Composite a static or animated SVG (via cairosvg → PNG → alpha channel)."""
    type: Literal["svg"]
    src: str | None = Field(default=None, description="Path to .svg file")
    content: str | None = Field(default=None, description="Inline SVG string (<svg>...</svg>)")
    position: _POSITION_LITERALS = "center"
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    width_pct: float | None = Field(default=None, ge=0.1, le=100.0, description="Scale to % of canvas width")
    height_pct: float | None = Field(default=None, ge=0.1, le=100.0, description="Scale to % of canvas height")
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_order: int = Field(default=0)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    condition: str | None = None

    @model_validator(mode="after")
    def require_src_or_content(self) -> "SvgOverlay":
        if not self.src and not self.content:
            raise ValueError("SvgOverlay requires either 'src' or 'content'")
        return self


class ComponentOverlay(BaseModel):
    """Bundled or user-saved HTML component, parameterised via props."""
    type: Literal["component"]
    name: str = Field(description="Component slug — bundled (e.g. 'lower_third') or user-saved ('user.my_comp')")
    props: dict[str, Any] = Field(default_factory=dict, description="Template variables injected via {{prop_name}}")
    position: _POSITION_LITERALS = Field(
        default="center",
        description="Canvas position; components handle internal layout via CSS — position sets ffmpeg composite point"
    )
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_order: int = Field(default=0)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    condition: str | None = None


class AiSvgOverlay(BaseModel):
    """AI-generated SVG overlay — Claude produces an SVG from a text prompt."""
    type: Literal["ai_svg"]
    prompt: str = Field(description="Natural-language description of the SVG to generate")
    style: str | None = Field(default=None, description="Style hint, e.g. 'neon', 'minimal', 'corporate'")
    model: str = Field(default="claude-opus-4-7", description="Anthropic model for generation")
    position: _POSITION_LITERALS = "center"
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    width_pct: float | None = Field(default=None, ge=0.1, le=100.0)
    height_pct: float | None = Field(default=None, ge=0.1, le=100.0)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_order: int = Field(default=0)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    cache: bool = Field(default=True, description="Cache generated SVG to disk; same prompt reuses cached result")
    condition: str | None = None


class AiHtmlOverlay(BaseModel):
    """AI-generated HTML/CSS overlay — Claude produces a full HTML string from a text prompt."""
    type: Literal["ai_html"]
    prompt: str = Field(description="Natural-language description of the overlay to generate")
    style: str | None = Field(default=None, description="Style hint, e.g. 'glassmorphism', 'neon', 'minimal'")
    model: str = Field(default="claude-opus-4-7", description="Anthropic model for generation")
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_order: int = Field(default=0)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    cache: bool = Field(default=True, description="Cache generated HTML to disk; same prompt reuses cached result")
    condition: str | None = None


class RectangleOverlay(BaseModel):
    """Solid or stroked rectangle (optionally rounded) drawn with PIL."""
    type: Literal["rectangle"]
    color: str = Field(default="#ffffff", description="Fill color (hex); use 'transparent' for stroke-only")
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    width_pct: float = Field(default=30.0, ge=0.1, le=100.0, description="Width as % of canvas")
    height_pct: float = Field(default=10.0, ge=0.1, le=100.0, description="Height as % of canvas")
    border_radius: int = Field(default=0, ge=0, description="Corner radius in pixels")
    stroke_color: str | None = Field(default=None, description="Outline color; None = no outline")
    stroke_width: int = Field(default=0, ge=0, description="Outline width in pixels")
    position: _POSITION_LITERALS = "center"
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    z_order: int = Field(default=0)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    keyframes: list[Keyframe] | None = None
    condition: str | None = None


class CircleOverlay(BaseModel):
    """Solid or stroked circle/ellipse drawn with PIL."""
    type: Literal["circle"]
    color: str = Field(default="#ffffff", description="Fill color")
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    radius_pct: float = Field(default=10.0, ge=0.1, le=50.0, description="Radius as % of canvas width")
    aspect: float = Field(default=1.0, gt=0.0, description="width/height ratio; 1.0=circle, <1=tall ellipse")
    stroke_color: str | None = None
    stroke_width: int = Field(default=0, ge=0)
    position: _POSITION_LITERALS = "center"
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    z_order: int = Field(default=0)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    keyframes: list[Keyframe] | None = None
    condition: str | None = None


class LineOverlay(BaseModel):
    """Straight line drawn with PIL."""
    type: Literal["line"]
    color: str = Field(default="#ffffff")
    width: int = Field(default=2, ge=1, description="Line width in pixels")
    x1_pct: float = Field(default=10.0, ge=0.0, le=100.0, description="Start X as % of canvas width")
    y1_pct: float = Field(default=50.0, ge=0.0, le=100.0, description="Start Y as % of canvas height")
    x2_pct: float = Field(default=90.0, ge=0.0, le=100.0, description="End X as % of canvas width")
    y2_pct: float = Field(default=50.0, ge=0.0, le=100.0, description="End Y as % of canvas height")
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_order: int = Field(default=0)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    condition: str | None = None


class ArrowOverlay(BaseModel):
    """Line with arrowhead(s) drawn with PIL."""
    type: Literal["arrow"]
    color: str = Field(default="#ffffff")
    width: int = Field(default=2, ge=1)
    x1_pct: float = Field(default=10.0, ge=0.0, le=100.0)
    y1_pct: float = Field(default=50.0, ge=0.0, le=100.0)
    x2_pct: float = Field(default=90.0, ge=0.0, le=100.0)
    y2_pct: float = Field(default=50.0, ge=0.0, le=100.0)
    arrowhead_size: int = Field(default=15, ge=4, description="Arrowhead size in pixels")
    double_headed: bool = Field(default=False, description="Add arrowhead at both ends")
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_order: int = Field(default=0)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    condition: str | None = None


class GifOverlay(BaseModel):
    """Animated GIF overlay with proper loop handling via ffmpeg."""
    type: Literal["gif"]
    src: str = Field(description="Path to animated .gif file")
    position: _POSITION_LITERALS = "center"
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    width_pct: float | None = Field(default=None, ge=0.1, le=100.0)
    height_pct: float | None = Field(default=None, ge=0.1, le=100.0)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    loop: bool = Field(default=True, description="Loop the GIF for the overlay duration")
    speed: float = Field(default=1.0, gt=0.0, le=8.0, description="Playback speed multiplier")
    z_order: int = Field(default=0)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    condition: str | None = None


class QrCodeOverlay(BaseModel):
    """QR code generated inline via the qrcode library."""
    type: Literal["qr_code"]
    content: str = Field(description="URL or text to encode in the QR code")
    fg_color: str = Field(default="#000000", description="Module (foreground) color")
    bg_color: str = Field(default="#ffffff", description="Background color; use 'transparent' for no bg")
    size_pct: float = Field(default=20.0, ge=1.0, le=80.0, description="QR code size as % of canvas width")
    error_correction: Literal["L", "M", "Q", "H"] = Field(default="M")
    position: _POSITION_LITERALS = "center"
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_order: int = Field(default=0)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    condition: str | None = None


class LottieOverlay(BaseModel):
    """Lottie JSON animation overlay rendered via lottie-python."""
    type: Literal["lottie"]
    src: str = Field(description="Path to Lottie .json animation file")
    position: _POSITION_LITERALS = "center"
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    width_pct: float = Field(default=30.0, ge=1.0, le=100.0)
    height_pct: float | None = Field(default=None, ge=1.0, le=100.0, description="None = preserve aspect ratio")
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    speed: float = Field(default=1.0, gt=0.0, le=4.0, description="Animation playback speed")
    loop: bool = Field(default=True)
    z_order: int = Field(default=0)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    condition: str | None = None


class WordTiming(BaseModel):
    """Manual timing for a single word in a WordHighlightOverlay."""
    word: str
    start: float = Field(ge=0.0, description="Word start time in seconds (from overlay start)")
    end: float = Field(ge=0.0, description="Word end time in seconds")


class WordHighlightOverlay(BaseModel):
    """Karaoke-style word-by-word text animation — each word lights up in sequence."""
    type: Literal["word_highlight"]
    text: str = Field(description="Full text string to display and animate")
    words: list[WordTiming] | None = Field(
        default=None,
        description="Manual per-word timings; if None, words are distributed evenly across overlay duration"
    )
    highlight_color: str = Field(default="#ffff00", description="Active word color")
    base_color: str = Field(default="rgba(255,255,255,0.45)", description="Inactive word color")
    font_size: int = Field(default=48, gt=0)
    font_family: str = Field(default="Inter")
    bold: bool = True
    bg_color: str | None = Field(default=None, description="Optional semi-transparent background behind text")
    position: _POSITION_LITERALS = "center"
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    max_width_pct: float = Field(default=80.0, ge=10.0, le=100.0)
    z_order: int = Field(default=0)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    condition: str | None = None


class FaceBlurOverlay(BaseModel):
    """Detect faces in the underlying segment video and blur/pixelate them."""
    type: Literal["face_blur"]
    strength: int = Field(default=5, ge=1, le=20, description="Blur kernel size multiplier")
    pixelate: bool = Field(default=False, description="Pixelate instead of Gaussian blur")
    z_order: int = Field(default=500)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    condition: str | None = None


class AutoCaptionOverlay(BaseModel):
    """Transcribe audio from source and render animated kinetic captions frame-by-frame."""
    type: Literal["auto_caption"]
    source: str = Field(description="Path to audio or video file to transcribe")
    style: str = Field(default="karaoke", description="Caption style preset: karaoke, pop, typewriter, shake, glow, slide_up, fade, outline_pulse, color_wave, bold_highlight")
    position: _POSITION_LITERALS = "bottom"
    font_family: str | None = None
    font_size_pct: float = Field(default=5.0, gt=0.0, le=20.0)
    text_color: str = "#ffffff"
    highlight_color: str = "#ffdd00"
    highlight_bg: str | None = None
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_order: int = Field(default=10)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    language: str = "auto"
    condition: str | None = None


class BlurRegionOverlay(BaseModel):
    """Blur or pixelate an arbitrary rectangular region for privacy/redaction."""
    type: Literal["blur_region"]
    x_pct: float = Field(ge=0.0, le=100.0, description="Left edge of region as % of canvas width")
    y_pct: float = Field(ge=0.0, le=100.0, description="Top edge of region as % of canvas height")
    width_pct: float = Field(ge=0.1, le=100.0, description="Region width as % of canvas width")
    height_pct: float = Field(ge=0.1, le=100.0, description="Region height as % of canvas height")
    radius: int = Field(default=20, ge=1, le=100, description="Gaussian blur radius (ignored when pixelate=True)")
    pixelate: bool = Field(default=False, description="Pixelate (mosaic) instead of Gaussian blur")
    z_order: int = Field(default=500)
    timing: OverlayTiming = Field(default_factory=OverlayTiming)
    condition: str | None = None


OverlayConfig = Annotated[
    Union[
        TextOverlay, BarOverlay, WebOverlay,
        ImageOverlay, VideoOverlay, AudiogramOverlay,
        SvgOverlay, ComponentOverlay, AiSvgOverlay, AiHtmlOverlay,
        RectangleOverlay, CircleOverlay, LineOverlay, ArrowOverlay,
        GifOverlay, QrCodeOverlay, LottieOverlay, WordHighlightOverlay,
        FaceBlurOverlay, AutoCaptionOverlay, BlurRegionOverlay,
    ],
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
    duck_music: bool = Field(
        default=False,
        description="Automatically lower music volume when voiceover is playing (sidechain compression)"
    )
    duck_threshold: float = Field(default=0.15, ge=0.0, le=1.0, description="Voiceover RMS level that triggers ducking")
    duck_ratio: float = Field(default=4.0, ge=1.0, le=20.0, description="Music reduction ratio when ducking")
    duck_attack_ms: float = Field(default=200.0, ge=10.0, description="Ducking attack time in milliseconds")
    duck_release_ms: float = Field(default=1000.0, ge=10.0, description="Ducking release time in milliseconds")
    loudnorm_per_segment: bool = Field(default=False, description="Apply EBU R128 loudness normalization to each segment before concat")
    denoise: bool = Field(default=False, description="Apply spectral noise reduction to voiceover audio (requires noisereduce)")
    beat_sync: bool = Field(default=False, description="Snap segment durations to nearest beat boundary of the first music track (requires librosa)")


# ---------------------------------------------------------------------------
# Subtitles
# ---------------------------------------------------------------------------

class SubtitleStyle(BaseModel):
    font_family: str = Field(default="Inter", description="Font name (must be available on system)")
    font_size: int = Field(default=40, gt=0)
    color: str = Field(default="#ffffff", description="Primary text color (hex)")
    outline_color: str = Field(default="#000000", description="Outline/border color (hex)")
    outline_width: int = Field(default=2, ge=0)
    box: bool = Field(default=False, description="Render a background box behind each line")
    box_color: str = Field(default="#000000cc", description="Box fill color (supports alpha via 8-char hex)")
    position: Literal["top", "center", "bottom"] = "bottom"
    max_words_per_line: int = Field(default=7, gt=0)
    uppercase: bool = False
    shadow: bool = True
    shadow_color: str = "#000000"


class SubtitleConfig(BaseModel):
    mode: Literal["burn", "auto"] = Field(
        default="burn",
        description="'burn' = use provided SRT/VTT/ASS file; 'auto' = transcribe via OpenAI Whisper API"
    )
    captions_path: str | None = Field(
        default=None,
        description="SRT/VTT/ASS file path — required when mode='burn'"
    )
    language: str = Field(
        default="auto",
        description="BCP-47 language code (e.g. 'en', 'sv') or 'auto' for Whisper detection"
    )
    model: Literal["whisper-1"] = "whisper-1"
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    translate_to: str | None = Field(default=None, description="BCP-47 language code to translate captions into before burning (e.g. 'sv', 'de', 'fr')")
    check_compliance: bool = Field(default=False, description="Warn on CPS > 17, line > 42 chars, or display < 1s")

    @model_validator(mode="after")
    def captions_required_for_burn(self) -> "SubtitleConfig":
        if self.mode == "burn" and not self.captions_path:
            raise ValueError("subtitles.captions_path is required when mode='burn'")
        return self


# ---------------------------------------------------------------------------
# Base segment (shared fields)
# ---------------------------------------------------------------------------

class SegmentTTSConfig(BaseModel):
    """Per-segment text-to-speech — generates audio and mixes it onto the segment."""
    text: str | None = Field(default=None, description="TTS text; defaults to segment.narration if unset")
    voice: str = Field(default="default")
    provider: Literal["talk-cast"] = "talk-cast"
    start: float = Field(default=0.0, ge=0.0, description="Start offset within the segment in seconds")


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
    condition: str | None = Field(
        default=None,
        description="Python expression; segment is skipped when falsy. Use {{var}} for spec variables"
    )
    iterate: str | None = Field(
        default=None,
        description="$sources.<id> ref or inline list — clones this segment once per item, "
                    "injecting {{item.field}}, {{item_index}}, {{item_total}} into string fields"
    )
    blur: float = Field(
        default=0.0, ge=0.0, le=100.0,
        description="Gaussian blur radius applied to the rendered segment (pixels, 0=off)"
    )
    tts: SegmentTTSConfig | None = Field(
        default=None,
        description="Per-segment TTS; overrides global voiceover config for this segment"
    )


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
    motion_easing: Literal["linear", "ease-in-out", "ease-out-cubic", "ease-out-back"] = "ease-in-out"
    mask: Literal["none", "circle", "ellipse"] = Field(
        default="none",
        description="Shape mask applied after render — 'circle' for headshots, 'ellipse' for portraits"
    )
    mask_outline_color: str = Field(default="#ffffff", description="Outline/ring color around mask")
    mask_outline_width: int = Field(default=4, ge=0, description="Outline width in pixels")
    mask_feather: int = Field(default=8, ge=0, description="Gaussian feather radius on mask edge")
    mask_shadow: bool = Field(default=True, description="Add drop shadow behind masked circle")


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
    start_time: float = Field(default=0.0, ge=0.0, description="Start offset into the source video")
    trim_end: float | None = Field(default=None, ge=0.0, description="End time in source video (None = full clip)")
    loop: bool = False
    mute: bool = False
    speed: float = Field(default=1.0, gt=0.0, le=16.0, description="Playback speed multiplier (2.0=2× fast, 0.5=half speed)")
    reverse: bool = Field(default=False, description="Reverse video playback")
    freeze_at: float | None = Field(default=None, ge=0.0, description="Freeze on frame at this timestamp (seconds from source start)")
    freeze_duration: float = Field(default=1.0, gt=0.0, description="Duration to hold the frozen frame")
    speed_ramp: list[dict] | None = Field(default=None, description="Speed ramp keypoints: [{time: 0.0, speed: 1.0}, {time: 2.0, speed: 3.0}]")
    stabilize: bool = Field(default=False, description="Stabilize shaky footage via libvidstab (two-pass ffmpeg)")
    stabilize_smoothing: int = Field(default=10, ge=1, le=100, description="Stabilization smoothing radius")
    remove_silence: bool = Field(default=False, description="Auto-detect and cut silent sections from source video")
    silence_threshold_db: float = Field(default=-35.0, le=0.0, description="Silence detection threshold in dB")
    silence_min_duration: float = Field(default=0.5, gt=0.0, description="Minimum silence gap to remove (seconds)")
    smart_crop: bool = Field(default=False, description="Use face-detection to keep subject in frame when cropping to target resolution")


class BlankSegment(BaseSegment):
    """Solid colour or gradient segment."""
    type: Literal["blank"]
    color: str | None = Field(
        default=None,
        description="Hex colour; falls back to theme.background"
    )
    bg_style: Literal["gradient_v", "gradient_v_dark", "gradient_d", "radial", "solid", "gradient_anim"] = Field(
        default="gradient_v",
        description="Background style: gradient_v, gradient_v_dark, gradient_d (diagonal), radial, solid, gradient_anim (slow breathing gradient)"
    )


class SplitScreenSegment(BaseSegment):
    """Side-by-side (or top/bottom) compositor — ideal for before/after comparisons."""
    type: Literal["split_screen"]
    source_a: str = Field(description="Path to the left (or top) image or video")
    source_b: str = Field(description="Path to the right (or bottom) image or video")
    split_direction: Literal["horizontal", "vertical"] = Field(
        default="horizontal",
        description="'horizontal' = left/right; 'vertical' = top/bottom",
    )
    label_a: str | None = Field(default=None, description="Label shown on source_a side (e.g. 'BEFORE')")
    label_b: str | None = Field(default=None, description="Label shown on source_b side (e.g. 'AFTER')")
    label_color: str = Field(default="#ffffff", description="Label text colour")
    label_font_size: int = Field(default=48, gt=0)
    divider_color: str = Field(default="#ffffff", description="Colour of the centre divider line")
    divider_width: int = Field(default=4, ge=0, description="Divider line width in pixels; 0 = no divider")


class ScreenshotSegment(BaseSegment):
    """Captures a headless-browser screenshot of a URL and uses it as a scene."""
    type: Literal["screenshot"]
    url: str = Field(description="URL to screenshot")
    wait_ms: int = Field(default=2000, ge=0, description="Wait in ms after page load before capturing")
    full_page: bool = Field(default=False, description="Capture full scrollable page height")
    selector: str | None = Field(default=None, description="CSS selector — wait for element before capture")
    fit: Literal["cover", "contain", "stretch"] = "cover"
    motion: Literal["ken_burns", "zoom_in", "zoom_out", "pan_left", "pan_right", "static"] = "static"


class TTSSegment(BaseSegment):
    """Generate a video segment from text via OpenAI TTS — audio over a background."""
    type: Literal["tts"]
    text: str = Field(description="Text to synthesize")
    voice: str = Field(
        default="alloy",
        description="OpenAI TTS voice: alloy, echo, fable, onyx, nova, shimmer"
    )
    model: Literal["tts-1", "tts-1-hd"] = Field(default="tts-1")
    speed: float = Field(default=1.0, ge=0.25, le=4.0, description="TTS playback speed")
    language: str | None = Field(default=None, description="BCP-47 language hint (e.g. 'en', 'sv')")
    color: str = Field(default="#000000", description="Background color")
    bg_style: Literal[
        "solid", "gradient_v", "gradient_v_dark", "gradient_d", "radial", "gradient_anim"
    ] = Field(default="solid", description="Background visual style")


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
        SplitScreenSegment,
        ScreenshotSegment,
        TTSSegment,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Root spec
# ---------------------------------------------------------------------------

class WatermarkConfig(BaseModel):
    """Global image watermark composited on every segment."""
    src: str = Field(description="Path to watermark image (PNG with alpha recommended)")
    position: _POSITION_LITERALS = Field(default="top-right")
    opacity: float = Field(default=0.3, ge=0.0, le=1.0)
    scale_pct: float = Field(default=10.0, ge=0.5, le=50.0, description="Watermark width as % of canvas")
    x_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    y_pct: float | None = Field(default=None, ge=0.0, le=100.0)


class FontConfig(BaseModel):
    """Custom font to load before rendering (from local path or URL)."""
    name: str = Field(description="Font family name used in text overlays")
    src: str = Field(description="Local .ttf/.otf path or https:// URL")


class TVCSSpec(BaseModel):
    """Trollfabriken Video Composition Spec (TVCS) v1."""
    model_config = ConfigDict(extra="forbid")

    tvcs: str = Field(default="1.0", description="Schema version; must be '1.0'")
    meta: MetaConfig = Field(default_factory=MetaConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    theme: ThemeConfig = Field(default_factory=ThemeConfig)
    variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Movie-level variables usable in condition expressions and {{var}} interpolation"
    )
    data_sources: dict[str, DataSourceConfig] = Field(default_factory=dict)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    fonts: list[FontConfig] = Field(
        default_factory=list,
        description="Custom fonts to load before rendering; referenced by name in text overlays"
    )
    watermark: WatermarkConfig | None = Field(
        default=None,
        description="Global watermark applied to every segment; shorthand for a persistent global ImageOverlay"
    )
    elements: list[OverlayConfig] = Field(
        default_factory=list,
        description="Global overlays rendered on every segment (watermarks, persistent lower-thirds, etc.)"
    )
    subtitles: SubtitleConfig | None = Field(
        default=None,
        description="Movie-level subtitle burn-in (SRT/VTT/ASS) or auto-transcription via Whisper"
    )
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
