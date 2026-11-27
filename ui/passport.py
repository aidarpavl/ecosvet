"""Паспорт кабинета (помещения): параметры, лампы, расчёты, рекомендации."""
import math

import pandas as pd
import streamlit as st

from core import db, service, storage
from core.calc import STATUS_LABEL, fmt
from core.export import lamps_df, metrics_df, to_excel
from core.swot import PRIO, room_recommendations
from ui.common import admin_only_note, is_admin, pick_map, pick_room, secrets


def render():
    ss = st.session_state
    # переход с карты: подставляем выбранные план и помещение
    if "pass_map" in ss:
        ss["pp_map"] = ss.pop("pass_map")
    if "pass_room" in ss:
        ss["pp_room_pending"] = ss.pop("pass_room")
    c1, c2 = st.columns(2)
    with c1:
        map_id = pick_map("pp_map")
    if map_id is None:
        return
    if "pp_room_pending" in ss:
        ss["pp_room"] = ss.pop("pp_room_pending")
    with c2:
        room_id = pick_room(map_id, "pp_room")
    if is_admin():
        with st.expander("➕ Добавить помещение без контура на карте"):
            with st.form("add_room_nomap"):
                n = st.text_input("Название")
                t = st.selectbox("Тип", list(db.norms()))
                a = st.number_input("Площадь, м²", 0.0, 2000.0, 50.0)
                if st.form_submit_button("Добавить") and n:
                    ss["pp_room_pending"] = db.add_room({"map_id": map_id, "name": n, "room_type": t, "area": a})
                    st.rerun()
    if room_id is None:
        return
    room = db.get_room(room_id)
    m = next(x for x in service.compute_all(map_id) if x["room_id"] == room_id)
    settings = db.get_settings()

    st.markdown(f"## 📋 Паспорт помещения: {room['name']}")
    st.caption(f"{db.get_map(map_id)['name']} · {room['room_type']} · {STATUS_LABEL[m['status']]} · "
               f"класс энергоэффективности **{m['eff_class']}**")
    admin_only_note()

    k = st.columns(6)
    k[0].metric("Площадь", f"{fmt(m['area'])} м²")
    k[1].metric("Светильников", m["n_lamps"])
    k[2].metric("Мощность", f"{m['power_w']:.0f} Вт", f"{fmt(m['power_kw'], 3)} кВт", delta_color="off")
    k[3].metric("Световой поток", f"{fmt(m['lumens'], 0)} лм")
    k[4].metric("Освещённость", f"{m['lux']:.0f} лк", f"{(m['norm_pct'] or 0) - 100:+.0f} % к норме {m['norm_lux']:.0f}")
    k[5].metric("Удельная мощность", f"{fmt(m['w_per_m2'])} Вт/м²")
    e = st.columns(4)
    e[0].metric("В день", f"{fmt(m['kwh_day'], 2)} кВт·ч", f"{fmt(m['cost_day'], 0)} ₸", delta_color="off")
    e[1].metric("В месяц", f"{fmt(m['kwh_month'], 1)} кВт·ч", f"{fmt(m['cost_month'], 0)} ₸", delta_color="off")
    e[2].metric("В год", f"{fmt(m['kwh_year'], 0)} кВт·ч", f"{fmt(m['cost_year'], 0)} ₸", delta_color="off")
    e[3].metric("CO₂ в год", f"{fmt(m['co2_year'], 0)} кг")
    st.markdown("**🪟 Естественное освещение** (окна и двери распознаны по плану)")
    d = st.columns(6)
    d[0].metric("Окон", m["win_count"], f"{fmt(m['win_len'], 1)} м по стене", delta_color="off")
    d[1].metric("Дверей", m["door_count"])
    d[2].metric("Площадь остекления", f"{fmt(m['win_area'], 1)} м²",
                f"СК 1:{1 / m['glazing_ratio']:.1f}" if m["glazing_ratio"] else "окон нет", delta_color="off")
    keo_delta = (f"норма {m['keo_norm']} % — {'✅ выполнена' if m['keo_ok'] else '❌ не выполнена'}"
                 if m["keo_norm"] is not None else "норма не задана")
    d[3].metric("КЕО", f"{m['df_pct']:.2f} %", keo_delta, delta_color="off")
    d[4].metric("Дневной свет", f"{m['lux_nat']:.0f} лк", f"днём всего {m['lux_day_total']:.0f} лк", delta_color="off")
    d[5].metric("Экономия от окон", f"{m['daylight_pct']:.0f} %", f"≈ {fmt(m['cost_year'] * m['daylight_pct'] / 100, 0)} ₸/год",
                delta_color="off")
    if m["need_lamps"] is not None and m["main_lamp"]:
        st.caption(f"По норме {m['norm_lux']:.0f} лк нужно ≈ **{m['need_lamps']}** светильников «{m['main_lamp']}» "
                   f"(сейчас {m['n_lamps']}). Формула: N = ⌈E·S / (Φ·U·MF)⌉, U={settings['util_factor']}, "
                   f"MF={settings['maint_factor']}. Тариф {settings['tariff']} ₸/кВт·ч.")

    t1, t2, t3 = st.tabs(["⚙️ Параметры", "💡 Лампы", "✅ Рекомендации"])
    with t1:
        params_tab(room, map_id)
    with t2:
        lamps_tab(room, m)
    with t3:
        for i, r in enumerate(room_recommendations(m, service.led_types(), settings), 1):
            st.markdown(f"{i}. {PRIO[r['prio']]} — {r['text']}")

    xl = to_excel({"Паспорт": metrics_df([m]).T.reset_index().rename(columns={"index": "Показатель", 0: "Значение"}),
                   "Светильники": lamps_df([m])})
    st.download_button("⬇️ Скачать паспорт (Excel)", xl, f"passport_{room['name']}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def params_tab(room, map_id):
    dis = not is_admin()
    types = list(db.norms())
    with st.form(f"room_form_{room['id']}"):
        c = st.columns(3)
        name = c[0].text_input("Название", room["name"], disabled=dis)
        rtype = c[1].selectbox("Тип помещения", types, index=types.index(room["room_type"]) if room["room_type"] in types else 0,
                               disabled=dis)
        area = c[2].number_input("Площадь, м²", 0.0, 5000.0, float(room["area"] or 0), 0.1, disabled=dis)
        c = st.columns(3)
        height = c[0].number_input("Высота потолка, м", 2.0, 15.0, float(room["height"] or 3), 0.1, disabled=dis)
        hours = c[1].number_input("Часов освещения в день", 0.0, 24.0, float(room["hours_per_day"] or 0), 0.5, disabled=dis)
        days = c[2].number_input("Дней в месяц", 0.0, 31.0, float(room["days_per_month"] or 0), 1.0, disabled=dis)
        c = st.columns(3)
        months = c[0].number_input("Месяцев в году", 0.0, 12.0, float(room["months_per_year"] or 0), 1.0, disabled=dis)
        windows = c[1].checkbox("Есть окна (дневной свет)", bool(room["windows"]), disabled=dis)
        sensor = c[2].checkbox("Есть датчик движения / таймер", bool(room["has_sensor"]), disabled=dis)
        st.markdown("**🪟 Окна и двери** (заполняются распознаванием по плану; можно поправить вручную)")
        c = st.columns(4)
        win_count = c[0].number_input("Окон, шт", 0, 200, int(room["win_count"] or 0), disabled=dis)
        win_len = c[1].number_input("Суммарная ширина окон, м", 0.0, 500.0, float(room["win_len"] or 0), 0.1, disabled=dis)
        win_area = c[2].number_input("Площадь остекления, м² (0 = ширина × высота окна)", 0.0, 1000.0,
                                     float(room["win_area"] or 0), 0.1, disabled=dis)
        door_count = c[3].number_input("Дверей, шт", 0, 50, int(room["door_count"] or 0), disabled=dis)
        note = st.text_area("Примечание", room["note"] or "", disabled=dis)
        with st.expander("Контур на карте (пиксели плана)"):
            cc = st.columns(4)
            box = [cc[i].number_input(lbl, value=float(room[k] or 0), disabled=dis, key=f"{k}_{room['id']}")
                   for i, (lbl, k) in enumerate([("x1", "x1"), ("y1", "y1"), ("x2", "x2"), ("y2", "y2")])]
        if st.form_submit_button("💾 Сохранить", type="primary", disabled=dis):
            upd = {"name": name, "room_type": rtype, "area": area, "height": height, "hours_per_day": hours,
                   "days_per_month": days, "months_per_year": months, "windows": int(windows),
                   "has_sensor": int(sensor), "note": note, "win_count": win_count, "win_len": win_len,
                   "win_area": win_area, "door_count": door_count}
            if any(box):
                upd.update(dict(zip(("x1", "y1", "x2", "y2"), box)))
            db.update_room(room["id"], upd)
            st.success("Сохранено")
            st.rerun()
    if is_admin():
        if room["x1"] is not None and st.button("🔍 Распознать окна и двери по плану заново"):
            r = service.detect_room(room)
            st.success(f"Найдено окон: {r.get('win_count', 0)}, дверей: {r.get('door_count', 0)}")
            st.rerun()
        with st.popover("🗑️ Удалить помещение"):
            st.warning("Будут удалены помещение и все его лампы.")
            if st.button("Да, удалить", type="primary", key=f"del_room_{room['id']}"):
                db.delete_room(room["id"])
                st.rerun()


def lamps_tab(room, m):
    types = db.lamp_types()
    names = {t["id"]: t["name"] for t in types}
    by_name = {t["name"]: t for t in types}
    lamps = db.lamps(room_id=room["id"])
    df = pd.DataFrame([{"id": l["id"], "Светильник": l["type_name"], "Кол-во": int(l["qty"]),
                        "Вт/шт": l["watts"], "лм/шт": l["lumens"], "Вт всего": l["watts"] * l["qty"],
                        "кВт всего": round(l["watts"] * l["qty"] / 1000, 3), "лм всего": l["lumens"] * l["qty"],
                        "На карте": "📍" if l["x"] is not None else "—"} for l in lamps],
                      columns=["id", "Светильник", "Кол-во", "Вт/шт", "лм/шт", "Вт всего", "кВт всего", "лм всего", "На карте"])
    # Сводка по типам
    if lamps:
        g = df.groupby("Светильник").agg({"Кол-во": "sum", "Вт всего": "sum", "лм всего": "sum"}).reset_index()
        g["кВт всего"] = g["Вт всего"] / 1000
        st.markdown("**Сводка по типам ламп**")
        st.dataframe(g, hide_index=True, use_container_width=True)
    if not is_admin():
        st.dataframe(df.drop(columns=["id"]), hide_index=True, use_container_width=True)
        return
    st.markdown("**Редактирование** (меняйте тип и количество, удаляйте строки, добавляйте новые — они сами встанут на карту). Затем нажмите «💾 Сохранить лампы»")
    ver = st.session_state.get(f"lamps_ver_{room['id']}", 0)   # новая версия → таблица сбрасывается после сохранения
    if "lamps_saved_msg" in st.session_state:
        st.success(st.session_state.pop("lamps_saved_msg"))
    edited = st.data_editor(
        df, key=f"lamps_ed_{room['id']}_{ver}", num_rows="dynamic", hide_index=True, use_container_width=True,
        disabled=["id", "Вт/шт", "лм/шт", "Вт всего", "кВт всего", "лм всего", "На карте"],
        column_config={"Светильник": st.column_config.SelectboxColumn(options=list(by_name), required=True),
                       "Кол-во": st.column_config.NumberColumn(min_value=1, max_value=500, step=1, required=True)})
    if st.button("💾 Сохранить лампы", type="primary"):
        old_ids = {l["id"] for l in lamps}
        keep = set()
        for _, row in edited.iterrows():
            t = by_name.get(row["Светильник"])
            qty = row["Кол-во"]
            if t is None or qty is None or (isinstance(qty, float) and math.isnan(qty)):
                continue
            rid = row["id"]
            if rid is not None and not (isinstance(rid, float) and math.isnan(rid)) and int(rid) in old_ids:
                keep.add(int(rid))
                db.update_lamp(int(rid), t["id"], int(qty))
            else:
                db.add_lamp(room["map_id"], room["id"], t["id"], None, None, int(qty))
        for lid in old_ids - keep:
            db.delete_lamp(lid)
        ok, msg = storage.persist(secrets())
        st.session_state[f"lamps_ver_{room['id']}"] = ver + 1
        st.session_state["lamps_saved_msg"] = "✅ Лампы сохранены и видны на карте. " + msg
        st.rerun()
    with st.form(f"quick_add_{room['id']}"):
        c = st.columns([3, 1, 1])
        tid = c[0].selectbox("Быстро добавить", list(names), format_func=names.get)
        q = c[1].number_input("Кол-во", 1, 500, 1)
        if c[2].form_submit_button("➕ Добавить"):
            db.add_lamp(room["map_id"], room["id"], tid, None, None, q)
            ok, msg = storage.persist(secrets())
            st.session_state[f"lamps_ver_{room['id']}"] = ver + 1
            st.session_state["lamps_saved_msg"] = "✅ Лампа добавлена и поставлена на карту. " + msg
            st.rerun()
    st.caption("💡 Лампы, добавленные здесь, сами ставятся на свободное место в контуре помещения. "
               "Точно расставить их можно на «Карты школы» → «✏️ Карандаш» / «🧽 Ластик» → «💾 Сохранить изменения».")
