"""
Quality JSON report for a batch of rendered template videos.

Probes each MP4 for duration, resolution, bitrate, codec.
Correlates with template JSON files to produce a per-template metrics report.

Usage:
    python -m video_compose.tools.report --video-dir E:/VideoCompose/output --template-dir src/video_compose/templates/bundled --out quality_report.json
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)


def probe_video(path: Path) -> dict:
    """Run ffprobe and return a dict with duration, width, height, codec, bitrate."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration,bit_rate:stream=codec_name,width,height,r_frame_rate",
        "-of", "json",
        str(path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout)
    except Exception as exc:
        return {"error": str(exc)}

    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_name") in ("h264", "hevc", "vp9", "av1")), {})

    fps_str = video_stream.get("r_frame_rate", "0/1")
    try:
        num, den = fps_str.split("/")
        fps = round(int(num) / int(den), 2) if int(den) else 0
    except Exception:
        fps = 0

    return {
        "duration_s": round(float(fmt.get("duration", 0)), 2),
        "bitrate_kbps": round(int(fmt.get("bit_rate", 0)) / 1000),
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "codec": video_stream.get("codec_name"),
        "fps": fps,
        "file_size_kb": round(path.stat().st_size / 1024),
    }


def load_template_meta(template_dir: Path) -> dict[str, dict]:
    """Load template JSON files and return {template_id: metadata}."""
    meta: dict[str, dict] = {}
    for f in template_dir.rglob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            tmpl = data.get("template", {})
            tid = tmpl.get("id") or f.stem
            meta[tid] = {
                "id": tid,
                "name": tmpl.get("name", f.stem),
                "category": tmpl.get("category", f.parent.name),
                "tags": tmpl.get("tags", []),
                "template_file": str(f),
            }
        except Exception:
            pass
    return meta


def generate_report(
    video_dir: Path,
    template_dir: Path | None,
    output_path: Path,
    *,
    thumb_dir: Path | None = None,
) -> dict:
    """Scan *video_dir* for MP4s, probe each, correlate with templates, write JSON report."""
    template_meta = load_template_meta(template_dir) if template_dir else {}
    entries: list[dict] = []
    errors: list[dict] = []
    total_duration = 0.0
    total_size_kb = 0

    for mp4 in sorted(video_dir.rglob("*.mp4")):
        stem = mp4.stem
        probe = probe_video(mp4)
        tmeta = template_meta.get(stem, {})

        thumb_path = None
        if thumb_dir:
            for ext in (".jpg", ".jpeg", ".png"):
                candidate = thumb_dir / mp4.relative_to(video_dir).with_suffix(ext)
                if candidate.exists():
                    thumb_path = str(candidate)
                    break

        entry = {
            "stem": stem,
            "file": str(mp4),
            "template_id": tmeta.get("id"),
            "template_name": tmeta.get("name"),
            "category": tmeta.get("category"),
            "thumbnail": thumb_path,
            **probe,
        }

        if "error" in probe:
            errors.append({"file": str(mp4), "error": probe["error"]})
        else:
            total_duration += probe.get("duration_s", 0)
            total_size_kb += probe.get("file_size_kb", 0)
        entries.append(entry)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "video_dir": str(video_dir),
        "template_dir": str(template_dir) if template_dir else None,
        "summary": {
            "total_videos": len(entries),
            "total_errors": len(errors),
            "total_duration_s": round(total_duration, 2),
            "total_size_mb": round(total_size_kb / 1024, 1),
            "avg_duration_s": round(total_duration / max(len(entries), 1), 2),
            "avg_bitrate_kbps": round(
                sum(e.get("bitrate_kbps", 0) for e in entries if "bitrate_kbps" in e)
                / max(sum(1 for e in entries if "bitrate_kbps" in e), 1)
            ),
        },
        "errors": errors,
        "videos": entries,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    _log.info("Report written: %s (%d videos, %d errors)", output_path, len(entries), len(errors))
    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Generate quality report for rendered template videos")
    parser.add_argument("--video-dir", type=Path, required=True)
    parser.add_argument("--template-dir", type=Path, default=None)
    parser.add_argument("--thumb-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("quality_report.json"))
    args = parser.parse_args()

    report = generate_report(
        args.video_dir, args.template_dir, args.out, thumb_dir=args.thumb_dir
    )
    s = report["summary"]
    print(
        f"Report: {s['total_videos']} videos, {s['total_errors']} errors, "
        f"{s['total_duration_s']}s total, {s['total_size_mb']} MB → {args.out}"
    )


if __name__ == "__main__":
    main()
