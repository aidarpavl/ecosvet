"""Отзывы пользователей администрации об электроэнергии и экономии."""
import pandas as pd
import streamlit as st

from core import db
from ui.common import is_admin, user

TOPICS = ["💡 Освещение / электроэнергия", "💰 Идея по экономии", "⚠️ Проблема (свет горит зря, не работает)",
          "📝 Предложение администрации"]
STATUSES = ["новый", "в работе", "решено"]


def render():
    st.markdown("## 💬 Отзывы и предложения для администрации")
    u = user()
    with st.expander("✍️ Оставить отзыв", expanded=not is_admin()):
        maps = db.maps()
        c = st.columns(2)
        map_id = c[0].selectbox("План (необязательно)", [None] + [m["id"] for m in maps], key="fb_map",
                                format_func=lambda i: "—" if i is None else next(m["name"] for m in maps if m["id"] == i))
        rooms = db.rooms(map_id) if map_id else []
        room_id = c[1].selectbox("Помещение (необязательно)", [None] + [r["id"] for r in rooms], key=f"fb_room_{map_id}",
                                 format_func=lambda i: "—" if i is None else next(r["name"] for r in rooms if r["id"] == i))
        with st.form("fb", clear_on_submit=True):
            c = st.columns(2)
            topic = c[0].selectbox("Тема", TOPICS)
            rating = c[1].slider("Оценка энергосбережения в школе", 1, 5, 3)
            text = st.text_area("Ваш отзыв", placeholder="Например: в кабинете 203 мигают лампы; в коридоре свет горит весь день…")
            if st.form_submit_button("Отправить", type="primary"):
                if len(text.strip()) < 5:
                    st.error("Напишите хотя бы пару слов.")
                else:
                    db.add_feedback(u["id"], map_id, room_id, topic, rating, text.strip())
                    st.success("Спасибо! Отзыв отправлен администрации.")

    items = db.feedback_list(None if is_admin() else u["id"])
    if is_admin() and items:
        c = st.columns(4)
        c[0].metric("Всего отзывов", len(items))
        c[1].metric("Новых", sum(1 for f in items if f["status"] == "новый"))
        c[2].metric("Средняя оценка", f"{sum(f['rating'] or 0 for f in items) / len(items):.1f} / 5")
        c[3].metric("Решено", sum(1 for f in items if f["status"] == "решено"))
        st.dataframe(pd.DataFrame(items)[["created_at", "username", "topic", "map_name", "room_name", "rating",
                                          "status", "text"]], hide_index=True, use_container_width=True)
    st.markdown("### " + ("Все отзывы" if is_admin() else "Мои отзывы"))
    if not items:
        st.info("Отзывов пока нет.")
    for f in items:
        icon = {"новый": "🆕", "в работе": "🔧", "решено": "✅"}.get(f["status"], "")
        where = " · ".join(x for x in (f["map_name"], f["room_name"]) if x)
        with st.container(border=True):
            st.markdown(f"{icon} **{f['topic']}** · {'⭐' * (f['rating'] or 0)} · {f['created_at']}"
                        + (f" · 📍 {where}" if where else "")
                        + (f" · 👤 {f['full_name'] or f['username']}" if is_admin() else ""))
            st.write(f["text"])
            if f["reply"]:
                st.success(f"**Ответ администрации ({f['replied_at']}):** {f['reply']}")
            if is_admin():
                with st.form(f"reply_{f['id']}"):
                    c = st.columns([4, 1, 1])
                    rep = c[0].text_input("Ответ", f["reply"] or "")
                    stt = c[1].selectbox("Статус", STATUSES, index=STATUSES.index(f["status"]) if f["status"] in STATUSES else 0)
                    if c[2].form_submit_button("Сохранить"):
                        db.reply_feedback(f["id"], rep, stt)
                        st.rerun()
                if st.button("🗑️ Удалить", key=f"fb_del_{f['id']}"):
                    db.delete_feedback(f["id"])
                    st.rerun()
