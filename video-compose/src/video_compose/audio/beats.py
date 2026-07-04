from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BeatResult:
    bpm: float
    timestamps: list[float] = field(default_factory=list)


def detect_beats(audio_path: str | Path) -> BeatResult:
    """Return BPM and beat timestamps using librosa."""
    try:
        import librosa
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("librosa is required for beat detection — pip install librosa") from exc

    y, sr = librosa.load(str(audio_path), mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    return BeatResult(bpm=float(tempo), timestamps=beat_times)


def snap_to_beat(duration: float, beat_timestamps: list[float]) -> float:
    """Return the nearest beat timestamp to *duration*."""
    if not beat_timestamps:
        return duration
    return min(beat_timestamps, key=lambda t: abs(t - duration))
