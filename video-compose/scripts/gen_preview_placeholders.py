"""Generate placeholder preview JPEGs for all bundled templates."""
from __future__ import annotations
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BUNDLED = Path(__file__).parent.parent / "src" / "video_compose" / "templates" / "bundled"
PREVIEWS = Path(__file__).parent.parent / "src" / "video_compose" / "templates" / "previews"
THUMB_DIR = PREVIEWS / "thumbnails"
FULL_DIR = PREVIEWS / "full"

CATEGORY_COLORS: dict[str, tuple[int, int, int]] = {
    "social":        (30,  30,  80),
    "data_story":    (10,  40,  60),
    "lower_third":   (30,  10,  10),
    "product_launch":(10,  10,  10),
    "presentation":  (10,  22,  40),
    "swedish":       (0,   42, 104),
    "real_estate":   (26,  26,  46),
    "financial":     (10,  22,  40),
    "event":         (30,   5,   5),
    "people":        (20,  20,  50),
    "creator":       (10,  10,  10),
    "sports":        (10,  10,  10),
    "audio":         (26,  26,  46),
}

ACCENT_COLORS: dict[str, tuple[int, int, int]] = {
    "social":        (80, 140, 255),
    "data_story":    (0,  160, 220),
    "lower_third":   (200,  0,   0),
    "product_launch":(0,  255, 136),
    "presentation":  (0,  102, 204),
    "swedish":       (0,  106, 167),
    "real_estate":   (200, 150,  62),
    "financial":     (0,  102, 204),
    "event":         (230,  57,  70),
    "people":        (0,  102, 204),
    "creator":       (255,   0,   0),
    "sports":        (255, 215,   0),
    "audio":         (255, 107,  53),
}


def _load_font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def render_placeholder(template_id: str, name: str, category: str,
                        width: int, height: int) -> Image.Image:
    bg = CATEGORY_COLORS.get(category, (20, 20, 40))
    accent = ACCENT_COLORS.get(category, (100, 150, 255))

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    # accent bar at bottom 8 px (scaled)
    bar_h = max(4, height // 80)
    draw.rectangle([(0, height - bar_h), (width, height)], fill=accent)

    # category badge top-left
    badge_h = max(20, height // 30)
    badge_w = max(80, width // 10)
    draw.rectangle([(0, 0), (badge_w, badge_h)], fill=accent)

    font_badge = _load_font(max(8, height // 55))
    draw.text((4, 2), category.upper(), fill=(255, 255, 255), font=font_badge)

    # template name centred
    font_name = _load_font(max(14, height // 28))
    bbox = draw.textbbox((0, 0), name, font=font_name)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - tw) // 2, (height - th) // 2 - th // 2), name,
              fill=(255, 255, 255), font=font_name)

    # template id below
    font_id = _load_font(max(8, height // 55))
    bid = draw.textbbox((0, 0), template_id, font=font_id)
    iw = bid[2] - bid[0]
    draw.text(((width - iw) // 2, (height + th) // 2 + 6), template_id,
              fill=accent, font=font_id)

    return img


def main() -> None:
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    FULL_DIR.mkdir(parents=True, exist_ok=True)

    generated = 0
    for json_path in sorted(BUNDLED.rglob("*.json")):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  SKIP {json_path.name}: {exc}")
            continue

        tmpl = data.get("template", {})
        template_id = tmpl.get("id", json_path.stem)
        name = tmpl.get("name", template_id)
        category = tmpl.get("category", "unknown")

        thumb_path = THUMB_DIR / f"{template_id}.jpg"
        full_path = FULL_DIR / f"{template_id}.jpg"

        thumb = render_placeholder(template_id, name, category, 400, 225)
        thumb.save(thumb_path, "JPEG", quality=85)

        full = render_placeholder(template_id, name, category, 1920, 1080)
        full.save(full_path, "JPEG", quality=85)

        generated += 1
        print(f"  OK  {template_id}")

    print(f"\nGenerated {generated * 2} preview images ({generated} templates).")


if __name__ == "__main__":
    main()
