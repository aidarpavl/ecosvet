"""Администрирование: настройки, каталог ламп, нормы, карты, пользователи, резервная копия."""
import time

import pandas as pd
import streamlit as st

from core import auth, db
from core.calc import TECHS
from ui.common import is_admin, user


def render():
    if not is_admin():
        st.error("Доступ только для администратора.")
        return
    st.markdown("## ⚙️ Администрирование")
    tabs = st.tabs(["💲 Тариф и коэффициенты", "💡 Каталог ламп", "📏 Нормы освещённости", "🗺️ Карты",
                    "👥 Пользователи", "💾 Резервная копия"])
    with tabs[0]:
        settings_tab()
    with tabs[1]:
        catalog_tab()
    with tabs[2]:
        norms_tab()
    with tabs[3]:
        maps_tab()
    with tabs[4]:
        users_tab()
    with tabs[5]:
        backup_tab()


def settings_tab():
    s = db.get_settings()
    led = [t for t in db.lamp_types() if t["tech"] == "LED"]
    ids = [t["id"] for t in led]
    nm = {t["id"]: t["name"] for t in led}

    def idx(key):
        try:
            return ids.index(int(float(s.get(key, -1))))
        except ValueError:
            return 0

    with st.form("settings"):
        name = st.text_input("Название школы", s["school_name"])
        c = st.columns(4)
        tariff = c[0].number_input("Тариф, ₸/кВт·ч", 0.0, 500.0, float(s["tariff"]), 0.1,
                                   help="Уточните действующий тариф для юрлиц/бюджетных организаций у энергоснабжающей компании")
        u = c[1].number_input("Коэф. использования U", 0.1, 1.0, float(s["util_factor"]), 0.05)
        mf = c[2].number_input("Коэф. эксплуатации MF", 0.3, 1.0, float(s["maint_factor"]), 0.05)
        co2 = c[3].number_input("CO₂, кг/кВт·ч", 0.0, 2.0, float(s["co2_factor"]), 0.05)
        st.markdown("**LED-замены для расчёта экономии**")
        c = st.columns(3)
        d = c[0].selectbox("Обычные помещения", ids, index=idx("led_default"), format_func=nm.get) if ids else None
        sm = c[1].selectbox("Маленькие (< 12 м²)", ids, index=idx("led_small"), format_func=nm.get) if ids else None
        hb = c[2].selectbox("Спортзал / актовый зал", ids, index=idx("led_highbay"), format_func=nm.get) if ids else None
        if st.form_submit_button("💾 Сохранить", type="primary"):
            for k, v in {"school_name": name, "tariff": tariff, "util_factor": u, "maint_factor": mf, "co2_factor": co2,
                         "led_default": d, "led_small": sm, "led_highbay": hb}.items():
                if v is not None:
                    db.set_setting(k, v)
            st.success("Сохранено")
    with st.form("bulk_hours"):
        st.markdown("**Массово изменить режим работы** (для всех помещений выбранного типа)")
        c = st.columns(4)
        rt = c[0].selectbox("Тип", list(db.norms()))
        h = c[1].number_input("Часов/день", 0.0, 24.0, 7.0, 0.5)
        dm = c[2].number_input("Дней/мес", 0.0, 31.0, 22.0, 1.0)
        my = c[3].number_input("Месяцев/год", 0.0, 12.0, 9.0, 1.0)
        if st.form_submit_button("Применить"):
            db.ex("UPDATE rooms SET hours_per_day=?, days_per_month=?, months_per_year=? WHERE room_type=?", (h, dm, my, rt))
            st.success(f"Обновлено для типа «{rt}»")


def catalog_tab():
    st.caption("Значения по умолчанию — типовые, ориентировочные. Укажите реальные данные с маркировки и ценники поставщиков.")
    types = db.lamp_types()
    df = pd.DataFrame(types, columns=["id", "name", "tech", "watts", "lumens", "life_hours", "price"])
    df["лм/Вт"] = (df["lumens"] / df["watts"]).round(1)
    ed = st.data_editor(df, num_rows="dynamic", hide_index=True, use_container_width=True, key="cat_ed",
                        disabled=["id", "лм/Вт"],
                        column_config={"name": "Название", "tech": st.column_config.SelectboxColumn("Технология", options=TECHS, required=True),
                                       "watts": st.column_config.NumberColumn("Вт", min_value=0.1),
                                       "lumens": st.column_config.NumberColumn("лм", min_value=1),
                                       "life_hours": st.column_config.NumberColumn("Срок службы, ч"),
                                       "price": st.column_config.NumberColumn("Цена, ₸")})
    if st.button("💾 Сохранить каталог", type="primary"):
        keep, errors = set(), []
        for _, r in ed.iterrows():
            if not r["name"] or pd.isna(r["watts"]) or pd.isna(r["lumens"]) or not r["tech"]:
                continue
            rid = None if pd.isna(r["id"]) else int(r["id"])
            keep.add(db.upsert_lamp_type({"id": rid, "name": r["name"], "tech": r["tech"], "watts": float(r["watts"]),
                                          "lumens": float(r["lumens"]),
                                          "life_hours": 0 if pd.isna(r["life_hours"]) else float(r["life_hours"]),
                                          "price": 0 if pd.isna(r["price"]) else float(r["price"])}))
        for t in types:
            if t["id"] not in keep and not db.delete_lamp_type(t["id"]):
                errors.append(t["name"])
        if errors:
            st.warning("Не удалены (используются в помещениях): " + ", ".join(errors))
        st.success("Каталог сохранён")
        st.rerun()


def norms_tab():
    st.caption("Нормы средней освещённости, лк. Сверьте с действующими санитарными правилами для объектов образования и СП РК.")
    df = pd.DataFrame([{"Тип помещения": k, "Норма, лк": v} for k, v in db.norms().items()])
    ed = st.data_editor(df, num_rows="dynamic", hide_index=True, use_container_width=True, key="norm_ed")
    if st.button("💾 Сохранить нормы", type="primary"):
        for _, r in ed.iterrows():
            if r["Тип помещения"] and not pd.isna(r["Норма, лк"]):
                db.set_norm(str(r["Тип помещения"]).strip(), float(r["Норма, лк"]))
        st.success("Нормы сохранены")
        st.rerun()


def maps_tab():
    for m in db.maps():
        with st.container(border=True):
            c = st.columns([3, 1, 1, 1])
            new = c[0].text_input("Название", m["name"], key=f"mn_{m['id']}")
            sort = c[1].number_input("Порядок", 0, 99, int(m["sort"] or 0), key=f"ms_{m['id']}")
            if c[2].button("💾", key=f"msave_{m['id']}"):
                db.rename_map(m["id"], new)
                db.ex("UPDATE maps SET sort=? WHERE id=?", (sort, m["id"]))
                st.rerun()
            with c[3].popover("🗑️"):
                st.warning("Удалятся все помещения и лампы этого плана!")
                if st.button("Удалить план", key=f"mdel_{m['id']}", type="primary"):
                    db.delete_map(m["id"])
                    st.rerun()
    st.markdown("#### ➕ Загрузить новый план")
    with st.form("upload_map", clear_on_submit=True):
        name = st.text_input("Название плана", "Новый план")
        f = st.file_uploader("Изображение плана (PNG/JPG)", type=["png", "jpg", "jpeg"])
        if st.form_submit_button("Загрузить", type="primary") and f:
            code = f"map{int(time.time())}"
            rel = f"data/maps/{code}.{f.name.rsplit('.', 1)[-1].lower()}"
            path = db.ROOT / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f.getvalue())
            db.add_map(code, name, rel)
            st.success("План добавлен. Откройте «Карты школы» и разметьте помещения инструментом ▭.")


def users_tab():
    me = user()
    with st.form("pw"):
        st.markdown("**Сменить мой пароль**")
        p1 = st.text_input("Новый пароль", type="password")
        p2 = st.text_input("Повторите", type="password")
        if st.form_submit_button("Сменить"):
            if len(p1) < 6 or p1 != p2:
                st.error("Пароль ≥ 6 символов и должен совпадать")
            else:
                auth.set_password(me["id"], p1)
                st.session_state["weak_admin_pw"] = False
                st.success("Пароль изменён")
    st.markdown("**Пользователи**")
    for u in auth.users():
        c = st.columns([2, 2, 1, 2, 1])
        c[0].write(f"**{u['username']}**")
        c[1].write(u["full_name"] or "—")
        c[2].write("🛡️ admin" if u["role"] == "admin" else "👁️ viewer")
        if u["id"] == me["id"]:
            c[3].caption("это вы")
            continue
        if u["role"] == "admin":
            if c[3].button("Сделать viewer", key=f"rv_{u['id']}"):
                auth.set_role(u["id"], "viewer")
                st.rerun()
        elif c[3].button("Сделать admin", key=f"ra_{u['id']}"):
            auth.set_role(u["id"], "admin")
            st.rerun()
        with c[4].popover("⋯"):
            np_ = st.text_input("Новый пароль", key=f"np_{u['id']}", type="password")
            if st.button("Сбросить пароль", key=f"rp_{u['id']}") and len(np_) >= 6:
                auth.set_password(u["id"], np_)
                st.success("Готово")
            if st.button("Удалить пользователя", key=f"du_{u['id']}"):
                auth.delete_user(u["id"])
                st.rerun()


def backup_tab():
    st.caption("На Streamlit Community Cloud файл базы может сбрасываться при перезапуске — регулярно скачивайте копию.")
    st.download_button("⬇️ Скачать резервную копию (JSON)", db.export_json().encode("utf-8"), "ecosvet_backup.json",
                       "application/json", type="primary")
    f = st.file_uploader("Восстановить из копии (JSON)", type=["json"])
    if f and st.button("♻️ Восстановить (текущие данные будут заменены)"):
        try:
            db.import_json(f.getvalue().decode("utf-8"))
            st.success("Данные восстановлены")
        except Exception as e:
            st.error(f"Ошибка: {e}")
    with st.popover("🧨 Сбросить к начальным данным"):
        st.warning("Удалит все карты, помещения, лампы, SWOT и отзывы. Пользователи сохранятся.")
        if st.button("Сбросить", type="primary"):
            from core import seed
            with db.conn() as c:
                for t in ["lamps", "rooms", "maps", "lamp_types", "norms", "swot_items", "feedback"]:
                    c.execute(f"DELETE FROM {t}")
            seed.seed()
            st.rerun()

