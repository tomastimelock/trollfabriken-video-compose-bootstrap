from __future__ import annotations

from pathlib import Path
from typing import Any

from video_compose.renderers.base import BaseRenderer, frames_to_mp4


class ChartRenderer(BaseRenderer):
    """Renders a ChartSegment using chart-fx render_chart."""

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
            from chart_fx.api import render_chart
        except ImportError as exc:
            raise RuntimeError(
                "chart-fx is required for chart segments — pip install video-compose[chart]"
            ) from exc

        # data may be a DataFrame, dict, or list — chart-fx expects a ChartData-compatible dict
        if hasattr(data, "to_dict"):
            # pandas DataFrame: convert to {x_categories, series: [{name, values}]}
            df = data
            cols = list(df.columns)
            x_categories = [str(v) for v in df[cols[0]].tolist()]
            series = [
                {"name": col, "values": df[col].tolist()}
                for col in cols[1:]
            ]
            chart_data = {"x_categories": x_categories, "series": series}
        elif isinstance(data, dict):
            chart_data = data
        else:
            chart_data = {"series": [{"name": "data", "values": list(data or [])}]}

        params = dict(segment.config)
        params.setdefault("enter_duration", min(segment.duration * 0.4, 1.5))
        params.setdefault("hold_duration", segment.duration - params["enter_duration"])

        frames = render_chart(
            chart_type=segment.chart_type,
            data=chart_data,
            params=params or None,
            width=width,
            height=height,
            fps=int(fps),
        )

        output_path = Path(output_path)
        frames_to_mp4(frames, output_path, fps)
        return output_path
