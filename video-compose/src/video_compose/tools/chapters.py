from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from video_compose.audio.transcription import TranscriptResult


@dataclass
class Chapter:
    start_sec: float
    title: str

    def youtube_line(self) -> str:
        m = int(self.start_sec // 60)
        s = int(self.start_sec % 60)
        return f"{m}:{s:02d} {self.title}"

    def ffmeta_block(self, end_sec: float) -> str:
        return (
            f"[CHAPTER]\n"
            f"TIMEBASE=1/1000\n"
            f"START={int(self.start_sec * 1000)}\n"
            f"END={int(end_sec * 1000)}\n"
            f"title={self.title}\n"
        )


def generate_chapters(
    transcript: TranscriptResult,
    total_duration: float,
    model: str = "gpt-4o-mini",
) -> list[Chapter]:
    """Use LLM to identify topic-change timestamps and generate chapter titles."""
    from auth_api_key import get_key
    import openai

    client = openai.OpenAI(api_key=get_key("OPENAI_API_KEY"))
    system = (
        "You are a video editor. Given a transcript with timestamps, identify "
        "major topic changes and assign concise chapter titles (3-6 words). "
        "Return JSON array: [{\"start_sec\": 0.0, \"title\": \"Introduction\"}, ...]. "
        "Always start at 0. Maximum 10 chapters. Titles must be plain text."
    )
    # Build condensed transcript with timestamps
    condensed = " ".join(
        f"[{w.start:.1f}s] {w.word}" for w in transcript.words[::3]
    ) if transcript.words else transcript.text

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Transcript:\n{condensed[:4000]}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    raw = response.choices[0].message.content or "{}"
    data = json.loads(raw)
    items = data if isinstance(data, list) else data.get("chapters", data.get("items", []))
    return [Chapter(float(c["start_sec"]), str(c["title"])) for c in items]


def export_chapters(
    chapters: list[Chapter],
    total_duration: float,
    output_dir: Path,
    stem: str = "output",
) -> dict[str, Path]:
    """Write YouTube .txt and FFMETADATA .ini chapter files. Returns dict of paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    yt_path = output_dir / f"{stem}_chapters.txt"
    yt_lines = [c.youtube_line() for c in chapters]
    yt_path.write_text("\n".join(yt_lines), encoding="utf-8")

    meta_path = output_dir / f"{stem}_chapters.ffmeta"
    meta_lines = [";FFMETADATA1\n"]
    for i, ch in enumerate(chapters):
        end = chapters[i + 1].start_sec if i + 1 < len(chapters) else total_duration
        meta_lines.append(ch.ffmeta_block(end))
    meta_path.write_text("\n".join(meta_lines), encoding="utf-8")

    return {"youtube": yt_path, "ffmeta": meta_path}


def embed_chapters_in_mp4(mp4_path: Path, ffmeta_path: Path, output_path: Path) -> Path:
    """Mux chapter metadata into an MP4 file."""
    import subprocess
    cmd = [
        "ffmpeg", "-y",
        "-i", str(mp4_path),
        "-i", str(ffmeta_path),
        "-map_metadata", "1",
        "-codec", "copy",
        str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"chapter embed failed: {r.stderr[-300:]}")
    return output_path
