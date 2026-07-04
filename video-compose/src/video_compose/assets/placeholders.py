from __future__ import annotations

from pathlib import Path

_ASSETS_DIR = Path(__file__).parent / "placeholders"

# keyword → placeholder filename (checked against lowercase variable name)
_IMAGE_RULES: list[tuple[tuple[str, ...], str]] = [
    (("headshot", "portrait", "speaker_photo", "avatar", "profile"), "headshot.png"),
    (("product", "hero_image", "item_photo"),                        "product_hero.png"),
    (("real_estate", "property", "house", "exterior", "listing"),   "real_estate.png"),
    (("team",),                                                       "team_photo.png"),
    (("landscape", "background_image", "scene", "cover"),           "landscape_motivational.png"),
]

_AUDIO_RULES: list[tuple[tuple[str, ...], str]] = [
    (("lofi", "chill", "ambient_track"),  "music_lofi.mp3"),
    (("cinematic", "dramatic", "epic"),   "music_cinematic.mp3"),
    # default fallback for any music/audio var
    (("music", "track", "audio_file", "bed", "bgm", "background_audio", "soundtrack"), "music_corporate.mp3"),
]


def auto_placeholder(var_name: str, var_type: str) -> str | None:
    """Return an absolute path to a bundled placeholder asset for *var_name*.

    Matches on keyword substrings in the variable name (case-insensitive).
    Returns None if no match is found.

    Args:
        var_name: Template variable name (e.g. 'speaker_photo', 'bg_music').
        var_type: TVCS variable type: 'image_path', 'video_path', 'audio_path', etc.

    Returns:
        Absolute path string to the placeholder file, or None.
    """
    name_lower = var_name.lower()

    if var_type in ("image_path", "video_path"):
        for keywords, filename in _IMAGE_RULES:
            if any(kw in name_lower for kw in keywords):
                p = _ASSETS_DIR / filename
                return str(p) if p.exists() else None
        # Generic fallback for any image_path
        fallback = _ASSETS_DIR / "landscape_motivational.png"
        return str(fallback) if fallback.exists() else None

    if var_type == "audio_path":
        for keywords, filename in _AUDIO_RULES:
            if any(kw in name_lower for kw in keywords):
                p = _ASSETS_DIR / filename
                return str(p) if p.exists() else None
        # Generic fallback for any audio_path
        fallback = _ASSETS_DIR / "music_corporate.mp3"
        return str(fallback) if fallback.exists() else None

    return None
