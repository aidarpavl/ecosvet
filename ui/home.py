import pandas as pd
import streamlit as st

from core import db, service
from core.calc import aggregate, fmt, simulate
from ui.common import goto, kpi_row


def render():
    metrics = service.compute_all()
    if not metrics:
        st.info("Данных пока нет.")
        return
    agg = aggregate(metrics)
    st.subheader("Энергопаспорт школы — кратко")
    kpi_row(agg)

    s = db.get_settings()
    full = simulate(metrics, service.led_types(), s, led=True, to_norm=True, sensors=True, daylight=True,
                    hours_cut=0.5)
    c1, c2, c3 = st.columns(3)
    c1.success(f"**Потенциал экономии:** −{full['save_pct']:.0f} %  \n≈ **{fmt(full['save_tg'], 0)} ₸ в год**")
    c2.warning(f"**Ниже нормы освещённости:** {agg['st_low'] + agg['st_critical']} помещ.  \n"
               f"Пересвет: {agg['st_over']} помещ.")
    c3.info(f"**Выбросы CO₂:** {fmt(agg['co2_year'] / 1000, 1)} т/год  \n"
            f"Снижение при модернизации: {fmt(full['co2'] / 1000, 1)} т/год")

    names = service.map_names()
    by_map = {}
    for m in metrics:
        by_map.setdefault(names.get(m["map_id"], "?"), []).append(m)
    df = pd.DataFrame([{"План": k, "₸/год": round(aggregate(v)["cost_year"]),
                        "кВт·ч/год": round(aggregate(v)["kwh_year"])} for k, v in by_map.items()]).set_index("План")
    a, b = st.columns([3, 2])
    with a:
        st.markdown("##### Стоимость освещения по планам, ₸/год")
        st.bar_chart(df["₸/год"], color="#34a853")
    with b:
        st.markdown("##### ТОП-5 потребителей")
        top = sorted(metrics, key=lambda m: -m["cost_year"])[:5]
        st.dataframe(pd.DataFrame([{"Помещение": m["name"], "₸/год": round(m["cost_year"]),
                                    "кВт": round(m["power_kw"], 2)} for m in top]),
                     hide_index=True, use_container_width=True)

    st.markdown("##### С чего начать")
    c = st.columns(4)
    c[0].button("🗺️ Открыть карты", on_click=goto, args=("🗺️ Карты школы",), use_container_width=True)
    c[1].button("🏫 Паспорт школы", on_click=goto, args=("🏫 Паспорт школы",), use_container_width=True)
    c[2].button("💰 Калькулятор экономии", on_click=goto, args=("💰 Экономия",), use_container_width=True)
    c[3].button("💬 Оставить отзыв", on_click=goto, args=("💬 Отзывы",), use_container_width=True)
