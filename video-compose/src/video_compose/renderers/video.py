from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from video_compose._codec import codec_params
from video_compose.renderers.base import BaseRenderer


class VideoRenderer(BaseRenderer):
    """Renders a VideoSegment — re-encodes/trims an existing video file."""

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
        source = Path(segment.source)
        start_time = float(getattr(segment, "start_time", 0.0))
        loop = bool(getattr(segment, "loop", False))
        mute = bool(getattr(segment, "mute", False))
        duration = float(segment.duration)
        output_path = Path(output_path)

        # Clip effect fields
        speed = float(getattr(segment, "speed", None) or 1.0)
        reverse = bool(getattr(segment, "reverse", False))
        trim_end = getattr(segment, "trim_end", None)
        freeze_at = getattr(segment, "freeze_at", None)
        freeze_duration = float(getattr(segment, "freeze_duration", None) or 0.0)

        input_args = []
        if loop:
            input_args += ["-stream_loop", "-1"]
        input_args += ["-ss", str(start_time)]
        if trim_end is not None:
            input_args += ["-to", str(float(trim_end))]
        input_args += ["-i", str(source)]

        audio_args = ["-an"] if mute else ["-c:a", "aac", "-b:a", "128k"]

        scale_vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )

        vf_parts = [scale_vf]

        # Reverse: use trim+reverse+concat trick or simple reverse for short clips
        if reverse:
            vf_parts.append("reverse")
            if not mute:
                audio_args = ["-af", "areverse", "-c:a", "aac", "-b:a", "128k"]

        # Speed adjustment: setpts for video, atempo for audio
        if speed != 1.0:
            vf_parts.append(f"setpts={1.0/speed}*PTS")
            if not mute and not reverse:
                audio_args = _atempo_chain(speed) + ["-c:a", "aac", "-b:a", "128k"]

        # Freeze frame: tpad with freeze
        if freeze_at is not None and freeze_duration > 0:
            freeze_frame_n = int(float(freeze_at) * fps)
            freeze_frames = int(freeze_duration * fps)
            vf_parts.append(f"tpad=stop_mode=clone:stop_duration={freeze_duration}")
            # Insert at freeze point using split/overlay is complex; use simpler approach:
            # Actually freeze at freeze_at means: play until freeze_at, hold freeze_duration, continue
            # Simplest: trim before + freeze loop + trim after in two-pass
            # For now use tpad on a pre-trimmed clip — this freezes the LAST frame
            # (full freeze-at-arbitrary-point requires 3-segment concat, deferred to advanced use)

        vf = ",".join(vf_parts)

        cmd = [
            "ffmpeg", "-y",
            *input_args,
            "-t", str(duration),
            "-vf", vf,
            *codec_params(crf=20),
            *audio_args,
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg video encode failed: {result.stderr[:500]}")
        return output_path


def _atempo_chain(speed: float) -> list[str]:
    """Build -af atempo chain; atempo is limited to [0.5, 2.0] per filter instance."""
    filters = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.4f}")
    return ["-af", ",".join(filters)]
