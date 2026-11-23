"""Сборка показателей из базы для интерфейса."""
from __future__ import annotations

from collections import defaultdict

from . import db
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
