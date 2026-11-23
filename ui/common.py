"""Общие помощники интерфейса."""
from __future__ import annotations

import streamlit as st

from core import db
from core.calc import STATUS_LABEL, fmt


def user() -> dict | None:
    return st.session_state.get("user")


def is_admin() -> bool:
    u = user()
    return bool(u and u["role"] == "admin")


def secrets() -> dict:
    try:
        return {k: st.secrets[k] for k in st.secrets.keys()}
    except Exception:
        return {}


def goto(page: str, **state) -> None:
    """Колбэк для кнопок перехода между страницами."""
    st.session_state["nav"] = page
    for k, v in state.items():
        st.session_state[k] = v


def admin_only_note() -> None:
    if not is_admin():
        st.caption("🔒 Режим просмотра. Редактирование доступно только администратору.")


def pick_map(key: str = "map_pick", label: str = "🗺️ План", allow_all: bool = False):
    maps = db.maps()
    if not maps:
        st.warning("Нет загруженных планов.")
        return None
    opts = ([None] if allow_all else []) + [m["id"] for m in maps]
    names = {m["id"]: m["name"] for m in maps}
    if key in st.session_state and st.session_state[key] not in opts:
        del st.session_state[key]
    return st.selectbox(label, opts, key=key,
                        format_func=lambda i: "🏫 Вся школа" if i is None else names[i])


def pick_room(map_id: int, key: str = "room_pick", label: str = "🚪 Помещение"):
    rooms = db.rooms(map_id)
    if not rooms:
        st.info("На этом плане пока нет помещений.")
        return None
    ids = [r["id"] for r in rooms]
    names = {r["id"]: r["name"] for r in rooms}
    if key in st.session_state and st.session_state[key] not in ids:
        del st.session_state[key]
    return st.selectbox(label, ids, key=key, format_func=lambda i: names[i])


def kpi_row(agg: dict) -> None:
    c = st.columns(5)
    c[0].metric("Помещений", agg["rooms"])
    c[1].metric("Светильников", agg["n_lamps"], f"LED {agg['led_share'] * 100:.0f} %", delta_color="off")
    c[2].metric("Мощность", f"{fmt(agg['power_kw'], 2)} кВт")
    c[3].metric("Потребление", f"{fmt(agg['kwh_year'], 0)} кВт·ч/год", f"{fmt(agg['kwh_month'], 0)} в мес.",
                delta_color="off")
    c[4].metric("Стоимость", f"{fmt(agg['cost_year'], 0)} ₸/год", f"{fmt(agg['cost_month'], 0)} ₸/мес",
                delta_color="off")


def status_legend() -> str:
    return " · ".join(STATUS_LABEL[s] for s in ("ok", "low", "critical", "over", "no_lamps"))


TECH_LEGEND = "💡 LED — жёлтые · Люминесцентные — голубые · КЛЛ — зелёные · Накаливания — оранжевые · Галогенные — красные · ДРЛ — фиолетовые"
