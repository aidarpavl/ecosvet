"""SQLite-хранилище «ЭкоСвет»: схема, CRUD-операции, резервная копия."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("ECOSVET_DB", ROOT / "data" / "ecosvet.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    full_name TEXT DEFAULT '',
    pw_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS maps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    image_path TEXT NOT NULL,
    sort INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS lamp_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    tech TEXT NOT NULL,
    watts REAL NOT NULL,
    lumens REAL NOT NULL,
    life_hours REAL DEFAULT 10000,
    price REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS norms (
    room_type TEXT PRIMARY KEY,
    lux REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    map_id INTEGER NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    room_type TEXT NOT NULL DEFAULT 'Кабинет',
    x1 REAL, y1 REAL, x2 REAL, y2 REAL,
    area REAL DEFAULT 0,
    height REAL DEFAULT 3.0,
    windows INTEGER DEFAULT 1,
    hours_per_day REAL DEFAULT 6,
    days_per_month REAL DEFAULT 22,
    months_per_year REAL DEFAULT 9,
    has_sensor INTEGER DEFAULT 0,
    note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS lamps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER REFERENCES rooms(id) ON DELETE CASCADE,
    map_id INTEGER NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    lamp_type_id INTEGER NOT NULL REFERENCES lamp_types(id),
    x REAL, y REAL,
    qty INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS swot_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quadrant TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    map_id INTEGER, room_id INTEGER,
    topic TEXT, rating INTEGER, text TEXT NOT NULL,
    status TEXT DEFAULT 'новый',
    reply TEXT DEFAULT '',
    created_at TEXT, replied_at TEXT
);
"""

DEFAULT_SETTINGS = {
    "tariff": "32.0",          # ₸ за кВт·ч (уточните у энергоснабжающей организации)
    "util_factor": "0.5",      # коэффициент использования светового потока U
    "maint_factor": "0.8",     # коэффициент эксплуатации MF
    "co2_factor": "0.9",       # кг CO₂ на кВт·ч (угольная генерация, ориентировочно)
    "school_name": "КГУ «Специализированная школа-лицей «Жас дарын»",
    "llm_provider": "auto",
}


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


@contextmanager
def conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def q(sql: str, params=()) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def q1(sql: str, params=()) -> dict | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def ex(sql: str, params=()) -> int:
    with conn() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid


def init_db() -> bool:
    """Создаёт схему. Возвращает True, если база была пустой (нужен seed)."""
    with conn() as c:
        c.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
        empty = c.execute("SELECT COUNT(*) FROM maps").fetchone()[0] == 0
    return empty


# ---------- настройки ----------
def get_settings() -> dict:
    s = {r["key"]: r["value"] for r in q("SELECT key, value FROM settings")}
    for k, v in DEFAULT_SETTINGS.items():
        s.setdefault(k, v)
    return s


def set_setting(key: str, value) -> None:
    ex("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
       (key, str(value)))


# ---------- карты ----------
def maps() -> list[dict]:
    return q("SELECT * FROM maps ORDER BY sort, id")


def get_map(map_id: int) -> dict | None:
    return q1("SELECT * FROM maps WHERE id=?", (map_id,))


def add_map(code: str, name: str, image_path: str, sort: int = 99) -> int:
    return ex("INSERT INTO maps(code, name, image_path, sort) VALUES (?,?,?,?)", (code, name, image_path, sort))


def rename_map(map_id: int, name: str) -> None:
    ex("UPDATE maps SET name=? WHERE id=?", (name, map_id))


def delete_map(map_id: int) -> None:
    ex("DELETE FROM maps WHERE id=?", (map_id,))


def resolve_image(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


# ---------- типы ламп и нормы ----------
def lamp_types() -> list[dict]:
    return q("SELECT * FROM lamp_types ORDER BY tech, watts")


def lamp_type_map() -> dict[int, dict]:
    return {t["id"]: t for t in lamp_types()}


def upsert_lamp_type(t: dict) -> int:
    if t.get("id"):
        ex("UPDATE lamp_types SET name=?, tech=?, watts=?, lumens=?, life_hours=?, price=? WHERE id=?",
           (t["name"], t["tech"], t["watts"], t["lumens"], t.get("life_hours", 10000), t.get("price", 0), t["id"]))
        return int(t["id"])
    return ex("INSERT INTO lamp_types(name, tech, watts, lumens, life_hours, price) VALUES (?,?,?,?,?,?)",
              (t["name"], t["tech"], t["watts"], t["lumens"], t.get("life_hours", 10000), t.get("price", 0)))


def delete_lamp_type(type_id: int) -> bool:
    used = q1("SELECT COUNT(*) n FROM lamps WHERE lamp_type_id=?", (type_id,))["n"]
    if used:
        return False
    ex("DELETE FROM lamp_types WHERE id=?", (type_id,))
    return True


def norms() -> dict[str, float]:
    return {r["room_type"]: r["lux"] for r in q("SELECT * FROM norms ORDER BY room_type")}


def set_norm(room_type: str, lux: float) -> None:
    ex("INSERT INTO norms(room_type, lux) VALUES (?,?) ON CONFLICT(room_type) DO UPDATE SET lux=excluded.lux",
       (room_type, lux))


# ---------- помещения ----------
ROOM_FIELDS = ["map_id", "name", "room_type", "x1", "y1", "x2", "y2", "area", "height", "windows",
               "hours_per_day", "days_per_month", "months_per_year", "has_sensor", "note"]


def rooms(map_id: int | None = None) -> list[dict]:
    if map_id is None:
        return q("SELECT * FROM rooms ORDER BY map_id, id")
    return q("SELECT * FROM rooms WHERE map_id=? ORDER BY id", (map_id,))


def get_room(room_id: int) -> dict | None:
    return q1("SELECT * FROM rooms WHERE id=?", (room_id,))


def add_room(r: dict) -> int:
    cols = [f for f in ROOM_FIELDS if f in r]
    return ex(f"INSERT INTO rooms({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
              tuple(r[f] for f in cols))


def update_room(room_id: int, r: dict) -> None:
    cols = [f for f in ROOM_FIELDS if f in r]
    if cols:
        ex(f"UPDATE rooms SET {', '.join(f + '=?' for f in cols)} WHERE id=?",
           tuple(r[f] for f in cols) + (room_id,))


def delete_room(room_id: int) -> None:
    ex("DELETE FROM rooms WHERE id=?", (room_id,))


def room_at(map_id: int, x: float, y: float) -> dict | None:
    """Помещение, в контур которого попадает точка (самое маленькое из подходящих)."""
    hits = [r for r in rooms(map_id)
            if r["x1"] is not None and min(r["x1"], r["x2"]) <= x <= max(r["x1"], r["x2"])
            and min(r["y1"], r["y2"]) <= y <= max(r["y1"], r["y2"])]
    if not hits:
        return None
    return min(hits, key=lambda r: abs((r["x2"] - r["x1"]) * (r["y2"] - r["y1"])))


# ---------- лампы ----------
def lamps(map_id: int | None = None, room_id: int | None = None) -> list[dict]:
    sql = ("SELECT l.*, t.name AS type_name, t.tech, t.watts, t.lumens, t.price, t.life_hours "
           "FROM lamps l JOIN lamp_types t ON t.id = l.lamp_type_id")
    if room_id is not None:
        return q(sql + " WHERE l.room_id=? ORDER BY l.id", (room_id,))
    if map_id is not None:
        return q(sql + " WHERE l.map_id=? ORDER BY l.id", (map_id,))
    return q(sql + " ORDER BY l.id")


def add_lamp(map_id: int, room_id: int | None, lamp_type_id: int, x=None, y=None, qty: int = 1) -> int:
    return ex("INSERT INTO lamps(map_id, room_id, lamp_type_id, x, y, qty) VALUES (?,?,?,?,?,?)",
              (map_id, room_id, lamp_type_id, x, y, int(qty)))


def update_lamp(lamp_id: int, lamp_type_id: int, qty: int) -> None:
    ex("UPDATE lamps SET lamp_type_id=?, qty=? WHERE id=?", (lamp_type_id, int(qty), lamp_id))


def delete_lamp(lamp_id: int) -> None:
    ex("DELETE FROM lamps WHERE id=?", (lamp_id,))


def nearest_lamp(map_id: int, x: float, y: float, max_dist: float = 25) -> dict | None:
    best, bd = None, max_dist ** 2
    for l in lamps(map_id=map_id):
        if l["x"] is None:
            continue
        d = (l["x"] - x) ** 2 + (l["y"] - y) ** 2
        if d <= bd:
            best, bd = l, d
    return best


def reassign_lamps_in_room_box(room: dict) -> None:
    """После перерисовки контура: лампы внутри контура привязываются к помещению."""
    for l in lamps(map_id=room["map_id"]):
        if l["x"] is None:
            continue
        r = room_at(room["map_id"], l["x"], l["y"])
        ex("UPDATE lamps SET room_id=? WHERE id=?", (r["id"] if r else None, l["id"]))


# ---------- SWOT ----------
def swot_items() -> list[dict]:
    return q("SELECT * FROM swot_items ORDER BY id")


def add_swot(quadrant: str, text: str) -> None:
    ex("INSERT INTO swot_items(quadrant, text, created_at) VALUES (?,?,?)", (quadrant, text, now()))


def delete_swot(item_id: int) -> None:
    ex("DELETE FROM swot_items WHERE id=?", (item_id,))


# ---------- отзывы ----------
def add_feedback(user_id, map_id, room_id, topic, rating, text) -> None:
    ex("INSERT INTO feedback(user_id, map_id, room_id, topic, rating, text, created_at) VALUES (?,?,?,?,?,?,?)",
       (user_id, map_id, room_id, topic, rating, text, now()))


def feedback_list(user_id: int | None = None) -> list[dict]:
    sql = ("SELECT f.*, u.username, u.full_name, m.name AS map_name, r.name AS room_name FROM feedback f "
           "LEFT JOIN users u ON u.id=f.user_id LEFT JOIN maps m ON m.id=f.map_id "
           "LEFT JOIN rooms r ON r.id=f.room_id")
    if user_id is not None:
        return q(sql + " WHERE f.user_id=? ORDER BY f.id DESC", (user_id,))
    return q(sql + " ORDER BY f.id DESC")


def reply_feedback(fid: int, reply: str, status: str) -> None:
    ex("UPDATE feedback SET reply=?, status=?, replied_at=? WHERE id=?", (reply, status, now(), fid))


def delete_feedback(fid: int) -> None:
    ex("DELETE FROM feedback WHERE id=?", (fid,))


# ---------- резервная копия ----------
BACKUP_TABLES = ["maps", "lamp_types", "norms", "rooms", "lamps", "settings", "swot_items", "feedback"]


def export_json() -> str:
    data = {t: q(f"SELECT * FROM {t}") for t in BACKUP_TABLES}
    data["_exported_at"] = now()
    return json.dumps(data, ensure_ascii=False, indent=1)


def import_json(text: str) -> None:
    data = json.loads(text)
    with conn() as c:
        c.execute("PRAGMA foreign_keys = OFF")
        for t in reversed(BACKUP_TABLES):
            if t in data:
                c.execute(f"DELETE FROM {t}")
        for t in BACKUP_TABLES:
            for row in data.get(t, []):
                cols = list(row.keys())
                c.execute(f"INSERT INTO {t}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                          tuple(row[k] for k in cols))
        c.execute("PRAGMA foreign_keys = ON")
