"""ИИ-анализ: встроенный экспертный движок (работает без интернета) + опциональная LLM (Anthropic / OpenAI)."""
from __future__ import annotations

import json
import os
from collections import Counter

from .calc import STATUS_LABEL, aggregate, fmt, simulate
from .swot import PRIO, room_recommendations

SYSTEM_PROMPT = (
    "Ты — инженер-энергоаудитор школы в Казахстане. На основе JSON-данных энергоаудита освещения "
    "напиши подробный аналитический отчёт на русском языке в Markdown: 1) оценка состояния, "
    "2) выявленные проблемы и источники нерационального потребления, 3) соответствие нормам освещённости "
    "и влияние на здоровье учащихся, 4) конкретные рекомендации с приоритетом и расчётом эффекта в кВт·ч и ₸, "
    "5) план действий по этапам, 6) краткий вывод. Используй только цифры из данных, не выдумывай. "
    "Денежные суммы — в тенге (₸)."
)


# ---------- оценка ----------
def room_score(m: dict) -> int:
    if not m["n_lamps"] or not m["area"]:
        return 0
    pct = m["norm_pct"] or 0
    norm_part = 40 * (1 - min(abs(pct - 110) / 110, 1)) if pct < 90 or pct > 150 else 40
    led_part = 30 * m["led_share"]
    cls_part = {"A": 20, "B": 16, "C": 11, "D": 6, "E": 2}.get(m["eff_class"], 0)
    extra = (5 if m["has_sensor"] else 0) + (5 if m["windows"] else 0)
    return int(round(norm_part + led_part + cls_part + extra))


def grade(score: float) -> str:
    return ("🏆 Отлично" if score >= 85 else "✅ Хорошо" if score >= 70 else
            "⚠️ Удовлетворительно" if score >= 50 else "❌ Неудовлетворительно")


def _lamp_summary(lamps: list[dict]) -> str:
    c = Counter()
    for l in lamps:
        c[l.get("type_name", "?")] += int(l.get("qty") or 1)
    return ", ".join(f"{n} × {t}" for t, n in c.most_common()) or "нет"


# ---------- помещение ----------
def analyze_room(m: dict, led_types, settings) -> str:
    sc = room_score(m)
    recs = room_recommendations(m, led_types, settings)
    lines = [
        f"### 🤖 ИИ-анализ помещения «{m['name']}»",
        f"**Итоговая оценка:** {sc}/100 — {grade(sc)}  ",
        f"**Статус освещённости:** {STATUS_LABEL[m['status']]}",
        "",
        "| Показатель | Значение |", "|---|---|",
        f"| Тип / площадь | {m['room_type']} / {fmt(m['area'])} м² |",
        f"| Светильники | {_lamp_summary(m['lamps'])} |",
        f"| Мощность | {fmt(m['power_w'], 0)} Вт ({fmt(m['power_kw'], 2)} кВт), {fmt(m['w_per_m2'])} Вт/м² |",
        f"| Световой поток | {fmt(m['lumens'], 0)} лм |",
        f"| Освещённость | {fmt(m['lux'], 0)} лк при норме {fmt(m['norm_lux'], 0)} лк "
        f"({fmt(m['norm_pct'] or 0, 0)} %) |",
        f"| Класс энергоэффективности | {m['eff_class']} |",
        f"| Режим | {fmt(m['hours_per_day'])} ч/день × {fmt(m['days_per_month'], 0)} дн. × {fmt(m['months_per_year'], 0)} мес. |",
        f"| Потребление | {fmt(m['kwh_day'], 2)} кВт·ч/день · {fmt(m['kwh_month'])} кВт·ч/мес · {fmt(m['kwh_year'], 0)} кВт·ч/год |",
        f"| Стоимость | {fmt(m['cost_month'], 0)} ₸/мес · **{fmt(m['cost_year'], 0)} ₸/год** |",
        f"| CO₂ | {fmt(m['co2_year'], 0)} кг/год |",
        f"| Окна / двери (по плану) | {m['win_count']} окон ({fmt(m['win_area'], 1)} м²) / {m['door_count']} дверей |",
        f"| Естественный свет | КЕО {m['df_pct']:.2f} %"
        + (f" (ориентир {m['keo_norm']} %)" if m['keo_norm'] is not None else "")
        + f", ≈ {m['lux_nat']:.0f} лк днём; вместе с лампами ≈ {m['lux_day_total']:.0f} лк |",
        "",
        "**Диагноз:**",
    ]
    diag = []
    if m["status"] in ("critical", "low"):
        diag.append(f"- недосвет: учащиеся работают при {m['lux']:.0f} лк вместо {m['norm_lux']:.0f} лк — повышенная нагрузка на зрение;")
    elif m["status"] == "over":
        diag.append("- пересвет: светильников больше, чем требуется — источник нерационального расхода;")
    elif m["status"] == "ok":
        diag.append("- освещённость в норме;")
    if m["led_share"] < 1 and m["n_lamps"]:
        diag.append(f"- {100 - m['led_share'] * 100:.0f} % светильников — устаревшие технологии;")
    if m["led_share"] == 1:
        diag.append("- все светильники светодиодные — хороший пример для других помещений;")
    if m.get("keo_ok") is False:
        diag.append("- естественного света недостаточно (мало окон или окна не распознаны);")
    elif m.get("daylight_pct", 0) >= 20:
        diag.append(f"- хороший дневной свет: при грамотном управлении освещением можно экономить ≈ {m['daylight_pct']:.0f} %;")
    lines += diag or ["- данных недостаточно для диагноза;"]
    lines += ["", "**Рекомендации:**"]
    lines += [f"{i}. {PRIO[r['prio']]} — {r['text']}" for i, r in enumerate(recs, 1)] or ["Замечаний нет."]
    return "\n".join(lines)


# ---------- план (карта) ----------
def analyze_group(title: str, metrics: list[dict], led_types, settings, top: int = 5) -> str:
    if not metrics:
        return f"### {title}\nНет помещений."
    agg = aggregate(metrics)
    scores = {m["room_id"]: room_score(m) for m in metrics}
    avg = sum(scores.values()) / len(scores)
    led = simulate(metrics, led_types, settings, led=True, to_norm=True)
    full = simulate(metrics, led_types, settings, led=True, to_norm=True, sensors=True, daylight=True, hours_cut=0.5)
    dls = simulate(metrics, led_types, settings, daylight=True)
    by_cost = sorted(metrics, key=lambda m: -m["cost_year"])[:top]
    worst = sorted([m for m in metrics if m["status"] in ("critical", "low")], key=lambda m: m["norm_pct"] or 0)[:top]
    best = sorted(metrics, key=lambda m: -scores[m["room_id"]])[:3]
    best_save = sorted(led["rows"], key=lambda r: -r["Экономия, ₸/год"])[:top]

    L = [f"### 🤖 ИИ-анализ: {title}",
         f"**Средняя оценка помещений:** {avg:.0f}/100 — {grade(avg)}", "",
         f"- Помещений: **{agg['rooms']}**, площадь {fmt(agg['area'], 0)} м², светильников **{agg['n_lamps']}** "
         f"(LED {agg['led_share'] * 100:.0f} %).",
         f"- Установленная мощность освещения: **{fmt(agg['power_kw'], 2)} кВт** ({fmt(agg['w_per_m2'])} Вт/м²).",
         f"- Потребление: {fmt(agg['kwh_day'], 1)} кВт·ч/день · {fmt(agg['kwh_month'], 0)} кВт·ч/мес · "
         f"**{fmt(agg['kwh_year'], 0)} кВт·ч/год**.",
         f"- Стоимость: {fmt(agg['cost_month'], 0)} ₸/мес · **{fmt(agg['cost_year'], 0)} ₸/год**; CO₂ {fmt(agg['co2_year'] / 1000, 2)} т/год.",
         f"- Окна по планам: **{sum(m['win_count'] for m in metrics)}** "
         f"({fmt(sum(m['win_area'] for m in metrics), 0)} м² остекления), дверей {sum(m['door_count'] for m in metrics)}; "
         f"помещений с КЕО ниже ориентира: {sum(1 for m in metrics if m.get('keo_ok') is False)}.",
         f"- Статусы: 🟢 {agg['st_ok']} · 🟡 {agg['st_low']} · 🔴 {agg['st_critical']} · 🔵 {agg['st_over']} · ⚪ {agg['st_no_lamps']}.",
         "", "**Крупнейшие потребители (₸/год):**"]
    L += [f"{i}. {m['name']} — {fmt(m['cost_year'], 0)} ₸ ({fmt(m['kwh_year'], 0)} кВт·ч, {_lamp_summary(m['lamps'])})"
          for i, m in enumerate(by_cost, 1)]
    if worst:
        L += ["", "**Наибольший недосвет (приоритет для здоровья учащихся):**"]
        L += [f"- {m['name']}: {m['lux']:.0f} из {m['norm_lux']:.0f} лк ({m['norm_pct']:.0f} %), "
              f"нужно ещё ≈ {max(m['lack_lamps'] or 0, 0)} светильник(ов)" for m in worst]
    L += ["", "**Лучшие помещения:** " + ", ".join(f"{m['name']} ({scores[m['room_id']]})" for m in best)]
    L += ["", "**Потенциал экономии:**",
          f"- Замена на LED с доведением до нормы: −{led['save_pct']:.0f} % = **{fmt(led['save_kwh'], 0)} кВт·ч / "
          f"{fmt(led['save_tg'], 0)} ₸ в год**, инвестиции {fmt(led['invest'], 0)} ₸, окупаемость {fmt(led['payback'], 1)} г.",
          f"- Дневной свет по окнам (КЕО): −{dls['save_pct']:.0f} % = **{fmt(dls['save_tg'], 0)} ₸/год** без затрат.",
          f"- Комплекс (LED + датчики + дневной свет + выключение на 0,5 ч раньше): −{full['save_pct']:.0f} % = "
          f"**{fmt(full['save_tg'], 0)} ₸/год**, {fmt(full['co2'] / 1000, 2)} т CO₂/год.",
          "", "**Где замена даст наибольший эффект:**"]
    L += [f"{i}. {r['Помещение']} — {fmt(r['Экономия, ₸/год'], 0)} ₸/год ({r['Новые лампы']})"
          for i, r in enumerate(best_save, 1) if r["Экономия, ₸/год"] > 0]
    L += ["", "**План действий:**",
          "1. **Сразу (без затрат):** правила «уходя — гаси», дежурные, раздельное включение у окон, мытьё плафонов.",
          "2. **Этап 1 (до 3 мес.):** замена ламп накаливания и ДРЛ на LED, датчики движения в коридорах и санузлах.",
          "3. **Этап 2 (6–12 мес.):** замена люминесцентных светильников в кабинетах с недосветом — сначала самые тёмные.",
          "4. **Этап 3:** полный переход на LED, ежемесячный мониторинг счётчика и сравнение с расчётом ЭкоСвет."]
    return "\n".join(L)


# ---------- LLM ----------
def _compact(metrics: list[dict]) -> list[dict]:
    keys = ["name", "room_type", "area", "n_lamps", "power_kw", "lumens", "lux", "norm_lux", "norm_pct",
            "eff_class", "hours_per_day", "kwh_year", "cost_year", "led_share", "windows", "has_sensor",
            "win_count", "win_area", "door_count", "df_pct", "lux_nat", "daylight_pct"]
    out = []
    for m in metrics:
        d = {k: (round(m[k], 2) if isinstance(m[k], float) else m[k]) for k in keys}
        d["lamps"] = _lamp_summary(m["lamps"])
        out.append(d)
    return out


def llm_available(secrets: dict) -> str | None:
    if secrets.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if secrets.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return None


def llm_report(title: str, metrics: list[dict], settings: dict, secrets: dict, base_report: str) -> tuple[str | None, str]:
    """Возвращает (текст, сообщение). Текст None — если LLM недоступна."""
    provider = llm_available(secrets)
    if not provider:
        return None, "Ключ API не задан — используется встроенный ИИ-движок."
    try:
        import requests
    except ImportError:
        return None, "Пакет requests не установлен."
    payload = {"объект": title, "тариф_тг_кВтч": settings.get("tariff"),
               "помещения": _compact(metrics), "предварительный_анализ": base_report[:6000]}
    user = "Данные энергоаудита (JSON):\n" + json.dumps(payload, ensure_ascii=False)
    try:
        if provider == "anthropic":
            key = secrets.get("ANTHROPIC_API_KEY") or os.environ["ANTHROPIC_API_KEY"]
            model = secrets.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
            r = requests.post("https://api.anthropic.com/v1/messages", timeout=120, headers={
                "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": model, "max_tokens": 3000, "system": SYSTEM_PROMPT,
                      "messages": [{"role": "user", "content": user}]})
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json()["content"]), f"Отчёт подготовлен моделью {model}."
        key = secrets.get("OPENAI_API_KEY") or os.environ["OPENAI_API_KEY"]
        model = secrets.get("OPENAI_MODEL", "gpt-4o-mini")
        r = requests.post("https://api.openai.com/v1/chat/completions", timeout=120,
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": model, "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                                             {"role": "user", "content": user}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"], f"Отчёт подготовлен моделью {model}."
    except Exception as e:  # сеть, ключ, лимиты
        return None, f"LLM недоступна ({type(e).__name__}) — показан встроенный анализ."
