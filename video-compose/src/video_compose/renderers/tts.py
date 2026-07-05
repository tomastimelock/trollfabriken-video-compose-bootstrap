from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from video_compose.renderers.base import BaseRenderer


class TTSRenderer(BaseRenderer):
    """Synthesise audio via OpenAI TTS and render it over a background segment."""

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
        output_path = Path(output_path)

        # 1. Call OpenAI TTS API → MP3
        audio_tmp = Path(tempfile.mktemp(suffix=".mp3"))
        try:
            from auth_api_key import get_key
            import openai
            client = openai.OpenAI(api_key=get_key("OPENAI_API_KEY"))
            with client.audio.speech.with_streaming_response.create(
                model=getattr(segment, "model", "tts-1"),
                voice=getattr(segment, "voice", "alloy"),
                input=segment.text,
                speed=float(getattr(segment, "speed", 1.0)),
            ) as response:
                response.stream_to_file(str(audio_tmp))
        except Exception as exc:
            audio_tmp.unlink(missing_ok=True)
            raise RuntimeError(f"OpenAI TTS failed: {exc}") from exc

        # 2. Render blank background for segment.duration
        from video_compose.renderers.blank import BlankRenderer
        from types import SimpleNamespace

        bg_path = output_path.with_stem(output_path.stem + "_ttsbg")
        bg_seg = SimpleNamespace(
            duration=float(segment.duration),
            color=getattr(segment, "color", "#000000"),
            bg_style=getattr(segment, "bg_style", "solid"),
        )
        BlankRenderer().render(bg_seg, None, bg_path, width=width, height=height, fps=fps)

        # 3. Mux TTS audio onto background video
        cmd = [
            "ffmpeg", "-y",
            "-i", str(bg_path),
            "-i", str(audio_tmp),
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        audio_tmp.unlink(missing_ok=True)
        bg_path.unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f"TTS mux failed: {result.stderr[-400:]}")

        return output_path
