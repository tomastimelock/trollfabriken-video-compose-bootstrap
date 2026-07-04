from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import WordHighlightOverlay


def render_word_highlight_overlay(
    ov: "WordHighlightOverlay",
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    work_dir: Path,
    index: int,
) -> dict:
    """Karaoke-style word-by-word highlight: PIL renders each frame, ffmpeg encodes to WebM."""
    from PIL import Image, ImageDraw, ImageFont

    start = ov.timing.start
    end = ov.timing.end if ov.timing.end is not None else segment_duration
    dur = max(end - start, 0.1)
    total_frames = max(1, int(dur * fps))

    words = ov.words
    word_timings = ov.word_timings  # list[WordTiming] with .word / .start / .end (relative to overlay start)

    # Build lookup: for each frame, which word is "active"
    def active_word_at(t: float) -> int | None:
        for wt_i, wt in enumerate(word_timings):
            if wt.start <= t < wt.end:
                return wt_i
        return None

    # Font setup
    font_size = int(height * ov.font_size_pct / 100)
    font = _load_font(ov.font_family, font_size)
    highlight_font = _load_font(ov.font_family, font_size)

    frames_dir = work_dir / f"word_highlight_{index}_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # Compute layout once: wrap words to lines
    pad_x = int(width * 0.05)
    max_text_width = width - pad_x * 2
    lines = _wrap_words(words, font, max_text_width, draw=None)

    # Draw each frame
    for frame_idx in range(total_frames):
        t = frame_idx / fps  # time relative to overlay start
        active_idx = active_word_at(t)

        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Re-compute line layout with real draw object for bbox
        lines = _wrap_words(words, font, max_text_width, draw=draw)

        line_h = _line_height(font, draw)
        total_h = len(lines) * line_h
        y_start = (height - total_h) // 2

        word_global_idx = 0
        for line_words in lines:
            # Compute line width for centering
            line_text = " ".join(w for w in line_words)
            lw = draw.textlength(line_text, font=font)
            x = (width - lw) // 2

            for word in line_words:
                is_active = active_idx is not None and word_global_idx == active_idx
                color = _hex_to_rgba(ov.highlight_color) if is_active else _hex_to_rgba(ov.text_color)
                bg_color = _hex_to_rgba(ov.highlight_bg) if (is_active and ov.highlight_bg) else None

                word_w = draw.textlength(word, font=font)
                if bg_color and bg_color[3] > 0:
                    pad = 4
                    draw.rounded_rectangle(
                        [(x - pad, y_start - pad), (x + word_w + pad, y_start + line_h + pad)],
                        radius=4, fill=bg_color,
                    )
                draw.text((x, y_start), word, font=font, fill=color)
                x += word_w + draw.textlength(" ", font=font)
                word_global_idx += 1

            y_start += line_h

        img.save(frames_dir / f"frame_{frame_idx:05d}.png")

    out = work_dir / f"word_highlight_{index}.webm"
    opacity_f = f",colorchannelmixer=aa={ov.opacity}" if ov.opacity < 1.0 else ""
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-t", str(dur),
        "-vf", f"format=yuva420p{opacity_f}",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20", "-an",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"word_highlight ffmpeg encode failed: {r.stderr[-400:]}")

    return {"path": out, "x": "0", "y": "0", "start": start, "end": end,
            "keyframes": None, "z_order": ov.z_order, "_is_media_overlay": True}


def _load_font(family: str | None, size: int):
    from PIL import ImageFont
    if family:
        # Try user font dir then system
        from pathlib import Path as _Path
        user_font_dir = _Path.home() / ".video_compose" / "fonts"
        for ext in ("ttf", "otf"):
            candidate = user_font_dir / f"{family}.{ext}"
            if candidate.exists():
                return ImageFont.truetype(str(candidate), size)
        try:
            return ImageFont.truetype(family, size)
        except Exception:
            pass
    return ImageFont.load_default(size=size)


def _line_height(font, draw) -> int:
    bbox = draw.textbbox((0, 0), "Ag", font=font)
    return int((bbox[3] - bbox[1]) * 1.3)


def _wrap_words(words: list[str], font, max_width: int, draw) -> list[list[str]]:
    """Wrap words into lines that fit within max_width."""
    if draw is None:
        # No draw context yet — return single line as fallback
        return [words]

    lines: list[list[str]] = []
    current: list[str] = []
    current_w = 0

    space_w = draw.textlength(" ", font=font)
    for word in words:
        word_w = draw.textlength(word, font=font)
        if current and current_w + space_w + word_w > max_width:
            lines.append(current)
            current = [word]
            current_w = word_w
        else:
            if current:
                current_w += space_w
            current.append(word)
            current_w += word_w

    if current:
        lines.append(current)
    return lines or [[]]


def _hex_to_rgba(h: str) -> tuple[int, int, int, int]:
    if not h or h.lower() in ("transparent", "none"):
        return (0, 0, 0, 0)
    h = h.lstrip("#")
    if len(h) == 6:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255
    if len(h) == 8:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16)
    return 255, 255, 255, 255
