from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WordTiming:
    word: str
    start: float
    end: float


@dataclass
class TranscriptResult:
    text: str
    language: str
    words: list[WordTiming] = field(default_factory=list)
    srt_content: str = ""

    def to_srt(self) -> str:
        return self.srt_content


_CACHE_DIR = Path.home() / ".video_compose" / "cache" / "transcripts"


def transcribe(
    audio_path: str | Path,
    language: str = "auto",
    model: str = "whisper-1",
    cache: bool = True,
) -> TranscriptResult:
    """Transcribe audio/video using OpenAI Whisper API with word-level timestamps."""
    audio_path = Path(audio_path)

    cache_key = hashlib.sha256(audio_path.read_bytes()).hexdigest()[:20]
    cache_file = _CACHE_DIR / f"{cache_key}.json"

    if cache and cache_file.exists():
        data = json.loads(cache_file.read_text())
        return _from_cache(data)

    try:
        from auth_api_key import get_key
        import openai
    except ImportError as exc:
        raise RuntimeError("openai is required for transcription — pip install openai") from exc

    client = openai.OpenAI(api_key=get_key("OPENAI_API_KEY"))

    # Extract to WAV if video
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "audio.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path), "-ar", "16000", "-ac", "1", str(wav)],
            capture_output=True, check=True,
        )

        kwargs: dict = {"model": model, "response_format": "verbose_json",
                        "timestamp_granularities": ["word"]}
        if language != "auto":
            kwargs["language"] = language

        with open(wav, "rb") as f:
            response = client.audio.transcriptions.create(file=f, **kwargs)

    words = [
        WordTiming(w.word.strip(), w.start, w.end)
        for w in (response.words or [])
    ]
    srt = _words_to_srt(words)
    result_data = {
        "text": response.text,
        "language": response.language or language,
        "words": [{"word": w.word, "start": w.start, "end": w.end} for w in words],
        "srt": srt,
    }

    if cache:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(result_data))

    return TranscriptResult(
        text=response.text,
        language=response.language or language,
        words=words,
        srt_content=srt,
    )


def _from_cache(data: dict) -> TranscriptResult:
    words = [WordTiming(w["word"], w["start"], w["end"]) for w in data.get("words", [])]
    return TranscriptResult(
        text=data["text"],
        language=data["language"],
        words=words,
        srt_content=data.get("srt", _words_to_srt(words)),
    )


def _words_to_srt(words: list[WordTiming]) -> str:
    """Group words into ~7-word subtitle cues and format as SRT."""
    if not words:
        return ""

    lines: list[str] = []
    idx = 1
    chunk: list[WordTiming] = []

    def flush():
        nonlocal idx
        if not chunk:
            return
        start = _fmt_ts(chunk[0].start)
        end = _fmt_ts(chunk[-1].end)
        text = " ".join(w.word for w in chunk)
        lines.append(f"{idx}\n{start} --> {end}\n{text}\n")
        idx += 1
        chunk.clear()

    for w in words:
        chunk.append(w)
        if len(chunk) >= 7:
            flush()
    flush()
    return "\n".join(lines)


def _fmt_ts(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
