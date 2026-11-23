"""Калькулятор экономии: сценарии, инвестиции, окупаемость."""
import pandas as pd
import streamlit as st

from core import db, service
from core.calc import fmt, simulate
from core.export import to_excel
from ui.common import pick_map


def render():
    st.markdown("## 💰 Как сэкономить на электричестве")
    map_id = pick_map("sav_map", allow_all=True)
    metrics = service.compute_all(map_id)
    s, led = db.get_settings(), service.led_types()
    with st.expander("⚙️ Параметры сценариев", expanded=True):
        c = st.columns(5)
        to_norm = c[0].checkbox("LED: довести до нормы", True,
                                help="При замене добавляются светильники, если помещение ниже нормы")
        sensor_pct = c[1].slider("Датчики: −% времени", 10, 60, 30)
        sensor_price = c[2].number_input("Цена датчика, ₸", 0, 100000, 6000, 500)
        daylight_pct = c[3].slider("Дневной свет: −%", 5, 40, 15)
        hours_cut = c[4].slider("Выключать раньше, ч/день", 0.0, 3.0, 1.0, 0.5)
    kw = dict(to_norm=to_norm, sensor_pct=sensor_pct, sensor_price=sensor_price, daylight_pct=daylight_pct)
    scen = {
        "1. Замена на LED": simulate(metrics, led, s, led=True, **kw),
        "2. Датчики движения": simulate(metrics, led, s, sensors=True, **kw),
        "3. Дневной свет": simulate(metrics, led, s, daylight=True, **kw),
        f"4. Выключение на {hours_cut:g} ч раньше": simulate(metrics, led, s, hours_cut=hours_cut, **kw),
        "5. Комплекс (1+2+3+4)": simulate(metrics, led, s, led=True, sensors=True, daylight=True,
                                         hours_cut=hours_cut, **kw),
    }
    df = pd.DataFrame([{"Сценарий": k, "Экономия, %": round(v["save_pct"], 1),
                        "Экономия, кВт·ч/год": round(v["save_kwh"]), "Экономия, ₸/год": round(v["save_tg"]),
                        "Инвестиции, ₸": round(v["invest"]), "Окупаемость, лет": round(v["payback"], 1),
                        "CO₂, т/год": round(v["co2"] / 1000, 2)} for k, v in scen.items()])
    best = scen["5. Комплекс (1+2+3+4)"]
    c = st.columns(4)
    c[0].metric("Сейчас", f"{fmt(best['kwh_before'], 0)} кВт·ч/год")
    c[1].metric("После комплекса", f"{fmt(best['kwh_after'], 0)} кВт·ч/год", f"−{best['save_pct']:.0f} %",
                delta_color="inverse")
    c[2].metric("Экономия", f"{fmt(best['save_tg'], 0)} ₸/год")
    c[3].metric("Окупаемость", f"{fmt(best['payback'], 1)} лет", f"инвестиции {fmt(best['invest'], 0)} ₸",
                delta_color="off")
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.bar_chart(df.set_index("Сценарий")["Экономия, ₸/год"], color="#0f9d58", horizontal=True)
    st.caption("Сценарии 2–4 без затрат или с минимальными затратами; эффекты в комплексе не складываются, "
               "а перемножаются (после замены на LED каждый час работы дешевле).")

    pick = st.selectbox("Детализация по помещениям", list(scen))
    rows = pd.DataFrame(scen[pick]["rows"]).drop(columns=["room_id", "map_id"])
    rows = rows.sort_values("Экономия, ₸/год", ascending=False)
    st.dataframe(rows.round(1), hide_index=True, use_container_width=True, height=380)
    st.download_button("⬇️ Сценарии (Excel)", to_excel({"Сценарии": df, pick[:28]: rows.round(2)}),
                       "ecosvet_savings.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
