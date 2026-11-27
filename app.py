"""ЭкоСвет: как уменьшить расход электроэнергии в школе — точка входа Streamlit."""
import streamlit as st

st.set_page_config(page_title="ЭкоСвет — энергоаудит школы", page_icon="💡", layout="wide")

APP_VERSION = "1.5 (27.11.2026)"

from core import auth, db, seed, storage  # noqa: E402
from ui import (about, admin, ai_page, feedback, home, maps, passport, savings, school,  # noqa: E402
                swot_page)
from ui.common import is_admin, secrets, user  # noqa: E402

st.markdown("""
<style>
.eco-banner {background: linear-gradient(90deg,#0f9d58 0%,#34a853 45%,#fbbc05 100%); color:white;
  padding:14px 22px; border-radius:14px; margin-bottom:12px}
.eco-banner h1 {color:white; margin:0; font-size:1.7rem}
.eco-banner p {margin:2px 0 0 0; opacity:.95}
div[data-testid="stMetricValue"] {font-size:1.35rem}
</style>""", unsafe_allow_html=True)


@st.cache_resource
def bootstrap():
    seed.ensure_seed(secrets())          # пустая база → восстановление сохранённых данных (GitHub / снимок)
    return auth.ensure_admin(secrets())


bootstrap()


def banner():
    st.markdown(f"""<div class="eco-banner"><h1>💡 ЭкоСвет</h1>
    <p>Как уменьшить расход электроэнергии в школе · {db.get_settings()['school_name']}</p></div>""",
                unsafe_allow_html=True)


def login_page():
    banner()
    st.markdown("**Школьный энергоаудит освещения**: карты помещений, паспорта кабинетов и школы, "
                "расчёт освещённости и затрат, SWOT-анализ, рекомендации и ИИ-анализ.")
    t1, t2 = st.tabs(["🔑 Вход", "📝 Регистрация"])
    with t1, st.form("login"):
        u = st.text_input("Логин")
        p = st.text_input("Пароль", type="password")
        if st.form_submit_button("Войти", type="primary"):
            res = auth.login(u, p)
            if res:
                st.session_state["user"] = res
                if res["role"] == "admin":
                    full = auth.get_user(res["username"])
                    st.session_state["weak_admin_pw"] = auth.verify("admin123", full["pw_hash"], full["salt"])
                st.rerun()
            else:
                st.error("Неверный логин или пароль")
    with t2, st.form("register"):
        st.caption("После регистрации вы сможете просматривать все данные и оставлять отзывы администрации.")
        fn = st.text_input("Имя и фамилия (или класс)")
        u = st.text_input("Придумайте логин (латиница)")
        p1 = st.text_input("Пароль (не короче 6 символов)", type="password")
        p2 = st.text_input("Повторите пароль", type="password")
        if st.form_submit_button("Зарегистрироваться", type="primary"):
            if p1 != p2:
                st.error("Пароли не совпадают")
            else:
                ok, msg = auth.create_user(u, p1, fn)
                if ok:
                    st.session_state["user"] = auth.login(u, p1)
                    st.rerun()
                st.error(msg)


PAGES = {
    "🏠 Главная": home.render,
    "🗺️ Карты школы": maps.render,
    "📋 Паспорт кабинета": passport.render,
    "🏫 Паспорт школы": school.render,
    "💰 Экономия": savings.render,
    "📊 SWOT-анализ": swot_page.render,
    "🤖 ИИ-анализ": ai_page.render,
    "💬 Отзывы": feedback.render,
    "ℹ️ О проекте и правила": about.render,
}
ADMIN_PAGES = {"⚙️ Администрирование": admin.render}


def storage_status():
    st_ = storage.STATUS
    if storage.mode(secrets()) == "github":
        if st_["block_push"]:
            st.error("⚠️ Не удалось загрузить данные из GitHub при запуске — отправка в GitHub приостановлена.")
        elif st_["last_error"]:
            st.warning(f"GitHub: {st_['last_error']}  \nПроверка: «Администрирование → Резервная копия → "
                       "🔌 Проверить подключение к GitHub».")
        else:
            st.caption(f"☁️ Данные сохраняются в GitHub · последнее сохранение: {st_['last_ok'] or '—'}")
    else:
        st.caption("💾 Данные сохраняются только на сервере. На Streamlit Cloud они сбросятся при перезапуске — "
                   "настройте GITHUB_TOKEN и GITHUB_REPO (см. README).")


def main():
    storage.flush_if_dirty(secrets())    # всё, что изменили на прошлом шаге, — в постоянное хранилище
    if not user():
        login_page()
        return
    u = user()
    pages = {**PAGES, **(ADMIN_PAGES if is_admin() else {})}
    if st.session_state.get("nav") not in pages:
        st.session_state["nav"] = "🏠 Главная"
    with st.sidebar:
        st.markdown(f"### 💡 ЭкоСвет\n👤 **{u['full_name'] or u['username']}**  \n"
                    f"{'🛡️ Администратор' if is_admin() else '👁️ Просмотр'}")
        st.radio("Навигация", list(pages), key="nav", label_visibility="collapsed")
        if is_admin() and st.session_state.get("weak_admin_pw"):
            st.warning("Пароль администратора по умолчанию! Смените его в «Администрирование → Пользователи».")
        if is_admin():
            if st.button("💾 Сохранить", type="primary", use_container_width=True, key="sidebar_save"):
                ok, msg = storage.persist(secrets(), force=True)
                (st.success if ok else st.warning)(msg)
            storage_status()
        st.caption(f"Версия {APP_VERSION}")
        if st.button("🚪 Выйти", use_container_width=True):
            st.session_state.clear()
            st.rerun()
    banner()
    pages[st.session_state["nav"]]()
    storage.flush_if_dirty(secrets())


main()
