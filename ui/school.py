"""Паспорт школы по электроэнергии (освещение)."""
import pandas as pd
import streamlit as st

from core import db, service
from core.calc import aggregate, fmt
from core.export import lamps_df, metrics_df, to_excel
from core.swot import room_recommendations
from ui.common import kpi_row


def summary_rows(metrics, names):
    rows = []
    groups = {}
    for m in metrics:
        groups.setdefault(m["map_id"], []).append(m)
    for mid, ms in list(groups.items()) + [(None, metrics)]:
        a = aggregate(ms)
        rows.append({"План": names.get(mid, "🏫 ИТОГО ПО ШКОЛЕ"), "Помещений": a["rooms"],
                     "Площадь, м²": round(a["area"], 1), "Светильников": a["n_lamps"],
                     "Доля LED, %": round(a["led_share"] * 100), "Мощность, кВт": round(a["power_kw"], 2),
                     "Вт/м²": round(a["w_per_m2"], 1), "кВт·ч/день": round(a["kwh_day"], 1),
                     "кВт·ч/мес": round(a["kwh_month"]), "кВт·ч/год": round(a["kwh_year"]),
                     "₸/мес": round(a["cost_month"]), "₸/год": round(a["cost_year"]),
                     "CO₂, т/год": round(a["co2_year"] / 1000, 2),
                     "Ниже нормы": a["st_low"] + a["st_critical"], "Пересвет": a["st_over"]})
    return pd.DataFrame(rows)


def render():
    metrics = service.compute_all()
    names = service.map_names()
    s = db.get_settings()
    st.markdown(f"## 🏫 Энергетический паспорт школы (освещение)\n{s['school_name']}")
    st.caption(f"Тариф: **{s['tariff']} ₸/кВт·ч** · U = {s['util_factor']} · MF = {s['maint_factor']} · "
               f"CO₂: {s['co2_factor']} кг/кВт·ч")
    agg = aggregate(metrics)
    kpi_row(agg)

    summ = summary_rows(metrics, names)
    st.markdown("#### Итоги по планам")
    st.dataframe(summ, hide_index=True, use_container_width=True)

    c1, c2 = st.columns(2)
    techs = {}
    for m in metrics:
        for l in m["lamps"]:
            t = techs.setdefault(l["tech"], {"Светильников": 0, "кВт": 0.0})
            t["Светильников"] += l["qty"]
            t["кВт"] += l["watts"] * l["qty"] / 1000
    tdf = pd.DataFrame(techs).T
    with c1:
        st.markdown("##### Установленная мощность по технологиям, кВт")
        st.bar_chart(tdf["кВт"], color="#fbbc05")
    with c2:
        st.markdown("##### Статус освещённости помещений")
        st.bar_chart(pd.Series({"Норма": agg["st_ok"], "Ниже нормы": agg["st_low"], "Сильно ниже": agg["st_critical"],
                                "Пересвет": agg["st_over"], "Нет ламп": agg["st_no_lamps"]}), color="#34a853")

    st.markdown("#### Все помещения")
    flt = st.multiselect("Фильтр по планам", list(names), format_func=names.get)
    view = [m for m in metrics if not flt or m["map_id"] in flt]
    df = metrics_df(view, names)
    st.dataframe(df, hide_index=True, use_container_width=True, height=420)

    recs = []
    led = service.led_types()
    for m in metrics:
        for r in room_recommendations(m, led, s):
            recs.append({"План": names.get(m["map_id"]), "Помещение": m["name"], "Приоритет": r["prio"],
                         "Рекомендация": r["text"], "Эффект, ₸/год": round(r["effect"])})
    xl = to_excel({"Паспорт школы": summ, "Помещения": metrics_df(metrics, names), "Светильники": lamps_df(metrics),
                   "Рекомендации": pd.DataFrame(recs)})
    c = st.columns(3)
    c[0].download_button("⬇️ Паспорт школы (Excel)", xl, "ecosvet_passport_school.xlsx",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
    c[1].download_button("⬇️ Помещения (CSV)", metrics_df(metrics, names).to_csv(index=False).encode("utf-8-sig"),
                         "ecosvet_rooms.csv", "text/csv")
    c[2].download_button("⬇️ Резервная копия (JSON)", db.export_json().encode("utf-8"), "ecosvet_backup.json",
                         "application/json")
