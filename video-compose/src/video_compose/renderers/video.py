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

        smart_crop = bool(getattr(segment, "smart_crop", False))
        if smart_crop:
            try:
                from video_compose.tools.smart_crop import get_face_crop
                scale_vf = get_face_crop(source, width, height)
            except Exception:
                scale_vf = (
                    f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
                )
        else:
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

        # Speed ramp: variable speed via evaluated setpts expression
        speed_ramp = getattr(segment, "speed_ramp", None)
        if speed_ramp and len(speed_ramp) >= 2:
            pts_expr = _build_speed_ramp_expr(speed_ramp, duration)
            vf_parts.append(f"setpts={pts_expr}")
        elif speed != 1.0:
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

        # Silence removal — pre-process source before main encode
        remove_silence = bool(getattr(segment, "remove_silence", False))
        if remove_silence:
            import tempfile as _tf
            noise_db = float(getattr(segment, "silence_threshold_db", -35.0))
            min_dur = float(getattr(segment, "silence_min_duration", 0.5))
            from video_compose.audio.silence import remove_silence as _rm_silence
            tmp_cleaned = Path(_tf.mktemp(suffix=".mp4"))
            try:
                _rm_silence(source, tmp_cleaned, noise_db, min_dur)
                source = tmp_cleaned
            except Exception:
                pass

        # Stabilization — two-pass vidstab
        stabilize = bool(getattr(segment, "stabilize", False))
        if stabilize:
            output_path = _stabilize(source, output_path, int(getattr(segment, "stabilize_smoothing", 10)), vf, codec_params(crf=20), audio_args)
        else:
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

        if remove_silence and source != Path(segment.source):
            source.unlink(missing_ok=True)

        return output_path


def _stabilize(source: Path, output: Path, smoothing: int, vf: str, codec: list, audio: list) -> Path:
    import tempfile as _tf
    transforms = Path(_tf.mktemp(suffix=".trf"))
    # Pass 1: detect
    r1 = subprocess.run([
        "ffmpeg", "-y", "-i", str(source),
        "-vf", f"vidstabdetect=shakiness=5:accuracy=9:result={transforms}",
        "-f", "null", "-",
    ], capture_output=True, text=True)
    if r1.returncode != 0 or not transforms.exists():
        import logging
        logging.getLogger(__name__).warning("vidstab pass 1 failed (libvidstab not compiled in?): %s", r1.stderr[-200:])
        # Fall back to unstabilized encode
        cmd = ["ffmpeg", "-y", "-i", str(source), "-vf", vf, *codec, *audio, str(output)]
        subprocess.run(cmd, capture_output=True)
        return output
    # Pass 2: transform
    stab_vf = f"vidstabtransform=input={transforms}:smoothing={smoothing}:crop=black,{vf}"
    r2 = subprocess.run([
        "ffmpeg", "-y", "-i", str(source), "-vf", stab_vf, *codec, *audio, str(output),
    ], capture_output=True, text=True)
    transforms.unlink(missing_ok=True)
    if r2.returncode != 0:
        raise RuntimeError(f"vidstab pass 2 failed: {r2.stderr[-300:]}")
    return output


def _build_speed_ramp_expr(ramp: list[dict], total_dur: float) -> str:
    """Build a ffmpeg setpts expression that linearly interpolates speed between keypoints."""
    # ramp = [{time: t, speed: s}, ...] sorted by time
    pts = sorted(ramp, key=lambda k: k.get("time", 0.0))
    if len(pts) < 2:
        s = float(pts[0].get("speed", 1.0))
        return f"{1.0/s}*PTS"

    # Build piecewise: for each segment between keypoints, calc accumulated PTS offset
    # Use ffmpeg's if()/between() expression for each segment
    # Simpler approach: use a single polynomial approximation via linear interpolation of 1/speed
    # ffmpeg doesn't support loops, so build explicit if-else chain
    expr_parts = []
    for i in range(len(pts) - 1):
        t0, s0 = float(pts[i]["time"]), float(pts[i]["speed"])
        t1, s1 = float(pts[i + 1]["time"]), float(pts[i + 1]["speed"])
        # Linear interpolation of 1/speed over the segment
        inv0 = 1.0 / max(s0, 0.01)
        inv1 = 1.0 / max(s1, 0.01)
        alpha = f"(T-{t0})/({t1}-{t0})"
        inv_speed = f"({inv0}+({inv1}-{inv0})*{alpha})"
        expr_parts.append(f"if(between(T,{t0},{t1}),{inv_speed}*PTS)")

    # After last keypoint: use final speed
    last_inv = 1.0 / max(float(pts[-1]["speed"]), 0.01)
    expr_parts.append(f"{last_inv}*PTS")

    return "if(" + ",if(".join(expr_parts[:-1]) + "," + expr_parts[-1] + ")" * (len(expr_parts) - 1)


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
