"""Экспорт паспортов в Excel/CSV."""
from __future__ import annotations

import io

import pandas as pd

from .calc import STATUS_LABEL

PASSPORT_COLS = {
    "name": "Помещение", "room_type": "Тип", "area": "Площадь, м²", "n_lamps": "Светильников, шт",
    "led_share": "Доля LED", "power_w": "Мощность, Вт", "power_kw": "Мощность, кВт", "lumens": "Поток, лм",
    "lux": "Освещённость, лк", "norm_lux": "Норма, лк", "norm_pct": "% нормы", "status": "Статус",
    "eff_class": "Класс", "w_per_m2": "Вт/м²", "hours_per_day": "Часов/день", "days_per_month": "Дней/мес",
    "months_per_year": "Мес/год", "kwh_day": "кВт·ч/день", "kwh_month": "кВт·ч/мес", "kwh_year": "кВт·ч/год",
    "cost_day": "₸/день", "cost_month": "₸/мес", "cost_year": "₸/год", "co2_year": "CO₂, кг/год",
    "win_count": "Окон", "win_len": "Ширина окон, м", "win_area": "Остекление, м²", "door_count": "Дверей",
    "df_pct": "КЕО, %", "lux_nat": "Дневной свет, лк", "daylight_pct": "Экономия от окон, %",
}


def metrics_df(metrics: list[dict], map_names: dict[int, str] | None = None) -> pd.DataFrame:
    rows = []
    for m in metrics:
        r = {"План": (map_names or {}).get(m["map_id"], "")} if map_names else {}
        for k, v in PASSPORT_COLS.items():
            val = m.get(k)
            if k == "status":
                val = STATUS_LABEL.get(val, val)
            elif k == "led_share":
                val = round((val or 0) * 100)
            elif isinstance(val, float):
                val = round(val, 2)
            r[v] = val
        rows.append(r)
    return pd.DataFrame(rows)


def lamps_df(metrics: list[dict]) -> pd.DataFrame:
    rows = []
    for m in metrics:
        for l in m["lamps"]:
            q = int(l.get("qty") or 1)
            rows.append({"Помещение": m["name"], "Светильник": l.get("type_name"), "Технология": l.get("tech"),
                         "Кол-во": q, "Вт/шт": l["watts"], "Вт всего": l["watts"] * q,
                         "кВт всего": round(l["watts"] * q / 1000, 3), "лм/шт": l["lumens"],
                         "лм всего": l["lumens"] * q, "X": l.get("x"), "Y": l.get("y")})
    return pd.DataFrame(rows)


def to_excel(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            df.to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 50)
    return buf.getvalue()
