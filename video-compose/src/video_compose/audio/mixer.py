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
        audio_config = spec.audio if spec.audio else None
        if not audio_config:
            return video_path

        try:
            from audio_arrange import Timeline, Clip
        except ImportError as exc:
            raise RuntimeError(
                "audio-arrange is required for audio mixing — pip install audio-arrange"
            ) from exc

        duck_music = bool(getattr(audio_config, "duck_music", False))
        has_voiceover = bool(voiceover_clips)

        if duck_music and has_voiceover:
            return self._mix_with_ducking(
                video_path, audio_config, segment_timing,
                voiceover_clips, total_duration, output_path,
            )

        tl = Timeline(sample_rate=48000, channels=2)

        for track in (audio_config.tracks or []):
            source = Path(track.source)
            if not source.exists():
                logger.warning("Audio track not found: %s", source)
                continue
            start_at = _resolve_track_timing(track.timing, segment_timing, total_duration)
            clip = Clip(source=source)
            tl.add(clip, track="music", at=start_at, gain_db=_volume_to_db(track.volume),
                   fade_in=track.fade_in, fade_out=track.fade_out)

        for seg_id, audio_path in voiceover_clips.items():
            start_at = 0.0 if seg_id == "__manual__" else segment_timing.get(seg_id, 0.0)
            clip = Clip(source=audio_path)
            tl.add(clip, track="voiceover", at=start_at, gain_db=0.0)

        if not tl.events():
            return video_path

        audio_out = output_path.with_suffix(".audio.wav")
        tl.render(audio_out, format="wav")

        result = _mux_audio(video_path, audio_out, output_path)
        audio_out.unlink(missing_ok=True)
        return result

    def _mix_with_ducking(
        self,
        video_path: Path,
        audio_config,
        segment_timing: dict[str, float],
        voiceover_clips: dict[str, Path],
        total_duration: float,
        output_path: Path,
    ) -> Path:
        """Apply sidechain ducking: music ducks when voiceover is present."""
        try:
            from audio_arrange import Timeline, Clip
        except ImportError as exc:
            raise RuntimeError("audio-arrange required — pip install audio-arrange") from exc

        work = output_path.parent

        # Render music-only mix
        tl_music = Timeline(sample_rate=48000, channels=2)
        has_music = False
        for track in (audio_config.tracks or []):
            source = Path(track.source)
            if not source.exists():
                continue
            has_music = True
            start_at = _resolve_track_timing(track.timing, segment_timing, total_duration)
            clip = Clip(source=source)
            tl_music.add(clip, track="music", at=start_at, gain_db=_volume_to_db(track.volume),
                         fade_in=track.fade_in, fade_out=track.fade_out)

        # Render voiceover-only mix
        tl_vo = Timeline(sample_rate=48000, channels=2)
        for seg_id, audio_path in voiceover_clips.items():
            start_at = 0.0 if seg_id == "__manual__" else segment_timing.get(seg_id, 0.0)
            clip = Clip(source=audio_path)
            tl_vo.add(clip, track="voiceover", at=start_at, gain_db=0.0)

        music_wav = work / "_music_only.wav"
        vo_wav = work / "_vo_only.wav"

        if has_music:
            tl_music.render(music_wav, format="wav")
        tl_vo.render(vo_wav, format="wav")

        # Build ducking params from config
        threshold = float(getattr(audio_config, "duck_threshold", -30))
        ratio = float(getattr(audio_config, "duck_ratio", 4))
        attack = float(getattr(audio_config, "duck_attack_ms", 200))
        release = float(getattr(audio_config, "duck_release_ms", 1000))

        if not has_music:
            # No music — just mux voiceover directly
            result = _mux_audio(video_path, vo_wav, output_path)
            vo_wav.unlink(missing_ok=True)
            return result

        # ffmpeg sidechaincompress: music input, voiceover as sidechain key
        mixed_wav = work / "_ducked_mix.wav"
        cmd = [
            "ffmpeg", "-y",
            "-i", str(music_wav),
            "-i", str(vo_wav),
            "-filter_complex",
            (
                f"[0:a][1:a]sidechaincompress="
                f"threshold={10**(threshold/20):.4f}:"
                f"ratio={ratio}:"
                f"attack={attack}:"
                f"release={release}"
                f"[music_ducked];"
                f"[music_ducked][1:a]amix=inputs=2:duration=longest[out]"
            ),
            "-map", "[out]",
            str(mixed_wav),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        music_wav.unlink(missing_ok=True)
        vo_wav.unlink(missing_ok=True)
        if r.returncode != 0:
            raise RuntimeError(f"sidechaincompress failed: {r.stderr[-400:]}")

        result = _mux_audio(video_path, mixed_wav, output_path)
        mixed_wav.unlink(missing_ok=True)
        return result


def _mux_audio(video_path: Path, audio_wav: Path, output_path: Path) -> Path:
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_wav),
        "-c:v", "copy",
        "-movflags", "+write_colr",
        "-c:a", "aac", "-b:a", "192k",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:linear=true",
        "-shortest",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
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
