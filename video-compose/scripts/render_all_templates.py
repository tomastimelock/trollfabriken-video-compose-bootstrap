"""Render all 51 bundled templates to E:\\VideoCompose.

Templates that require image_path / video_path / audio_path with no default
receive auto-generated placeholder assets so every template can attempt a render.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
OUTPUT_DIR = Path("E:/VideoCompose")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BUNDLED = Path(__file__).parent.parent / "src" / "video_compose" / "templates" / "bundled"

PLACEHOLDER_DIR = OUTPUT_DIR / "_placeholders"
PLACEHOLDER_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Placeholder asset generators (created once, reused for every template)
# ---------------------------------------------------------------------------

def _make_placeholder_image() -> Path:
    path = PLACEHOLDER_DIR / "placeholder_image.jpg"
    if not path.exists():
        img = Image.new("RGB", (1920, 1080), (30, 30, 50))
        draw = ImageDraw.Draw(img)
        draw.rectangle([(80, 80), (1840, 1000)], outline=(80, 80, 120), width=4)
        draw.text((880, 510), "PLACEHOLDER IMAGE", fill=(100, 100, 150))
        img.save(path, "JPEG", quality=85)
    return path


def _make_placeholder_video() -> Path:
    path = PLACEHOLDER_DIR / "placeholder_video.mp4"
    if not path.exists():
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "color=c=0x1a1a2e:size=1920x1080:rate=30:duration=15",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "28",
            str(path),
        ], capture_output=True, check=True)
    return path


def _make_placeholder_audio() -> Path:
    path = PLACEHOLDER_DIR / "placeholder_audio.wav"
    if not path.exists():
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "60",
            str(path),
        ], capture_output=True, check=True)
    return path


# ---------------------------------------------------------------------------
# Fallback data for templates whose default data is deliberately empty
# ---------------------------------------------------------------------------
_FALLBACK_DATA: dict[str, object] = {
    "swedish_valdistrikt_map": {
        "01-0001": 0.45, "01-0002": 0.38, "01-0003": 0.52,
        "12-0001": 0.31, "14-0001": 0.29, "14-0002": 0.41,
    },
}

# Inline deck-spec for presentation_corporate (default points to a non-existent file)
_FALLBACK_SLIDE_SPEC = {
    "title": "Acme Corporation",
    "slides": [
        {"layout": "title",   "title": "Acme Corporation",  "subtitle": "2025 Strategy Review"},
        {"layout": "bullet",  "title": "Key Initiatives",   "bullets": ["Grow revenue 20%", "Expand to 3 new markets", "Launch product v2"]},
        {"layout": "stat",    "title": "Q1 Results",        "stat_value": "127%", "stat_label": "Revenue Growth"},
    ],
}

# ---------------------------------------------------------------------------
# Template filling
# ---------------------------------------------------------------------------
_MEDIA_TYPES = {"image_path", "video_path", "audio_path"}


def fill_for_render(
    template_dict: dict,
    placeholder_image: Path,
    placeholder_video: Path,
    placeholder_audio: Path,
    template_id: str,
) -> dict:
    """Fill all template variables with defaults and placeholder media."""
    from video_compose.templates.engine import TemplateEngine

    engine = TemplateEngine()
    variables: dict = {}

    for var in template_dict.get("template", {}).get("variables", []):
        name: str = var["name"]
        vtype: str = var.get("type", "string")
        default = var.get("default")

        if vtype == "image_path":
            variables[name] = str(placeholder_image)
        elif vtype == "video_path":
            variables[name] = str(placeholder_video)
        elif vtype == "audio_path":
            variables[name] = str(placeholder_audio)
        elif default is not None:
            # Replace empty data_ref defaults with minimal fallback data
            if vtype == "data_ref" and isinstance(default, dict) and not default:
                variables[name] = _FALLBACK_DATA.get(
                    template_id, {"A": 0.6, "B": 0.4}
                )
            # Replace slide_spec file-path defaults with an inline deck-spec dict
            elif name == "slide_spec" and isinstance(default, str) and default.endswith(".json"):
                variables[name] = _FALLBACK_SLIDE_SPEC
            else:
                variables[name] = default
        # Required vars with no default and non-media types: leave absent;
        # engine.fill will raise TemplateFillError → caught by caller.

    filled = engine.fill(template_dict, variables)

    # TVCSSpec does not define a 'template' key — strip it before validation.
    filled.pop("template", None)

    return filled


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Generating placeholder assets...", flush=True)
    placeholder_image = _make_placeholder_image()
    placeholder_video = _make_placeholder_video()
    placeholder_audio = _make_placeholder_audio()
    print(f"  image : {placeholder_image}")
    print(f"  video : {placeholder_video}")
    print(f"  audio : {placeholder_audio}\n")

    from video_compose.api import compose

    json_files = sorted(BUNDLED.rglob("*.json"))
    total = len(json_files)
    print(f"Found {total} templates. Output -> {OUTPUT_DIR}\n")
    print(f"{'#':>3}  {'template_id':<40}  {'result':<8}  {'time':>6}  note")
    print("-" * 80)

    results: list[tuple[str, str, str]] = []

    for i, json_path in enumerate(json_files, 1):
        try:
            template_dict = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"{i:>3}  {json_path.stem:<40}  {'PARSE ERR':<8}  {'':>6}  {exc!s:.60}")
            results.append((json_path.stem, "parse_err", str(exc)))
            continue

        template_id = template_dict.get("template", {}).get("id", json_path.stem)
        out_path = OUTPUT_DIR / f"{template_id}.mp4"

        if out_path.exists():
            size_mb = out_path.stat().st_size / 1_048_576
            print(f"{i:>3}  {template_id:<40}  {'SKIP':<8}  {'':>6}  already exists ({size_mb:.1f} MB)")
            results.append((template_id, "skipped", ""))
            continue

        t0 = time.perf_counter()
        try:
            filled = fill_for_render(
                template_dict,
                placeholder_image,
                placeholder_video,
                placeholder_audio,
                template_id,
            )

            with tempfile.TemporaryDirectory() as td:
                result = compose(filled, output_dir=td)
                shutil.copy2(result.video_path, out_path)

            elapsed = time.perf_counter() - t0
            size_mb = out_path.stat().st_size / 1_048_576
            print(f"{i:>3}  {template_id:<40}  {'OK':<8}  {elapsed:>5.1f}s  {size_mb:.1f} MB")
            results.append((template_id, "ok", ""))

        except Exception as exc:
            elapsed = time.perf_counter() - t0
            short = str(exc).replace("\n", " ")[:80]
            print(f"{i:>3}  {template_id:<40}  {'FAIL':<8}  {elapsed:>5.1f}s  {short}")
            results.append((template_id, "fail", str(exc)))

    # ------------------------------------------------------------------
    ok      = [r for r in results if r[1] == "ok"]
    skipped = [r for r in results if r[1] == "skipped"]
    fails   = [r for r in results if r[1] in ("fail", "parse_err")]

    print(f"\n{'='*80}")
    print(f"TOTAL {total}  |  OK {len(ok)}  |  SKIPPED {len(skipped)}  |  FAILED {len(fails)}")

    if fails:
        print("\nFailed templates:")
        for tid, status, err in fails:
            print(f"  [{status}] {tid}")
            if err:
                print(f"           {err[:120]}")

    total_size = sum(
        (OUTPUT_DIR / f"{r[0]}.mp4").stat().st_size
        for r in ok
        if (OUTPUT_DIR / f"{r[0]}.mp4").exists()
    )
    print(f"\nTotal output size: {total_size / 1_048_576:.1f} MB")
    print(f"Output folder: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
