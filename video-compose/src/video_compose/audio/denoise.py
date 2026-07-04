from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


def denoise_audio(input_path: str | Path, output_path: str | Path) -> Path:
    """Apply spectral noise reduction using noisereduce library."""
    try:
        import noisereduce as nr
        import soundfile as sf
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "noisereduce and soundfile are required — pip install noisereduce soundfile"
        ) from exc

    input_path = Path(input_path)
    output_path = Path(output_path)

    # Convert to WAV first if needed
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_wav = Path(f.name)

    subprocess.run(
        ["ffmpeg", "-y", "-i", str(input_path), "-ar", "44100", "-ac", "1", str(tmp_wav)],
        capture_output=True, check=True,
    )

    data, rate = sf.read(str(tmp_wav))
    reduced = nr.reduce_noise(y=data, sr=rate, stationary=True, prop_decrease=0.85)
    sf.write(str(tmp_wav), reduced, rate)

    # Re-encode to original container
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(tmp_wav), "-c:a", "aac", "-b:a", "192k", str(output_path)],
        capture_output=True, check=True,
    )
    tmp_wav.unlink(missing_ok=True)
    return output_path


def denoise_video_audio(input_path: str | Path, output_path: str | Path) -> Path:
    """Extract audio from video, denoise it, mux back into a new video file."""
    input_path = Path(input_path)
    output_path = Path(output_path)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        audio_raw = tmp / "audio_raw.wav"
        audio_clean = tmp / "audio_clean.aac"

        # Extract audio
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(input_path), "-vn", "-ar", "44100", str(audio_raw)],
            capture_output=True, check=True,
        )

        denoise_audio(audio_raw, audio_clean)

        # Mux clean audio back
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-i", str(audio_clean),
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0",
            str(output_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"denoise mux failed: {r.stderr[-300:]}")

    return output_path
