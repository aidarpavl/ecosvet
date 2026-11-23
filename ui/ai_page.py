"""ИИ-анализ по помещению, по плану и по всей школе."""
import streamlit as st

from core import ai, db, service
from ui.common import pick_map, pick_room, secrets


def render():
    st.markdown("## 🤖 ИИ-анализ энергопотребления")
    sec = secrets()
    provider = ai.llm_available(sec)
    st.caption("Встроенный экспертный движок работает всегда. "
               + (f"Подключена внешняя модель: **{provider}** — можно получить развёрнутый отчёт."
                  if provider else "Чтобы подключить LLM, добавьте ANTHROPIC_API_KEY или OPENAI_API_KEY в secrets."))
    level = st.radio("Уровень анализа", ["🚪 Помещение", "🗺️ План (карта)", "🏫 Вся школа"], horizontal=True)
    s, led = db.get_settings(), service.led_types()
    names = service.map_names()

    if level.startswith("🚪"):
        c1, c2 = st.columns(2)
        with c1:
            map_id = pick_map("ai_map")
        if map_id is None:
            return
        with c2:
            room_id = pick_room(map_id, "ai_room")
        if room_id is None:
            return
        metrics = [m for m in service.compute_all(map_id) if m["room_id"] == room_id]
        title = metrics[0]["name"]
        report = ai.analyze_room(metrics[0], led, s)
    elif level.startswith("🗺️"):
        map_id = pick_map("ai_map2")
        if map_id is None:
            return
        metrics = service.compute_all(map_id)
        title = names[map_id]
        report = ai.analyze_group(title, metrics, led, s)
    else:
        metrics = service.compute_all()
        title = "вся школа"
        report = ai.analyze_group("вся школа", metrics, led, s, top=10)
        st.markdown("#### Сравнение планов")
        for mid, n in names.items():
            ms = [m for m in metrics if m["map_id"] == mid]
            if ms:
                avg = sum(ai.room_score(m) for m in ms) / len(ms)
                st.progress(min(int(avg), 100) / 100, text=f"{n}: {avg:.0f}/100 — {ai.grade(avg)}")

    st.markdown(report)
    key = f"llm_{level}_{title}"
    if provider and st.button("✨ Развёрнутый отчёт внешней ИИ-модели", type="primary"):
        with st.spinner("ИИ анализирует данные…"):
            text, msg = ai.llm_report(title, metrics, s, sec, report)
        st.session_state[key] = (text, msg)
    if key in st.session_state:
        text, msg = st.session_state[key]
        st.info(msg)
        if text:
            st.markdown("---")
            st.markdown(text)
            report = report + "\n\n---\n\n" + text
    st.download_button("⬇️ Скачать отчёт (Markdown)", report.encode("utf-8"), f"ecosvet_ai_{title}.md", "text/markdown")
