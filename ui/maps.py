"""Интерактивные карты: выбор плана, просмотр, «карандаш» для администратора."""
import pandas as pd
import streamlit as st

from core import db, mapdraw, service
from core.calc import STATUS_LABEL, fmt
from ui.common import TECH_LEGEND, goto, is_admin, pick_map, status_legend

try:
    from streamlit_image_coordinates import streamlit_image_coordinates as image_coords
except ImportError:  # компонент не установлен — запасной режим
    image_coords = None

TOOLS = {
    "select": "🔎 Выбор помещения",
    "lamp": "✏️ Карандаш: поставить лампу",
    "erase": "🧽 Ластик: удалить лампу",
    "rect": "▭ Разметить помещение (2 клика)",
}


def _flash(msg, kind="success"):
    st.session_state["map_flash"] = (kind, msg)


def handle_click(tool: str, map_id: int, x: float, y: float):
    ss = st.session_state
    if tool == "select" or not is_admin():
        r = db.room_at(map_id, x, y)
        ss["sel_room"] = r["id"] if r else None
        return
    if tool == "lamp":
        r = db.room_at(map_id, x, y)
        if not r:
            _flash("Точка вне помещений. Кликните внутри контура или сначала разметьте помещение.", "warning")
            return
        db.add_lamp(map_id, r["id"], ss["pencil_type"], round(x, 1), round(y, 1), ss.get("pencil_qty", 1))
        ss["sel_room"] = r["id"]
        _flash(f"💡 Лампа добавлена в «{r['name']}»")
    elif tool == "erase":
        l = db.nearest_lamp(map_id, x, y)
        if l:
            db.delete_lamp(l["id"])
            _flash(f"🧽 Удалена лампа «{l['type_name']}»")
        else:
            _flash("Рядом с точкой нет ламп.", "warning")
    elif tool == "rect":
        if ss.get("rect_p1") is None:
            ss["rect_p1"] = (x, y)
            _flash("Первый угол отмечен. Кликните противоположный угол.", "info")
        else:
            (x1, y1), ss["rect_p1"] = ss["rect_p1"], None
            ss["rect_box"] = (round(min(x1, x), 1), round(min(y1, y), 1), round(max(x1, x), 1), round(max(y1, y), 1))


def render():
    ss = st.session_state
    ss.setdefault("click_nonce", 0)
    ss.setdefault("map_tool", "select")
    top = st.columns([2, 1, 1, 1, 1])
    with top[0]:
        map_id = pick_map("maps_map")
    if map_id is None:
        return
    show_rooms = top[1].toggle("Контуры", True)
    show_lamps = top[2].toggle("Лампы", True)
    show_labels = top[3].toggle("Подписи", True)
    disp_w = top[4].select_slider("Масштаб", [700, 850, 1000, 1150, 1300], value=ss.get("disp_w", 1000), key="disp_w")
    if ss.get("last_map") != map_id:
        ss["last_map"], ss["sel_room"], ss["rect_p1"], ss["rect_box"] = map_id, None, None, None

    mp = db.get_map(map_id)
    tool = "select"
    if is_admin():
        tc = st.columns([2, 2, 1])
        tool = tc[0].radio("Инструмент", list(TOOLS), format_func=TOOLS.get, horizontal=False, key="map_tool")
        if tool == "lamp":
            types = db.lamp_types()
            tc[1].selectbox("Тип лампы", [t["id"] for t in types], key="pencil_type",
                            format_func=lambda i: next(f"{t['name']} — {t['watts']:g} Вт, {t['lumens']:g} лм"
                                                       for t in types if t["id"] == i))
            tc[2].number_input("Кол-во в точке", 1, 50, 1, key="pencil_qty")
        elif tool == "rect":
            tc[1].radio("Режим", ["Новое помещение", "Перерисовать выбранное"], key="rect_mode")
            if ss.get("rect_p1"):
                tc[2].button("✖ Сбросить угол", on_click=lambda: ss.update(rect_p1=None))
        elif tool == "erase":
            tc[1].caption("Кликните рядом с лампой — будет удалена ближайшая (радиус 25 px).")
    else:
        st.caption("🔎 Кликните по помещению, чтобы увидеть его паспорт. Редактирование доступно только администратору.")

    if "map_flash" in ss:
        kind, msg = ss.pop("map_flash")
        getattr(st, kind)(msg)

    metrics = {m["room_id"]: m for m in service.compute_all(map_id)}
    rooms = db.rooms(map_id)
    img = mapdraw.render(mp, rooms, db.lamps(map_id=map_id), metrics, selected_room=ss.get("sel_room"),
                         pending=ss.get("rect_p1"), show_rooms=show_rooms, show_lamps=show_lamps,
                         show_labels=show_labels)
    W0, H0 = mapdraw.original_size(mp)

    left, right = st.columns([3, 1])
    with left:
        if image_coords:
            val = image_coords(img, width=disp_w, key=f"mapclick_{map_id}_{ss['click_nonce']}")
            if val:
                sig = (map_id, val.get("x"), val.get("y"), val.get("unix_time"))
                if sig != ss.get("last_click"):
                    ss["last_click"] = sig
                    dw = val.get("width") or disp_w
                    dh = val.get("height") or disp_w * H0 / W0
                    handle_click(tool, map_id, val["x"] * W0 / dw, val["y"] * H0 / dh)
                    ss["click_nonce"] += 1
                    st.rerun()
        else:
            st.image(img, width=disp_w)
            st.info("Для кликов по карте установите `streamlit-image-coordinates`. Пока — ручной ввод координат.")
            with st.form("manual_click"):
                c = st.columns(3)
                x = c[0].number_input("X (px плана)", 0.0, float(W0), W0 / 2)
                y = c[1].number_input("Y (px плана)", 0.0, float(H0), H0 / 2)
                if c[2].form_submit_button("Применить инструмент"):
                    handle_click(tool, map_id, x, y)
                    st.rerun()
        st.caption(f"Статус помещения: {status_legend()}  \n{TECH_LEGEND}")

    with right:
        if ss.get("rect_box") and is_admin():
            rect_form(map_id)
        sel = ss.get("sel_room")
        m = metrics.get(sel) if sel else None
        if m:
            st.markdown(f"#### 🚪 {m['name']}")
            st.caption(f"{m['room_type']} · {fmt(m['area'])} м²")
            st.markdown(f"**{STATUS_LABEL[m['status']]}**")
            st.metric("Освещённость", f"{m['lux']:.0f} лк", f"{(m['norm_pct'] or 0) - 100:+.0f} % к норме {m['norm_lux']:.0f}")
            st.metric("Светильников", m["n_lamps"], f"LED {m['led_share'] * 100:.0f} %", delta_color="off")
            st.metric("Мощность", f"{m['power_w']:.0f} Вт", f"{fmt(m['power_kw'], 3)} кВт", delta_color="off")
            st.metric("Стоимость", f"{fmt(m['cost_year'], 0)} ₸/год", f"{fmt(m['cost_month'], 0)} ₸/мес",
                      delta_color="off")
            st.button("📋 Открыть паспорт", type="primary", use_container_width=True, on_click=goto,
                      args=("📋 Паспорт кабинета",), kwargs={"pass_map": map_id, "pass_room": sel})
        else:
            st.info("Помещение не выбрано. Включите «🔎 Выбор» и кликните по плану.")

    st.markdown("##### Помещения на плане")
    df = pd.DataFrame([{"Помещение": m["name"], "Тип": m["room_type"], "м²": round(m["area"], 1),
                        "Ламп": m["n_lamps"], "Вт": round(m["power_w"]), "лк": round(m["lux"]),
                        "Норма": round(m["norm_lux"]), "Статус": STATUS_LABEL[m["status"]],
                        "кВт·ч/год": round(m["kwh_year"]), "₸/год": round(m["cost_year"])}
                       for m in metrics.values()])
    st.dataframe(df, hide_index=True, use_container_width=True)


def rect_form(map_id: int):
    ss = st.session_state
    box = ss["rect_box"]
    st.markdown("#### ▭ Новый контур")
    st.caption(f"x1={box[0]}, y1={box[1]}, x2={box[2]}, y2={box[3]}")
    if ss.get("rect_mode") == "Перерисовать выбранное" and ss.get("sel_room"):
        r = db.get_room(ss["sel_room"])
        if st.button(f"Применить к «{r['name']}»", type="primary"):
            db.update_room(r["id"], dict(zip(("x1", "y1", "x2", "y2"), box)))
            db.reassign_lamps_in_room_box(db.get_room(r["id"]))
            ss["rect_box"] = None
            _flash("Контур обновлён")
            st.rerun()
    else:
        with st.form("new_room"):
            name = st.text_input("Название", "Новый кабинет")
            rtype = st.selectbox("Тип", list(db.norms()))
            area = st.number_input("Площадь, м²", 0.0, 2000.0, 50.0)
            if st.form_submit_button("Создать помещение", type="primary"):
                rid = db.add_room({"map_id": map_id, "name": name, "room_type": rtype, "x1": box[0], "y1": box[1],
                                   "x2": box[2], "y2": box[3], "area": area})
                db.reassign_lamps_in_room_box(db.get_room(rid))
                ss["rect_box"], ss["sel_room"] = None, rid
                _flash(f"Помещение «{name}» создано. Теперь добавьте лампы карандашом.")
                st.rerun()
    if st.button("Отмена"):
        ss["rect_box"] = None
        st.rerun()
