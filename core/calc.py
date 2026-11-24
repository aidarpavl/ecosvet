"""Расчёты «ЭкоСвет». Все функции чистые: на входе словари, на выходе словари.

Формулы
-------
Мощность помещения:          P = Σ(Wᵢ·nᵢ),  Вт;  P_кВт = P / 1000
Световой поток:              Φ = Σ(Φᵢ·nᵢ),  лм
Средняя освещённость:        E = Φ · U · MF / S,  лк   (метод коэффициента использования)
Ламп до нормы:               N = ⌈E_норм · S / (Φ_лампы · U · MF)⌉
Потребление:                 W_день = P_кВт · ч/день;  W_мес = W_день · дней;  W_год = W_мес · месяцев
Стоимость:                   C = W · тариф
Выбросы CO₂:                 CO₂ = W_год · k_сети
Удельная мощность:           p = P / S, Вт/м²;  на 100 лк: p₁₀₀ = p / (E/100)

Естественное освещение (окна распознаются на плане, см. core/openings.py):
Площадь остекления:          Aок = Σ длина окон × высота окна
Световой коэффициент:        СК = Aок / S   (ориентир для классов 1:4 – 1:6)
КЕО (средний, формула BRE):  КЕО = T · Aок · θ° / (Aпов · (1 − R²)), % (θ — в градусах),
                             Aпов = 2(L·W + L·H + W·H) — площадь всех поверхностей помещения
Дневная освещённость:        Eест = КЕО/100 · Eнаруж
Экономия за счёт дневного света: доля = доля_светлых_часов · min(1, Eест / Eнорм)
"""
from __future__ import annotations

import math

LED = "LED"
TECHS = ["LED", "Люминесцентная", "КЛЛ", "Накаливания", "Галогенная", "ДРЛ"]

# Типы помещений, где эффективны датчики движения
SENSOR_TYPES = {"Коридор / рекреация", "Санузел", "Склад / подсобное", "Гардероб", "Техническое помещение",
                "Лаборантская", "Душевая / раздевалка"}

STATUS_LABEL = {
    "ok": "🟢 Норма",
    "low": "🟡 Ниже нормы",
    "critical": "🔴 Сильно ниже нормы",
    "over": "🔵 Пересвет (перерасход)",
    "no_lamps": "⚪ Нет ламп",
    "no_area": "⚪ Не указана площадь",
}

# Ориентировочные нормы КЕО при боковом освещении, % (сверьте с СП РК по естественному освещению)
KEO_NORMS = {"Кабинет": 1.5, "Лаборатория": 1.5, "Компьютерный класс": 1.5, "Мастерская / робототехника": 1.5,
             "Актовый зал": 1.0, "Спортзал": 1.0, "Учительская": 1.0, "Администрация": 1.0,
             "Медицинский кабинет": 1.0, "Столовая": 1.0, "Лаборантская": 1.0, "Пищеблок": 1.0,
             "Коридор / рекреация": 0.2, "Холл / вестибюль": 0.2}

EFF_CLASSES = [(3.0, "A"), (4.5, "B"), (6.0, "C"), (8.0, "D")]


def fnum(x, default=0.0) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def lamp_totals(lamps: list[dict]) -> dict:
    n = sum(int(fnum(l.get("qty"), 1)) for l in lamps)
    w = sum(fnum(l["watts"]) * int(fnum(l.get("qty"), 1)) for l in lamps)
    lm = sum(fnum(l["lumens"]) * int(fnum(l.get("qty"), 1)) for l in lamps)
    led_n = sum(int(fnum(l.get("qty"), 1)) for l in lamps if l.get("tech") == LED)
    return {"n": n, "watts": w, "lumens": lm, "led_n": led_n}


def illuminance(lumens: float, area: float, u: float, mf: float) -> float:
    return lumens * u * mf / area if area > 0 else 0.0


def lamps_needed(norm_lux: float, area: float, lamp_lumens: float, u: float, mf: float) -> int:
    if lamp_lumens <= 0 or area <= 0 or u <= 0 or mf <= 0:
        return 0
    return math.ceil(norm_lux * area / (lamp_lumens * u * mf) - 1e-9)


def energy(power_kw: float, hours_day: float, days_month: float, months_year: float) -> dict:
    d = power_kw * hours_day
    m = d * days_month
    return {"kwh_day": d, "kwh_month": m, "kwh_year": m * months_year}


def eff_class(w_per_m2_100lx: float | None) -> str:
    if w_per_m2_100lx is None:
        return "—"
    for limit, cls in EFF_CLASSES:
        if w_per_m2_100lx <= limit:
            return cls
    return "E"


def status_of(pct: float | None, n: int, area: float) -> str:
    if area <= 0:
        return "no_area"
    if n == 0:
        return "no_lamps"
    if pct < 70:
        return "critical"
    if pct < 90:
        return "low"
    if pct > 150:
        return "over"
    return "ok"


def daylight(room: dict, settings: dict, norm_lux: float) -> dict:
    """Естественная освещённость помещения по окнам."""
    area = fnum(room.get("area"))
    h = fnum(room.get("height"), 3.0) or 3.0
    win_len = fnum(room.get("win_len"))
    win_area = fnum(room.get("win_area")) or win_len * fnum(settings.get("window_height"), 1.8)
    out = {"win_count": int(fnum(room.get("win_count"))), "win_len": win_len, "win_area": win_area,
           "door_count": int(fnum(room.get("door_count"))), "glazing_ratio": 0.0, "df_pct": 0.0,
           "lux_nat": 0.0, "daylight_pct": 0.0, "keo_norm": KEO_NORMS.get(room.get("room_type"))}
    if win_area <= 0 or area <= 0:
        out["keo_ok"] = None if out["keo_norm"] is None else False
        return out
    k = 1.0
    if room.get("x1") is not None and room.get("y2") is not None:
        wpx, hpx = abs(fnum(room["x2"]) - fnum(room["x1"])), abs(fnum(room["y2"]) - fnum(room["y1"]))
        k = wpx / hpx if wpx > 0 and hpx > 0 else 1.0
    L = math.sqrt(area * k)
    W = area / L
    a_tot = 2 * (L * W + L * h + W * h)
    T, theta = fnum(settings.get("glazing_t"), 0.65), fnum(settings.get("sky_angle"), 70)
    R = fnum(settings.get("reflectance"), 0.5)
    df = T * win_area * theta / (a_tot * (1 - R * R))   # θ в градусах → результат сразу в %
    lux_nat = df / 100 * fnum(settings.get("ext_lux"), 10000)
    share = min(1.0, lux_nat / norm_lux) if norm_lux > 0 else 0.0
    out.update(glazing_ratio=win_area / area, df_pct=df, lux_nat=lux_nat,
               daylight_pct=fnum(settings.get("day_frac"), 0.4) * share * 100,
               keo_ok=None if out["keo_norm"] is None else df >= out["keo_norm"])
    return out


def room_metrics(room: dict, lamps: list[dict], norms: dict, settings: dict) -> dict:
    """Полный набор показателей паспорта помещения."""
    u, mf = fnum(settings.get("util_factor"), 0.5), fnum(settings.get("maint_factor"), 0.8)
    tariff, co2k = fnum(settings.get("tariff"), 32), fnum(settings.get("co2_factor"), 0.9)
    area = fnum(room.get("area"))
    t = lamp_totals(lamps)
    p_kw = t["watts"] / 1000
    lux = illuminance(t["lumens"], area, u, mf)
    norm = fnum(norms.get(room.get("room_type")), 300)
    pct = lux / norm * 100 if norm else None
    e = energy(p_kw, fnum(room.get("hours_per_day")), fnum(room.get("days_per_month")),
               fnum(room.get("months_per_year")))
    # тип лампы с наибольшей долей — для расчёта «сколько нужно ламп»
    main = max(lamps, key=lambda l: fnum(l["lumens"]) * int(fnum(l.get("qty"), 1)), default=None)
    need = lamps_needed(norm, area, fnum(main["lumens"]), u, mf) if main else None
    wpm2 = t["watts"] / area if area > 0 else 0.0
    dl = daylight(room, settings, norm)
    w100 = wpm2 / (lux / 100) if lux > 0 else None
    return {
        "room_id": room.get("id"), "map_id": room.get("map_id"), "name": room.get("name"),
        "room_type": room.get("room_type"), "area": area,
        "windows": int(fnum(room.get("windows")) or fnum(room.get("win_count")) > 0),
        "has_sensor": int(fnum(room.get("has_sensor"))),
        "hours_per_day": fnum(room.get("hours_per_day")), "days_per_month": fnum(room.get("days_per_month")),
        "months_per_year": fnum(room.get("months_per_year")),
        "n_lamps": t["n"], "led_n": t["led_n"], "led_share": t["led_n"] / t["n"] if t["n"] else 0.0,
        "power_w": t["watts"], "power_kw": p_kw, "lumens": t["lumens"],
        "w_per_m2": wpm2, "w_per_m2_100lx": w100, "eff_class": eff_class(w100),
        "lux": lux, "norm_lux": norm, "norm_pct": pct,
        "main_lamp": main["type_name"] if main and "type_name" in main else (main or {}).get("name"),
        "need_lamps": need, "lack_lamps": (need - t["n"]) if (need is not None and main) else None,
        "status": status_of(pct, t["n"], area),
        **e,
        "cost_day": e["kwh_day"] * tariff, "cost_month": e["kwh_month"] * tariff,
        "cost_year": e["kwh_year"] * tariff, "co2_year": e["kwh_year"] * co2k,
        **dl, "lux_day_total": lux + dl["lux_nat"],
        "lamps": lamps,
    }


SUM_KEYS = ["area", "n_lamps", "led_n", "power_w", "power_kw", "lumens", "kwh_day", "kwh_month", "kwh_year",
            "cost_day", "cost_month", "cost_year", "co2_year"]


def aggregate(metrics: list[dict]) -> dict:
    agg = {k: sum(m[k] for m in metrics) for k in SUM_KEYS}
    agg["rooms"] = len(metrics)
    agg["led_share"] = agg["led_n"] / agg["n_lamps"] if agg["n_lamps"] else 0.0
    agg["w_per_m2"] = agg["power_w"] / agg["area"] if agg["area"] else 0.0
    for s in STATUS_LABEL:
        agg[f"st_{s}"] = sum(1 for m in metrics if m["status"] == s)
    return agg


# ---------------- экономия ----------------
def pick_led(room: dict, led_types: list[dict], settings: dict) -> dict | None:
    """Подбор LED-замены: спортзал/актовый — мощные светильники, маленькие помещения — LED-лампы, остальное — панели."""
    if not led_types:
        return None
    by_id = {t["id"]: t for t in led_types}
    rt, area = room.get("room_type", ""), fnum(room.get("area"))
    key = "led_highbay" if rt in ("Спортзал", "Актовый зал") else "led_small" if area < 12 else "led_default"
    t = by_id.get(int(fnum(settings.get(key), -1)))
    if t:
        return t
    target = 10000 if key == "led_highbay" else 1000 if key == "led_small" else 3500
    return min(led_types, key=lambda x: abs(fnum(x["lumens"]) - target))


def simulate(metrics: list[dict], led_types: list[dict], settings: dict, *, led=False, to_norm=True,  # noqa: C901
             sensors=False, sensor_pct=30.0, daylight=False, daylight_pct=15.0, hours_cut=0.0,
             sensor_price=6000.0) -> dict:
    """Сценарий экономии. Возвращает построчный результат и итоги."""
    u, mf = fnum(settings.get("util_factor"), 0.5), fnum(settings.get("maint_factor"), 0.8)
    tariff, co2k = fnum(settings.get("tariff"), 32), fnum(settings.get("co2_factor"), 0.9)
    rows = []
    for m in metrics:
        power_w, invest, new_lamps_note = m["power_w"], 0.0, ""
        if led and m["n_lamps"]:
            old = [l for l in m["lamps"] if l.get("tech") != LED]
            if old:
                keep_w = sum(fnum(l["watts"]) * int(fnum(l.get("qty"), 1)) for l in m["lamps"] if l.get("tech") == LED)
                keep_lm = sum(fnum(l["lumens"]) * int(fnum(l.get("qty"), 1)) for l in m["lamps"] if l.get("tech") == LED)
                old_lm = sum(fnum(l["lumens"]) * int(fnum(l.get("qty"), 1)) for l in old)
                need_lm = old_lm
                if to_norm and m["area"] > 0:
                    need_lm = max(old_lm, m["norm_lux"] * m["area"] / (u * mf) - keep_lm)
                t = pick_led({"room_type": m["room_type"], "area": m["area"]}, led_types, settings)
                if t:
                    n_new = max(1, math.ceil(need_lm / fnum(t["lumens"], 1) - 1e-9))
                    power_w = keep_w + n_new * fnum(t["watts"])
                    invest += n_new * fnum(t["price"])
                    new_lamps_note = f"{n_new} × {t['name']}"
        hours = max(m["hours_per_day"] - hours_cut, 0.0)
        if sensors and not m["has_sensor"] and m["room_type"] in SENSOR_TYPES and m["n_lamps"]:
            hours *= 1 - sensor_pct / 100
            invest += max(1, math.ceil(m["area"] / 30)) * sensor_price
        if daylight:
            pct = m.get("daylight_pct", 0.0) if m.get("win_area", 0) > 0 else (daylight_pct if m["windows"] else 0.0)
            hours *= 1 - pct / 100
        kwh_after = power_w / 1000 * hours * m["days_per_month"] * m["months_per_year"]
        save_kwh = m["kwh_year"] - kwh_after
        save_tg = save_kwh * tariff
        rows.append({
            "room_id": m["room_id"], "map_id": m["map_id"], "Помещение": m["name"], "Тип": m["room_type"],
            "Было, кВт·ч/год": m["kwh_year"], "Стало, кВт·ч/год": kwh_after,
            "Экономия, кВт·ч/год": save_kwh, "Экономия, ₸/год": save_tg,
            "CO₂, кг/год": save_kwh * co2k, "Инвестиции, ₸": invest,
            "Окупаемость, лет": (invest / save_tg) if save_tg > 0 and invest > 0 else 0.0,
            "Новые лампы": new_lamps_note,
        })
    tot_before = sum(r["Было, кВт·ч/год"] for r in rows)
    tot_save = sum(r["Экономия, кВт·ч/год"] for r in rows)
    tot_tg = sum(r["Экономия, ₸/год"] for r in rows)
    tot_inv = sum(r["Инвестиции, ₸"] for r in rows)
    return {
        "rows": rows,
        "kwh_before": tot_before, "kwh_after": tot_before - tot_save, "save_kwh": tot_save,
        "save_pct": tot_save / tot_before * 100 if tot_before else 0.0,
        "save_tg": tot_tg, "invest": tot_inv, "co2": tot_save * co2k,
        "payback": tot_inv / tot_tg if tot_tg > 0 and tot_inv > 0 else 0.0,
    }


def fmt(x, nd=1) -> str:
    """Число с пробелами-разделителями тысяч и запятой (рус. формат)."""
    if x is None:
        return "—"
    s = f"{x:,.{nd}f}".replace(",", " ").replace(".", ",")
    return s
