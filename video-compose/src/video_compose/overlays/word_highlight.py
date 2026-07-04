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

    style = getattr(ov, "style", "karaoke") or "karaoke"

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

        _draw_style(
            style, draw, img, lines, words, word_timings,
            font, line_h, y_start, width, height,
            active_idx, t, fps, ov,
        )

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


def _draw_style(
    style: str, draw, img, lines, words, word_timings,
    font, line_h, y_start, width, height,
    active_idx, t, fps, ov,
):
    """Dispatch to the correct style renderer."""
    import math, random

    text_color = _hex_to_rgba(ov.text_color)
    hi_color = _hex_to_rgba(ov.highlight_color)
    hi_bg = _hex_to_rgba(ov.highlight_bg) if ov.highlight_bg else None

    word_global_idx = 0
    ys = y_start

    for line_words in lines:
        line_text = " ".join(line_words)
        lw = draw.textlength(line_text, font=font)
        x = (width - lw) // 2

        for word in line_words:
            is_active = active_idx is not None and word_global_idx == active_idx
            word_w = draw.textlength(word, font=font)
            space_w = draw.textlength(" ", font=font)

            # --- active word timing fraction (0→1 within the word) ---
            frac = 0.0
            if is_active and word_timings:
                wt = word_timings[word_global_idx]
                dur_w = max(wt.end - wt.start, 0.001)
                frac = min(1.0, (t - wt.start) / dur_w)

            if style == "typewriter":
                # Show only words up to and including active
                if active_idx is None or word_global_idx > active_idx:
                    x += word_w + space_w
                    word_global_idx += 1
                    continue
                color = hi_color if is_active else text_color
                draw.text((x, ys), word, font=font, fill=color)

            elif style == "pop":
                # Active word scales up slightly (simulate with larger font rendered separately)
                if is_active:
                    scale = 1.0 + 0.3 * math.sin(frac * math.pi)
                    big_size = int(font.size * scale)
                    big_font = _load_font(getattr(ov, "font_family", None), big_size)
                    big_w = draw.textlength(word, font=big_font)
                    ox = x + (word_w - big_w) // 2
                    oy = ys - (big_size - font.size) // 2
                    if hi_bg and hi_bg[3] > 0:
                        pad = 4
                        draw.rounded_rectangle(
                            [(ox - pad, oy - pad), (ox + big_w + pad, oy + big_size + pad)],
                            radius=4, fill=hi_bg,
                        )
                    draw.text((ox, oy), word, font=big_font, fill=hi_color)
                else:
                    draw.text((x, ys), word, font=font, fill=text_color)

            elif style == "shake":
                if is_active:
                    import random as _r
                    ox = x + _r.randint(-4, 4)
                    oy = ys + _r.randint(-3, 3)
                    draw.text((ox, oy), word, font=font, fill=hi_color)
                else:
                    draw.text((x, ys), word, font=font, fill=text_color)

            elif style == "glow":
                if is_active:
                    # Draw multiple blurred copies for glow effect
                    for offset in [(-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1)]:
                        glow_c = (*hi_color[:3], 80)
                        draw.text((x + offset[0], ys + offset[1]), word, font=font, fill=glow_c)
                    draw.text((x, ys), word, font=font, fill=hi_color)
                else:
                    draw.text((x, ys), word, font=font, fill=text_color)

            elif style == "slide_up":
                if is_active:
                    slide = int(line_h * (1.0 - frac))
                    if hi_bg and hi_bg[3] > 0:
                        pad = 4
                        draw.rounded_rectangle(
                            [(x - pad, ys + slide - pad), (x + word_w + pad, ys + slide + line_h + pad)],
                            radius=4, fill=hi_bg,
                        )
                    draw.text((x, ys + slide), word, font=font, fill=hi_color)
                else:
                    draw.text((x, ys), word, font=font, fill=text_color)

            elif style == "fade":
                if is_active:
                    draw.text((x, ys), word, font=font, fill=hi_color)
                else:
                    faded = (*text_color[:3], int(text_color[3] * 0.35))
                    draw.text((x, ys), word, font=font, fill=faded)

            elif style == "outline_pulse":
                if is_active:
                    pulse = int(3 + 2 * math.sin(t * math.pi * 4))
                    for ox, oy in [(-pulse, 0), (pulse, 0), (0, -pulse), (0, pulse)]:
                        draw.text((x + ox, ys + oy), word, font=font, fill=hi_color)
                    draw.text((x, ys), word, font=font, fill=(255, 255, 255, 255))
                else:
                    draw.text((x, ys), word, font=font, fill=text_color)

            elif style == "color_wave":
                # Each word gets a hue-shifted color based on position + time
                import colorsys
                hue = (word_global_idx / max(len(words), 1) + t * 0.5) % 1.0
                r, g, b = colorsys.hsv_to_rgb(hue, 0.9, 1.0)
                wave_color = (int(r * 255), int(g * 255), int(b * 255), 255)
                draw.text((x, ys), word, font=font, fill=wave_color if is_active else text_color)

            elif style == "bold_highlight":
                if is_active:
                    # Simulate bold by drawing twice with 1px offset
                    if hi_bg and hi_bg[3] > 0:
                        pad = 4
                        draw.rounded_rectangle(
                            [(x - pad, ys - pad), (x + word_w + pad, ys + line_h + pad)],
                            radius=4, fill=hi_bg,
                        )
                    for ox in (0, 1):
                        draw.text((x + ox, ys), word, font=font, fill=hi_color)
                else:
                    draw.text((x, ys), word, font=font, fill=text_color)

            else:
                # karaoke (default): color change + optional bg highlight
                color = hi_color if is_active else text_color
                bg_color = hi_bg if (is_active and hi_bg) else None
                if bg_color and bg_color[3] > 0:
                    pad = 4
                    draw.rounded_rectangle(
                        [(x - pad, ys - pad), (x + word_w + pad, ys + line_h + pad)],
                        radius=4, fill=bg_color,
                    )
                draw.text((x, ys), word, font=font, fill=color)

            x += word_w + space_w
            word_global_idx += 1

        ys += line_h


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
