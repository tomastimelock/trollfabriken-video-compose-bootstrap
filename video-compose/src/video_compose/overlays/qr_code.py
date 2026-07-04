from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import QrCodeOverlay

_EC = {"L": 1, "M": 0, "Q": 3, "H": 2}  # qrcode ERROR_CORRECT_* values

_POSITION_TO_XY = {
    "center":            ("(main_w-overlay_w)/2", "(main_h-overlay_h)/2"),
    "top":               ("(main_w-overlay_w)/2", "0"),
    "bottom":            ("(main_w-overlay_w)/2", "main_h-overlay_h"),
    "top-left":          ("0", "0"),
    "top-right":         ("main_w-overlay_w", "0"),
    "bottom-left":       ("0", "main_h-overlay_h"),
    "bottom-right":      ("main_w-overlay_w", "main_h-overlay_h"),
    "left":              ("0", "(main_h-overlay_h)/2"),
    "right":             ("main_w-overlay_w", "(main_h-overlay_h)/2"),
    "lower_third":       ("(main_w-overlay_w)/2", "main_h*0.78"),
    "lower_third_left":  ("main_w*0.05", "main_h*0.78"),
    "lower_third_right": ("main_w*0.95-overlay_w", "main_h*0.78"),
    "lower_third_2":     ("(main_w-overlay_w)/2", "main_h*0.86"),
}


def render_qr_code_overlay(
    ov: "QrCodeOverlay",
    segment_duration: float,
    width: int,
    height: int,
    fps: float,
    work_dir: Path,
    index: int,
) -> dict:
    """Generate a QR code PNG via qrcode library, loop to WebM with alpha."""
    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H
    except ImportError as exc:
        raise RuntimeError("qrcode is required for qr_code overlays — pip install qrcode[pil]") from exc

    from PIL import Image

    ec_map = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "Q": ERROR_CORRECT_Q, "H": ERROR_CORRECT_H}
    size_px = int(width * ov.size_pct / 100)

    transparent_bg = ov.bg_color.lower() in ("transparent", "none", "")
    bg = (0, 0, 0, 0) if transparent_bg else _hex_to_rgba(ov.bg_color)
    fg = _hex_to_rgba(ov.fg_color)

    qr = qrcode.QRCode(error_correction=ec_map[ov.error_correction], box_size=10, border=2)
    qr.add_data(ov.content)
    qr.make(fit=True)

    # Generate as RGBA for transparency support
    pil_img = qr.make_image(fill_color=fg[:3], back_color="transparent" if transparent_bg else bg[:3])
    pil_img = pil_img.convert("RGBA")

    # If transparent bg, apply alpha channel
    if transparent_bg:
        data = pil_img.getdata()
        new_data = [(0, 0, 0, 0) if item[:3] == (255, 255, 255) else item for item in data]
        pil_img.putdata(new_data)

    pil_img = pil_img.resize((size_px, size_px), Image.NEAREST)

    png = work_dir / f"qr_overlay_{index}.png"
    pil_img.save(png)

    out = work_dir / f"qr_overlay_{index}.webm"
    start = ov.timing.start
    end = ov.timing.end if ov.timing.end is not None else segment_duration
    dur = max(end - start, 0.1)

    opacity_f = f",colorchannelmixer=aa={ov.opacity}" if ov.opacity < 1.0 else ""
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", str(int(fps)), "-i", str(png),
        "-t", str(dur),
        "-vf", f"format=yuva420p{opacity_f}",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "20", "-an",
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"QR ffmpeg encode failed: {r.stderr[-300:]}")

    x, y = (_POSITION_TO_XY.get(ov.position, _POSITION_TO_XY["center"])
            if ov.x_pct is None else (str(int(width*ov.x_pct/100)), str(int(height*ov.y_pct/100))))
    return {"path": out, "x": x, "y": y, "start": start, "end": end,
            "keyframes": None, "z_order": ov.z_order, "_is_media_overlay": True}


def _hex_to_rgba(h: str) -> tuple[int, int, int, int]:
    h = h.lstrip("#")
    if len(h) == 6:
        return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), 255
    if len(h) == 8:
        return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), int(h[6:8],16)
    return 0, 0, 0, 255
