from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import SubtitleConfig

logger = logging.getLogger(__name__)


def apply_subtitles(
    video_path: Path,
    config: "SubtitleConfig",
    work_dir: Path,
    output_path: Path,
) -> Path:
    """Burn subtitles into *video_path* and write to *output_path*.

    Two modes:
    - "burn": use the provided SRT/VTT/ASS file directly
    - "auto": transcribe audio via OpenAI Whisper API → SRT → burn

    Returns the output path.
    """
    if config.mode == "auto":
        srt_path = _transcribe(video_path, config, work_dir)
    else:
        srt_path = Path(config.captions_path)
        if not srt_path.exists():
            raise FileNotFoundError(f"Subtitles captions_path not found: {srt_path}")

    return _burn(video_path, srt_path, config, output_path)


def _transcribe(video_path: Path, config: "SubtitleConfig", work_dir: Path) -> Path:
    """Extract audio from video, transcribe via OpenAI Whisper API, return SRT path."""
    audio_path = work_dir / "subtitle_audio.mp3"
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1", "-ab", "64k",
        str(audio_path),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"Subtitle audio extraction failed: {r.stderr[-300:]}")

    from auth_api_key import get_key
    import openai

    client = openai.OpenAI(api_key=get_key("OPENAI_API_KEY"))

    with open(audio_path, "rb") as f:
        kwargs: dict = {
            "model": config.model,
            "file": f,
            "response_format": "srt",
        }
        if config.language != "auto":
            kwargs["language"] = config.language
        srt_text = client.audio.transcriptions.create(**kwargs)

    srt_path = work_dir / "subtitles.srt"
    srt_path.write_text(str(srt_text), encoding="utf-8")
    logger.info("Whisper transcription complete → %s", srt_path)
    return srt_path


def _burn(video_path: Path, srt_path: Path, config: "SubtitleConfig", output_path: Path) -> Path:
    """Burn subtitle file into video using ffmpeg subtitles/ass filter."""
    style = config.style

    # Alignment: 2=bottom-center, 8=top-center, 5=mid-center (ASS numpad layout)
    alignment_map = {"bottom": 2, "top": 8, "center": 5}
    alignment = alignment_map.get(style.position, 2)

    # Convert hex color to ASS BGR format (&H00BBGGRR)
    def hex_to_ass(h: str) -> str:
        h = h.lstrip("#")
        if len(h) == 8:
            # with alpha — ASS stores as &HAABBGGRR
            a = int(h[6:8], 16)
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"&H00{b:02X}{g:02X}{r:02X}"

    primary = hex_to_ass(style.color)
    outline_c = hex_to_ass(style.outline_color)
    shadow_c = hex_to_ass(style.shadow_color)
    back_c = hex_to_ass(style.box_color) if style.box else "&H00000000"

    border_style = 4 if style.box else 1  # 4=opaque box, 1=outline+shadow
    shadow_val = 2 if style.shadow else 0

    force_style = (
        f"FontName={style.font_family}"
        f",FontSize={style.font_size}"
        f",PrimaryColour={primary}"
        f",OutlineColour={outline_c}"
        f",BackColour={back_c}"
        f",Outline={style.outline_width}"
        f",Shadow={shadow_val}"
        f",ShadowColour={shadow_c}"
        f",BorderStyle={border_style}"
        f",Alignment={alignment}"
    )
    if style.uppercase:
        force_style += ",AllCaps=1"

    # Escape Windows path backslashes and colons for ffmpeg filter syntax
    srt_escaped = str(srt_path).replace("\\", "/").replace(":", "\\:")

    suffix = srt_path.suffix.lower()
    if suffix == ".ass":
        sub_filter = f"ass='{srt_escaped}'"
    else:
        sub_filter = f"subtitles='{srt_escaped}':force_style='{force_style}'"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", sub_filter,
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-c:a", "copy",
        str(output_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Subtitle burn-in failed: {r.stderr[-500:]}")

    logger.info("Subtitles burned → %s", output_path)
    return output_path
