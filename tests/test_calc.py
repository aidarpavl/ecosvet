import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["ECOSVET_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")

from core import auth, db, seed, service  # noqa: E402
from core.calc import (aggregate, energy, illuminance, lamps_needed, room_metrics,  # noqa: E402
                       simulate)

S = {"tariff": "30", "util_factor": "0.5", "maint_factor": "0.8", "co2_factor": "1.0"}
LED = {"id": 1, "name": "LED 36", "tech": "LED", "watts": 36, "lumens": 3600, "price": 9000}
FLUO = {"type_name": "ЛПО", "tech": "Люминесцентная", "watts": 86, "lumens": 3200, "qty": 10, "price": 0}


def test_illuminance_and_need():
    assert illuminance(32000, 50, 0.5, 0.8) == 256
    assert lamps_needed(400, 50, 3200, 0.5, 0.8) == math.ceil(400 * 50 / (3200 * 0.4))
    assert lamps_needed(400, 0, 3200, 0.5, 0.8) == 0


def test_energy():
    e = energy(1.0, 6, 22, 9)
    assert e == {"kwh_day": 6, "kwh_month": 132, "kwh_year": 1188}


def test_room_metrics():
    room = {"id": 1, "map_id": 1, "name": "Каб", "room_type": "Кабинет", "area": 50, "hours_per_day": 6,
            "days_per_month": 22, "months_per_year": 9, "windows": 1, "has_sensor": 0}
    m = room_metrics(room, [FLUO], {"Кабинет": 400}, S)
    assert m["power_w"] == 860 and m["n_lamps"] == 10
    assert round(m["lux"]) == 256
    assert m["status"] == "critical"          # 64 % нормы
    assert m["need_lamps"] == 16
    assert math.isclose(m["kwh_year"], 0.86 * 6 * 22 * 9)
    assert math.isclose(m["cost_year"], m["kwh_year"] * 30)


def test_simulate_led_saves():
    room = {"id": 1, "map_id": 1, "name": "Каб", "room_type": "Кабинет", "area": 50, "hours_per_day": 6,
            "days_per_month": 22, "months_per_year": 9, "windows": 1, "has_sensor": 0}
    m = room_metrics(room, [FLUO], {"Кабинет": 400}, S)
    r = simulate([m], [LED], S, led=True, to_norm=False)
    assert r["save_kwh"] > 0 and r["invest"] == 9 * 9000   # 32000 лм / 3600 → 9 панелей
    r2 = simulate([m], [LED], S, daylight=True, daylight_pct=15)
    assert math.isclose(r2["save_pct"], 15)


def test_seed_and_auth():
    seed.ensure_seed()
    assert len(db.maps()) == 5
    ms = service.compute_all()
    assert len(ms) > 50
    agg = aggregate(ms)
    assert agg["n_lamps"] > 0 and agg["cost_year"] > 0
    assert auth.ensure_admin({}) is True
    assert auth.login("admin", "admin123")["role"] == "admin"
    ok, _ = auth.create_user("student1", "secret12", "Ученик")
    assert ok and auth.login("student1", "secret12")["role"] == "viewer"
    assert auth.login("student1", "wrong") is None


def test_room_at_and_backup():
    seed.ensure_seed()
    mp = db.maps()[0]
    r = db.rooms(mp["id"])[3]
    cx, cy = (r["x1"] + r["x2"]) / 2, (r["y1"] + r["y2"]) / 2
    assert db.room_at(mp["id"], cx, cy)["id"] == r["id"]
    n = len(db.lamps())
    db.import_json(db.export_json())
    assert len(db.lamps()) == n
