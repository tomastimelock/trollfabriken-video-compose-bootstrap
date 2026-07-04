from __future__ import annotations

import json
from pathlib import Path


_PLATFORM_SPECS = {
    "tiktok":    {"width": 1080, "height": 1920, "fps": 30},
    "reels":     {"width": 1080, "height": 1920, "fps": 30},
    "youtube":   {"width": 1920, "height": 1080, "fps": 30},
    "instagram": {"width": 1080, "height": 1080, "fps": 30},
    "shorts":    {"width": 1080, "height": 1920, "fps": 60},
}


def repurpose(
    video_path: str | Path,
    output_dir: str | Path,
    count: int = 5,
    target_duration: float = 60.0,
    platform: str = "tiktok",
    caption_style: str = "karaoke",
) -> list[dict]:
    """Full pipeline: transcribe → score → select clips → generate TVCS specs.

    Returns list of spec dicts (one per clip). Saves specs to output_dir.
    """
    from video_compose.audio.transcription import transcribe
    from video_compose.tools.highlight import extract_highlights

    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    plat = _PLATFORM_SPECS.get(platform, _PLATFORM_SPECS["tiktok"])

    transcript = transcribe(video_path)
    per_clip = target_duration / count
    all_highlights = extract_highlights(video_path, transcript, target_duration=target_duration * count)

    specs: list[dict] = []
    clip_pool = list(all_highlights)

    for clip_i in range(count):
        # Pick clips that fill per_clip seconds
        chosen = []
        budget = per_clip
        while clip_pool and budget > 0:
            c = clip_pool.pop(0)
            dur = c.end - c.start
            chosen.append(c)
            budget -= dur
            if budget <= 0:
                break
        if not chosen:
            break

        segments = []
        for j, c in enumerate(chosen):
            seg_dur = round(c.end - c.start, 2)
            overlays = []
            if caption_style and transcript.words:
                # Filter words for this clip window
                clip_words = [
                    w for w in transcript.words
                    if c.start <= w.start < c.end
                ]
                if clip_words:
                    word_timings = [
                        {"word": w.word, "start": round(w.start - c.start, 3), "end": round(w.end - c.start, 3)}
                        for w in clip_words
                    ]
                    overlays.append({
                        "type": "word_highlight",
                        "words": [wt["word"] for wt in word_timings],
                        "word_timings": word_timings,
                        "style": caption_style,
                        "position": "lower_third_2",
                        "font_size_pct": 6.0,
                        "text_color": "#ffffff",
                        "highlight_color": "#ffdd00",
                        "timing": {"start": 0.0},
                    })

            segments.append({
                "id": f"clip_{clip_i}_{j}",
                "type": "video",
                "source": str(video_path),
                "start_time": round(c.start, 3),
                "trim_end": round(c.end, 3),
                "duration": seg_dur,
                "overlays": overlays,
            })

        spec = {
            "output": {
                "width": plat["width"],
                "height": plat["height"],
                "fps": plat["fps"],
            },
            "segments": segments,
        }
        spec_path = output_dir / f"clip_{clip_i:02d}.json"
        spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        specs.append(spec)

    return specs
