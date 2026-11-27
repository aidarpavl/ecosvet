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


def test_daylight_formula():
    from core.calc import daylight
    room = {"area": 54, "height": 3, "win_len": 4.5, "room_type": "Кабинет", "x1": 0, "y1": 0, "x2": 9, "y2": 6}
    s = {"window_height": "1.8", "glazing_t": "0.65", "sky_angle": "70", "reflectance": "0.5",
         "ext_lux": "10000", "day_frac": "0.4"}
    d = daylight(room, s, 400)
    assert math.isclose(d["win_area"], 8.1)
    L, W = 9, 6
    expected = 0.65 * 8.1 * 70 / (2 * (L * W + L * 3 + W * 3) * 0.75)
    assert math.isclose(d["df_pct"], expected, rel_tol=1e-6)
    assert math.isclose(d["lux_nat"], expected * 100)
    assert 0 < d["daylight_pct"] <= 40


def test_openings_detected_on_plan():
    seed.ensure_seed()
    r = next(x for x in db.rooms() if x["name"] == "Кабинет №5")
    assert r["win_count"] >= 2 and r["win_len"] > 2
    gym = next(x for x in db.rooms() if x["name"] == "Спортзал")
    assert gym["win_count"] >= 10          # окна 1 этажа + «второй свет»
    total = sum(x["win_count"] for x in db.rooms())
    assert total > 100


def test_migration_from_v1():
    seed.ensure_seed()
    r = next(x for x in db.rooms() if x["name"] == "Кабинет №5")
    db.update_room(r["id"], {"name": "Кабинет 101", "openings": None, "win_count": 0})
    db.set_setting("data_version", 1)
    seed.migrate()
    r2 = db.get_room(r["id"])
    assert r2["name"] == "Кабинет №5" and r2["win_count"] >= 2


def test_add_lamp_gets_map_point_and_batch_apply():
    seed.ensure_seed()
    r = next(x for x in db.rooms() if x["name"] == "Кабинет №4")
    t = db.lamp_types()[0]
    lid = db.add_lamp(r["map_id"], r["id"], t["id"], None, None, 2)   # как из паспорта
    l = next(x for x in db.lamps(room_id=r["id"]) if x["id"] == lid)
    assert l["x"] is not None and min(r["x1"], r["x2"]) <= l["x"] <= max(r["x1"], r["x2"])
    n = len(db.lamps(room_id=r["id"]))
    db.apply_lamp_changes([{"map_id": r["map_id"], "room_id": r["id"], "lamp_type_id": t["id"],
                            "x": r["x1"] + 5, "y": r["y1"] + 5, "qty": 1}], [lid])
    assert len(db.lamps(room_id=r["id"])) == n          # +1 и −1


def test_storage_persist_and_restore(tmp_path, monkeypatch):
    from core import storage
    seed.ensure_seed()
    monkeypatch.setattr(storage, "SNAP_PATH", str(tmp_path / "snap.json"))
    r = db.rooms()[0]
    db.update_room(r["id"], {"note": "проверка сохранения"})
    ok, _ = storage.persist({})
    assert ok and not db.DIRTY["flag"]
    db.update_room(r["id"], {"note": "изменено"})
    assert storage.restore({}) == "локальный снимок"
    assert db.get_room(r["id"])["note"] == "проверка сохранения"
    assert storage.mode({}) == "local" and storage.mode({"GITHUB_TOKEN": "x", "GITHUB_REPO": "a/b"}) == "github"
