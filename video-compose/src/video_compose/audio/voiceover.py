from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class VoiceoverEngine:
    """Generates per-segment voiceover audio via talk-cast ElevenLabs TTS."""

    def __init__(self, config) -> None:
        self._config = config  # VoiceoverConfig

    def generate_segment(self, text: str, output_path: Path) -> Path:
        """Synthesize *text* to *output_path* (MP3). Returns the path."""
        try:
            from talk_cast.tts.elevenlabs import synthesize
            from talk_cast.config import NarrateConfig
        except ImportError as exc:
            raise RuntimeError(
                "talk-cast is required for voiceover — pip install talk-cast"
            ) from exc

        # Resolve API key via vault or env
        api_key = _get_elevenlabs_key()

        voice_id = self._config.voice if self._config.voice != "default" else "JBFqnCBsd6RMkjVDRZzb"

        audio_bytes = synthesize(
            text=text,
            voice_id=voice_id,
            model_id="eleven_multilingual_v2",
            voice_settings={"stability": 0.5, "similarity_boost": 0.75},
            api_key=api_key,
        )

        output_path = Path(output_path)
        output_path.write_bytes(audio_bytes)
        logger.info("Voiceover: %d chars → %s (%d bytes)", len(text), output_path, len(audio_bytes))
        return output_path

    def generate_all(self, segments: list, output_dir: Path) -> dict[str, Path]:
        """Generate voiceover for every segment that has narration.

        Returns:
            {segment_id: audio_path} for segments with narration.
        """
        output_dir = Path(output_dir)
        result: dict[str, Path] = {}

        if self._config.script == "manual":
            # One unified audio file for the entire video
            if self._config.text:
                audio_path = output_dir / "voiceover_manual.mp3"
                self.generate_segment(self._config.text, audio_path)
                result["__manual__"] = audio_path
        else:
            # Auto: one audio per segment with narration
            for seg in segments:
                text = getattr(seg, "narration", None)
                if not text:
                    continue
                safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in seg.id)
                audio_path = output_dir / f"vo_{safe_id}.mp3"
                try:
                    self.generate_segment(text, audio_path)
                    result[seg.id] = audio_path
                except Exception as exc:
                    logger.warning("Voiceover for segment %r failed: %s", seg.id, exc)

        return result


def _get_elevenlabs_key() -> str:
    import os
    try:
        from auth_api_key import get_key
        return get_key("ELEVENLABS_API_KEY")
    except Exception:
        pass
    key = os.environ.get("ELEVENLABS_API_KEY")
    if key:
        return key
    raise RuntimeError(
        "ElevenLabs API key not found. Set ELEVENLABS_API_KEY or store it in the vault."
    )
