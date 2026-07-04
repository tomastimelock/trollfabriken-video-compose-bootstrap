from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from video_compose.audio.transcription import TranscriptResult, WordTiming


@dataclass
class HighlightClip:
    start: float
    end: float
    score: float
    reason: str = ""


def extract_highlights(
    video_path: str | Path,
    transcript: TranscriptResult,
    target_duration: float = 60.0,
    model: str = "gpt-4o-mini",
) -> list[HighlightClip]:
    """Score transcript segments by energy + speech density + LLM engagement.

    Returns list of (start, end) clips whose total duration ≈ target_duration.
    """
    video_path = Path(video_path)

    # Build 5-second windows
    words = transcript.words
    if not words:
        return []

    total = words[-1].end
    window = 5.0
    windows: list[dict] = []
    t = 0.0
    while t < total:
        w_end = min(t + window, total)
        chunk = [w for w in words if t <= w.start < w_end]
        density = len(chunk) / window
        text = " ".join(w.word for w in chunk)
        windows.append({"start": t, "end": w_end, "density": density, "text": text})
        t = w_end

    # LLM engagement scoring
    llm_scores = _llm_score(windows, model)

    clips: list[HighlightClip] = []
    for i, win in enumerate(windows):
        score = win["density"] * 0.4 + llm_scores.get(i, 0.5) * 0.6
        clips.append(HighlightClip(win["start"], win["end"], score))

    # Greedily select top clips up to target_duration
    clips.sort(key=lambda c: c.score, reverse=True)
    selected: list[HighlightClip] = []
    total_selected = 0.0
    for clip in clips:
        dur = clip.end - clip.start
        if total_selected + dur > target_duration * 1.1:
            continue
        selected.append(clip)
        total_selected += dur
        if total_selected >= target_duration:
            break

    return sorted(selected, key=lambda c: c.start)


def render_highlight_reel(
    video_path: str | Path,
    clips: list[HighlightClip],
    output_path: str | Path,
) -> Path:
    """Concatenate highlight clips into a single video using ffmpeg concat demuxer."""
    video_path = Path(video_path)
    output_path = Path(output_path)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        concat_path = Path(f.name)
        for clip in clips:
            f.write(f"file '{video_path.as_posix()}'\n")
            f.write(f"inpoint {clip.start:.3f}\n")
            f.write(f"outpoint {clip.end:.3f}\n")

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path),
           "-c", "copy", str(output_path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    concat_path.unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError(f"highlight concat failed: {r.stderr[-400:]}")
    return output_path


def _llm_score(windows: list[dict], model: str) -> dict[int, float]:
    try:
        from auth_api_key import get_key
        import openai
    except ImportError:
        return {}

    client = openai.OpenAI(api_key=get_key("OPENAI_API_KEY"))
    segments = [{"i": i, "text": w["text"][:120]} for i, w in enumerate(windows)]
    system = (
        "Rate each video segment for viewer engagement (0.0–1.0). "
        "Return JSON: {\"scores\": {\"0\": 0.7, \"1\": 0.3, ...}}. "
        "High score = surprising, emotional, or information-dense content."
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(segments)[:3000]},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        data = json.loads(response.choices[0].message.content or "{}")
        raw = data.get("scores", {})
        return {int(k): float(v) for k, v in raw.items()}
    except Exception:
        return {}
