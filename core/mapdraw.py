"""Отрисовка энергокарты поверх плана эвакуации (Pillow)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import db

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
SCALE = 1.5  # во сколько раз увеличиваем план для чёткости

STATUS_RGB = {
    "ok": (46, 160, 67), "low": (240, 170, 0), "critical": (220, 50, 50),
    "over": (40, 110, 230), "no_lamps": (130, 130, 130), "no_area": (130, 130, 130),
}
TECH_RGB = {
    "LED": (255, 214, 0), "Люминесцентная": (120, 200, 255), "КЛЛ": (140, 230, 140),
    "Накаливания": (255, 130, 30), "Галогенная": (255, 80, 80), "ДРЛ": (190, 90, 255),
}


@lru_cache(maxsize=8)
def font(size: int, bold: bool = False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(str(FONT_DIR / name), size)
    except OSError:
        return ImageFont.load_default()


@lru_cache(maxsize=16)
def _base(path: str, mtime: float) -> Image.Image:
    im = Image.open(path).convert("RGB")
    return im.resize((int(im.width * SCALE), int(im.height * SCALE)), Image.LANCZOS)


def base_image(map_row: dict) -> Image.Image:
    p = db.resolve_image(map_row["image_path"])
    return _base(str(p), p.stat().st_mtime).copy()


def original_size(map_row: dict) -> tuple[int, int]:
    with Image.open(db.resolve_image(map_row["image_path"])) as im:
        return im.size


def render(map_row: dict, rooms: list[dict], lamps: list[dict], metrics: dict[int, dict],
           selected_room: int | None = None, pending: tuple | None = None,
           show_rooms=True, show_lamps=True, show_labels=True, show_openings=True) -> Image.Image:
    img = base_image(map_row).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    S = SCALE

    if show_rooms:
        for r in rooms:
            if r["x1"] is None:
                continue
            m = metrics.get(r["id"], {})
            col = STATUS_RGB.get(m.get("status", "no_lamps"), (130, 130, 130))
            box = [min(r["x1"], r["x2"]) * S, min(r["y1"], r["y2"]) * S,
                   max(r["x1"], r["x2"]) * S, max(r["y1"], r["y2"]) * S]
            sel = r["id"] == selected_room
            d.rectangle(box, fill=col + ((95 if sel else 55),), outline=col + (255,), width=4 if sel else 2)

    if show_openings:
        for r in rooms:
            try:
                op = json.loads(r.get("openings") or "{}")
            except ValueError:
                op = {}
            for seg in op.get("windows", []):
                d.line([v * S for v in seg], fill=(0, 190, 255, 255), width=6)
            for seg in op.get("doors", []):
                d.line([v * S for v in seg], fill=(150, 75, 0, 255), width=6)

    if show_lamps:
        for l in lamps:
            if l["x"] is None:
                continue
            cx, cy = l["x"] * S, l["y"] * S
            col = TECH_RGB.get(l.get("tech"), (255, 255, 255))
            for rad, a in ((13, 45), (9, 90)):
                d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=col + (a,))
            d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=col + (255,), outline=(40, 40, 40, 255), width=1)
            if int(l.get("qty") or 1) > 1:
                d.text((cx + 6, cy - 14), f"×{l['qty']}", font=font(12, True), fill=(20, 20, 20, 255))

    if show_labels and show_rooms:
        f = font(12)
        for r in rooms:
            if r["x1"] is None:
                continue
            m = metrics.get(r["id"], {})
            x, y = min(r["x1"], r["x2"]) * S + 3, min(r["y1"], r["y2"]) * S + 3
            room_w = abs(r["x2"] - r["x1"]) * S
            txt = f"{r['name'][:22]}\n{m.get('lux', 0):.0f} лк · {m.get('power_kw', 0):.2f} кВт"
            bb = d.multiline_textbbox((x, y), txt, font=f, spacing=1)
            if bb[2] - bb[0] > room_w + 4:  # узкое помещение — только освещённость
                txt = f"{m.get('lux', 0):.0f} лк"
                bb = d.multiline_textbbox((x, y), txt, font=f, spacing=1)
            d.rectangle([bb[0] - 2, bb[1] - 1, bb[2] + 2, bb[3] + 1], fill=(255, 255, 255, 210))
            d.multiline_text((x, y), txt, font=f, fill=(20, 20, 20, 255), spacing=1)

    if pending:
        px, py = pending[0] * S, pending[1] * S
        d.line([px - 10, py, px + 10, py], fill=(255, 0, 140, 255), width=3)
        d.line([px, py - 10, px, py + 10], fill=(255, 0, 140, 255), width=3)

    return Image.alpha_composite(img, overlay).convert("RGB")
