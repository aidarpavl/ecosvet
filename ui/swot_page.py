"""SWOT-анализ для экономии электроэнергии."""
import html

import streamlit as st

from core import db, service
from core.calc import aggregate
from core.swot import QUADRANTS, auto_swot
from ui.common import is_admin


def render():
    st.markdown("## 📊 SWOT-анализ энергосбережения школы")
    st.caption("Пункты с 🤖 сформированы автоматически из данных аудита; пункты с ✍️ добавлены администрацией.")
    metrics = service.compute_all()
    s = db.get_settings()
    auto = auto_swot(metrics, aggregate(metrics), service.led_types(), s)
    custom = db.swot_items()
    cols = st.columns(2)
    for i, (q, (title, bg)) in enumerate(QUADRANTS.items()):
        items = [f"🤖 {html.escape(t)}" for t in auto[q]] + \
                [f"✍️ {html.escape(c['text'])}" for c in custom if c["quadrant"] == q]
        lis = "".join(f"<li>{t}</li>" for t in items)
        with cols[i % 2]:
            st.markdown(f"<div style='background:{bg};padding:12px 16px;border-radius:12px;min-height:320px;"
                        f"margin-bottom:12px;color:#222'><h4 style='color:#222'>{title}</h4><ul>{lis}</ul></div>",
                        unsafe_allow_html=True)
    if is_admin():
        st.markdown("#### ✍️ Добавить свой пункт")
        with st.form("swot_add", clear_on_submit=True):
            c = st.columns([1, 3, 1])
            q = c[0].selectbox("Квадрант", list(QUADRANTS), format_func=lambda k: QUADRANTS[k][0])
            t = c[1].text_input("Текст")
            if c[2].form_submit_button("Добавить") and t.strip():
                db.add_swot(q, t.strip())
                st.rerun()
        for c in custom:
            a, b = st.columns([6, 1])
            a.write(f"**{c['quadrant']}** — {c['text']}")
            if b.button("🗑️", key=f"sw_del_{c['id']}"):
                db.delete_swot(c["id"])
                st.rerun()
    md = "\n\n".join(f"## {QUADRANTS[q][0]}\n" + "\n".join(f"- {t}" for t in auto[q] +
                     [c["text"] for c in custom if c["quadrant"] == q]) for q in QUADRANTS)
    st.download_button("⬇️ Скачать SWOT (Markdown)", md.encode("utf-8"), "ecosvet_swot.md", "text/markdown")
