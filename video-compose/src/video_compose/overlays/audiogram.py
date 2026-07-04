from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import AudiogramOverlay

_POSITION_MAP = {
    "center":       ("(W-w)/2", "(H-h)/2"),
    "top":          ("(W-w)/2", "0"),
    "bottom":       ("(W-w)/2", "H-h"),
    "top-left":     ("0", "0"),
    "top-right":    ("W-w", "0"),
    "bottom-left":  ("0", "H-h"),
    "bottom-right": ("W-w", "H-h"),
}


def _extract_audio(video_path: Path, audio_path: Path) -> bool:
    """Extract audio track from a video to a WAV file. Returns True on success."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "44100", "-ac", "1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0


def render_audiogram_overlay(
    ov: "AudiogramOverlay",
    clip_path: Path,
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    work_dir: Path,
    index: int,
) -> dict:
    """Render an AudiogramOverlay: extract audio → showwaves/showfreqs → composite layer dict."""
    start = ov.timing.start
    end = ov.timing.end if ov.timing.end is not None else segment_duration
    dur = end - start

    ov_w = max(1, int(width * ov.width_pct / 100))
    ov_h = max(1, int(height * ov.height_pct / 100))

    # Determine audio source
    if ov.audio_source:
        audio_path = Path(ov.audio_source)
        extracted = False
    else:
        audio_path = work_dir / f"audiogram_audio_{index}.wav"
        extracted = _extract_audio(clip_path, audio_path)
        if not extracted:
            raise RuntimeError(
                f"AudiogramOverlay #{index}: could not extract audio from {clip_path}. "
                "Set audio_source to an explicit audio file path."
            )

    color_hex = ov.color.lstrip("#")
    amplitude = ov.amplitude

    out = work_dir / f"audiogram_overlay_{index}.webm"

    # Build the appropriate filter based on style
    if ov.style == "bars":
        # showfreqs renders frequency-domain bars (Spotify-style)
        wav_filter = (
            f"showfreqs=s={ov_w}x{ov_h}:mode=bar:ascale=log:fscale=log"
            f":colors=0x{color_hex}:win_func=hann"
        )
    elif ov.style == "waveform":
        # showwaves p2p mode — oscilloscope style
        wav_filter = (
            f"showwaves=s={ov_w}x{ov_h}:mode=p2p:scale={amplitude / 5.0:.2f}"
            f":colors=0x{color_hex}FF"
        )
    else:  # "line"
        wav_filter = (
            f"showwaves=s={ov_w}x{ov_h}:mode=line:scale={amplitude / 5.0:.2f}"
            f":colors=0x{color_hex}FF"
        )

    # Apply opacity and output with alpha
    post = f"colorchannelmixer=aa={ov.opacity},format=yuva420p"

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-t", str(dur),
        "-i", str(audio_path),
        "-filter_complex", f"[0:a]{wav_filter}[v];[v]{post}[out]",
        "-map", "[out]",
        "-r", str(int(fps)),
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20",
        "-an",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"AudiogramOverlay ffmpeg failed: {result.stderr[-500:]}")

    # Position
    if ov.x_pct is not None and ov.y_pct is not None:
        x = str(int(width * ov.x_pct / 100))
        y = str(int(height * ov.y_pct / 100))
    else:
        x_expr, y_expr = _POSITION_MAP.get(ov.position, _POSITION_MAP["bottom"])
        # Substitute W/H/w/h with actual pixel values for the overlay filter
        x = x_expr.replace("W", str(width)).replace("w", str(ov_w))
        y = y_expr.replace("H", str(height)).replace("h", str(ov_h))

    return {"path": out, "x": x, "y": y, "start": start, "end": end,
            "keyframes": None, "z_order": ov.z_order, "_is_audiogram": True}
