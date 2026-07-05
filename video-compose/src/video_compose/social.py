from __future__ import annotations

from pathlib import Path

SOCIAL_PRESETS: dict[str, dict] = {
    "reels":          {"width": 1080, "height": 1920, "fps": 30, "loudnorm_lufs": -14.0, "safe_zone_pct": 10},
    "tiktok":         {"width": 1080, "height": 1920, "fps": 30, "loudnorm_lufs": -14.0, "safe_zone_pct": 10},
    "shorts":         {"width": 1080, "height": 1920, "fps": 60, "loudnorm_lufs": -14.0, "safe_zone_pct": 15},
    "instagram-post": {"width": 1080, "height": 1080, "fps": 30, "loudnorm_lufs": -14.0, "safe_zone_pct": 0},
    "twitter":        {"width": 1280, "height": 720,  "fps": 30, "loudnorm_lufs": -16.0, "safe_zone_pct": 0},
    "linkedin":       {"width": 1920, "height": 1080, "fps": 30, "loudnorm_lufs": -16.0, "safe_zone_pct": 0},
    "youtube":        {"width": 1920, "height": 1080, "fps": 30, "loudnorm_lufs": -14.0, "safe_zone_pct": 0},
}


def apply_social_to_spec(spec, preset_name: str) -> None:
    """Mutate spec.output dimensions/fps to match a social platform's requirements."""
    preset = SOCIAL_PRESETS.get(preset_name)
    if not preset:
        raise ValueError(
            f"Unknown social preset {preset_name!r}. Available: {sorted(SOCIAL_PRESETS)}"
        )
    out = spec.output
    if out is None:
        return
    out.width = preset["width"]
    out.height = preset["height"]
    out.fps = preset["fps"]
    out.social_preset = preset_name


def loudnorm_video(video_path: Path, out_dir: Path, lufs: float) -> Path:
    """Apply EBU R128 loudnorm to a video's audio track, return the normalised path."""
    import subprocess
    out = out_dir / (video_path.stem + "_norm.mp4")
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-af", f"loudnorm=I={lufs:.1f}:TP=-1.5:LRA=11:linear=true",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Loudnorm failed: {r.stderr[-300:]}")
    return out
