"""Сборка показателей из базы для интерфейса."""
from __future__ import annotations

from collections import defaultdict

from . import db, openings
from .calc import room_metrics


def compute_all(map_id: int | None = None) -> list[dict]:
    settings, norms = db.get_settings(), db.norms()
    by_room = defaultdict(list)
    for l in db.lamps(map_id=map_id):
        if l["room_id"] is not None:
            by_room[l["room_id"]].append(l)
    return [room_metrics(r, by_room.get(r["id"], []), norms, settings) for r in db.rooms(map_id)]


def led_types() -> list[dict]:
    return [t for t in db.lamp_types() if t["tech"] == "LED"]


def map_names() -> dict[int, str]:
    return {m["id"]: m["name"] for m in db.maps()}


# Окна «второго света»: спортзал (1 этаж) освещается и окнами 2 этажа спортзала
EXTRA_WINDOWS = {("gym1", "Спортзал"): ("gym2", (20, 100, 40, 580), 0.0024)}


def detect_room(room: dict) -> dict:
    """Распознаёт окна и двери помещения по плану и сохраняет в базу."""
    mp = db.get_map(room["map_id"])
    box = (room["x1"], room["y1"], room["x2"], room["y2"])
    if mp is None or room["x1"] is None:
        return {}
    res = openings.detect(str(db.resolve_image(mp["image_path"])), box)
    s = openings.summarize(res, float(room["area"] or 0), box)
    extra = EXTRA_WINDOWS.get((mp["code"], room["name"]))
    if extra:
        other = next((m for m in db.maps() if m["code"] == extra[0]), None)
        if other:
            r2 = openings.detect(str(db.resolve_image(other["image_path"])), extra[1])
            s["win_count"] += len(r2["windows"])
            s["win_len"] = round(s["win_len"] + sum(openings.seg_len(x) for x in r2["windows"]) * extra[2] ** 0.5, 2)
    upd = {**s, "win_area": 0, "windows": int(s["win_count"] > 0)}
    db.update_room(room["id"], upd)
    return upd


def detect_map(map_id: int) -> int:
    n = 0
    for r in db.rooms(map_id):
        if r["x1"] is not None:
            n += detect_room(r).get("win_count", 0)
    return n
