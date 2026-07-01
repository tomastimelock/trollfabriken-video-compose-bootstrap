from __future__ import annotations

import subprocess
import tempfile
import os
from pathlib import Path
from typing import Any

from video_compose.renderers.base import BaseRenderer


class GeomapRenderer(BaseRenderer):
    """Renders a GeomapSegment using geo-map-fx render_static + Ken Burns animation."""

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
            from geo_map_fx.api import MapRenderer
            from geo_map_fx.base import MapParams
        except ImportError as exc:
            raise RuntimeError(
                "geo-map-fx is required for geomap segments — pip install video-compose[geomap]"
            ) from exc

        # Resolve data to {area_code: float} dict
        if hasattr(data, "to_dict"):
            df = data
            cols = list(df.columns)
            values = dict(zip(df[cols[0]].astype(str), df[cols[1]].astype(float)))
        elif isinstance(data, dict):
            values = {str(k): float(v) for k, v in data.items()}
        else:
            values = {}

        params = MapParams(
            view=segment.view,
            scope=segment.scope,
            values=values,
            palette=segment.palette,
            reverse_palette=segment.reverse_palette,
            title=segment.title or "",
        )

        # Render to a PNG first
        from geo_map_fx.renderers.static import render_static
        with tempfile.TemporaryDirectory() as td:
            png_path = Path(td) / "map.png"
            render_static(params, output_path=png_path)

            animation = getattr(segment, "animation", "ken_burns_zoom")
            zoom_factor = getattr(segment, "zoom_factor", 0.4)

            if animation == "static":
                # Static: loop the image for duration seconds
                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1", "-framerate", str(fps),
                    "-i", str(png_path),
                    "-t", str(segment.duration),
                    "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                           f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                    str(output_path),
                ]
            else:
                # Ken Burns zoom
                zoom_end = 1.0 + zoom_factor
                total_frames = int(segment.duration * fps)
                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1", "-framerate", str(fps),
                    "-i", str(png_path),
                    "-t", str(segment.duration),
                    "-vf", (
                        f"scale=iw*{zoom_end:.3f}:ih*{zoom_end:.3f},"
                        f"zoompan=z='min(zoom+{zoom_factor/total_frames:.6f},1+{zoom_factor:.3f})':"
                        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                        f"d={total_frames}:s={width}x{height}:fps={fps}"
                    ),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                    str(output_path),
                ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg encode failed: {result.stderr[:500]}")

        return Path(output_path)
