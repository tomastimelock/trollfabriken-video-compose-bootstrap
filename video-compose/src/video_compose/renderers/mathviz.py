from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from video_compose._codec import codec_params
from video_compose.renderers.base import BaseRenderer

# Color schemes that render at near-full saturation and need aggressive desaturation
_SATURATED_SCHEMES: frozenset[str] = frozenset({
    "neon", "rainbow", "fire", "electric", "cyberpunk",
})

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

# Per-effect blur sigma overrides (1.5 is the default).
# Dot-grid effects like starfield need higher blur to soften square pixel artifacts.
_EFFECT_SIGMA: dict[str, float] = {
    "starfield_3d":          2.5,
    "geometric_grid":        2.0,
    "lissajous_curves":      2.0,
    "phyllotaxis_spiral":    2.0,
    "matrix_rain":           0.8,
    "waveform_oscilloscope": 0.8,
    "perlin_noise":          1.0,
    "noise_flow_field":      1.0,
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


def _apply_cinematic_grade(
    src: Path, dst: Path, *, saturation: float = 0.72, sigma: float = 1.5
) -> None:
    """Post-process mathviz output: adaptive blur + softer vignette + desaturation.

    Adaptive sigma: starfield/geometric effects get higher blur (2.5) to soften
    square pixel dot artifacts; oscilloscope/noise keep it low (0.8–1.0) to
    preserve line sharpness. Vignette uses PI/4.5 (≈0.70 rad) for a softer,
    more cinematic look than the previous PI/3.5 (≈0.90 rad).
    Loop crossfade: fade=in:d=0.3 ensures the animation opens smoothly; the
    tail naturally cuts back to the loop point in the compositor.
    """
    vf = (
        f"gblur=sigma={sigma:.2f},"
        f"eq=brightness=-0.03:contrast=1.05:saturation={saturation:.3f},"
        "vignette=PI/4.5:eval=frame,"
        "fade=in:st=0:d=0.3"
    )
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-vf", vf,
        *codec_params(crf=18, profile="high"),
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        import shutil
        shutil.copy2(src, dst)


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

        saturation = 0.32 if color_scheme in _SATURATED_SCHEMES else 0.72
        sigma = _EFFECT_SIGMA.get(effect, 1.5)

        with tempfile.TemporaryDirectory() as td:
            raw_path = Path(td) / "mathviz_raw.mp4"
            scene = BackgroundScene(spec)
            scene.render_to_video(str(raw_path))
            _apply_cinematic_grade(raw_path, output_path, saturation=saturation, sigma=sigma)

        return output_path
