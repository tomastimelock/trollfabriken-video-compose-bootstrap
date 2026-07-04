from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AudioMixer:
    """Mixes background tracks and voiceover onto a video using audio-arrange + ffmpeg."""

    def mix_onto_video(
        self,
        video_path: Path,
        spec,
        segment_timing: dict[str, float],
        voiceover_clips: dict[str, Path],
        total_duration: float,
        output_path: Path,
    ) -> Path:
        """Composite audio (tracks + voiceover) onto *video_path*.

        Args:
            video_path:       Silent MP4 from the assembler.
            spec:             TVCSSpec (for audio.tracks and audio.voiceover).
            segment_timing:   {segment_id: start_time_seconds}.
            voiceover_clips:  {segment_id: audio_path} (empty if no voiceover).
            total_duration:   Total video duration in seconds.
            output_path:      Where to write the final MP4 with audio.
        """
        try:
            from audio_arrange import Timeline, Clip
        except ImportError as exc:
            raise RuntimeError(
                "audio-arrange is required for audio mixing — pip install audio-arrange"
            ) from exc

        audio_config = spec.audio if spec.audio else None
        if not audio_config:
            return video_path

        tl = Timeline(sample_rate=48000, channels=2)

        # --- Background music tracks ---
        for track in (audio_config.tracks or []):
            source = Path(track.source)
            if not source.exists():
                logger.warning("Audio track not found: %s", source)
                continue

            start_at = _resolve_track_timing(track.timing, segment_timing, total_duration)
            gain_db = _volume_to_db(track.volume)

            clip = Clip(source=source)
            tl.add(
                clip,
                track="music",
                at=start_at,
                gain_db=gain_db,
                fade_in=track.fade_in,
                fade_out=track.fade_out,
            )

        # --- Voiceover clips ---
        for seg_id, audio_path in voiceover_clips.items():
            if seg_id == "__manual__":
                start_at = 0.0
            else:
                start_at = segment_timing.get(seg_id, 0.0)

            clip = Clip(source=audio_path)
            tl.add(clip, track="voiceover", at=start_at, gain_db=0.0)

        # If nothing was added, skip mixing
        if not tl.events():
            return video_path

        # Render mixed audio to WAV
        audio_out = output_path.with_suffix(".audio.wav")
        tl.render(audio_out, format="wav")

        # Mux audio onto video with loudness normalisation (EBU R128 single-pass)
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_out),
            "-c:v", "copy",
            # Preserve BT.709 colour metadata written by renderers (pass-through only)
            "-movflags", "+write_colr",
            "-c:a", "aac", "-b:a", "192k",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:linear=true",
            "-shortest",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        audio_out.unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg audio mux failed: {result.stderr[:500]}")

        return output_path


def _resolve_track_timing(timing: str, segment_timing: dict, total_duration: float) -> float:
    if timing == "throughout":
        return 0.0
    if timing == "intro":
        return 0.0
    if timing == "outro":
        return max(0.0, total_duration - 30.0)
    return segment_timing.get(timing, 0.0)


def _volume_to_db(volume: float) -> float:
    import math
    if volume <= 0:
        return -60.0
    return 20.0 * math.log10(volume)
