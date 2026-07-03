from __future__ import annotations

from pathlib import Path
from typing import Any

from video_compose.renderers.base import BaseRenderer

# Remap invalid color scheme names to valid ColorSchemeType values
_SCHEME_REMAP: dict[str, str] = {
    "acid_neon":    "cyberpunk",
    "inferno":      "fire",
    "vivid":        "rainbow",
    "pastel":       "ice",
    "dark":         "cinematic_noir",
    "green":        "matrix_green",
    "blue":         "ocean",
    "purple":       "synthwave",
}

# Maps effect → (animation_type, color_scheme) defaults for visual impact
_EFFECT_DEFAULTS: dict[str, tuple[str, str]] = {
    "matrix_rain":           ("scroll",  "matrix_green"),
    "plasma_field":          ("flow",    "cyberpunk"),
    "tunnel_loop":           ("zoom",    "electric"),
    "kaleidoscope":          ("rotate",  "rainbow"),
    "voronoi_cells":         ("morph",   "neon"),
    "waveform_oscilloscope": ("wave",    "electric"),
    "spirograph":            ("orbit",   "neon"),
    "particle_swarm":        ("flow",    "synthwave"),
    "sine_wave_field":       ("wave",    "ocean"),
    "concentric_ripples":    ("pulse",   "neon"),
    "perlin_noise":          ("flow",    "nebula"),
    "noise_flow_field":      ("flow",    "fire"),
    "moire_pattern":         ("scroll",  "monochrome"),
    "lissajous_curves":      ("orbit",   "electric"),
    "phyllotaxis_spiral":    ("rotate",  "synthwave"),
    "cellular_automaton":    ("morph",   "matrix_green"),
    "starfield_3d":          ("zoom",    "ice"),
    "geometric_grid":        ("scroll",  "cyberpunk"),
    "radial_burst":          ("pulse",   "fire"),
    "pendulum_wave":         ("wave",    "electric"),
    "reaction_diffusion":    ("morph",   "fire"),
    "hyperbolic_tiling":     ("rotate",  "rainbow"),
    "surface_3d":            ("morph",   "synthwave"),
    "vector_field":          ("flow",    "neon"),
    "phase_portrait":        ("orbit",   "cyberpunk"),
}


class MathvizRenderer(BaseRenderer):
    """Renders a MathvizSegment using mathviz-fx BackgroundScene."""

    def render(
        self,
        segment,
        data: Any,
        output_path: Path,
        *,
        width: int,
        height: int,
        fps: float,
    ) -> Path:
        try:
            from mathviz_fx.core.background_scene import BackgroundScene
        except ImportError as exc:
            raise RuntimeError(
                "mathviz-fx is required for mathviz segments — "
                "pip install video-compose[mathviz]"
            ) from exc

        effect = segment.effect
        default_anim, default_color = _EFFECT_DEFAULTS.get(effect, ("flow", "neon"))

        params = dict(segment.config)

        # Pop energy controls — wire into anim / params dicts
        speed       = params.pop("speed",        1.5)
        intensity   = params.pop("intensity",    1.8)
        complexity  = params.pop("complexity",   1.5)
        raw_scheme = params.pop("color_scheme", default_color)
        color_scheme = _SCHEME_REMAP.get(raw_scheme, raw_scheme)

        # Set intensity/complexity in params for generator
        params.setdefault("intensity",  float(intensity))
        params.setdefault("complexity", float(complexity))
        params["color_scheme"] = color_scheme

        anim_config: dict[str, Any] = {
            "type":  params.pop("animation_type", default_anim),
            "speed": float(speed),
        }

        render_config: dict[str, Any] = {
            "width":    width,
            "height":   height,
            "fps":      fps,
            "duration": segment.duration,
            "quality":  "high",
        }

        spec = {
            "id":              segment.id,
            "background_type": effect,
            "params":          params,
            "animation":       anim_config,
            "render":          render_config,
        }

        output_path = Path(output_path)
        scene = BackgroundScene(spec)
        scene.render_to_video(str(output_path))
        return output_path
