"""Автоматический SWOT-анализ, рекомендации и правила энергосбережения."""
from __future__ import annotations

from .calc import SENSOR_TYPES, fmt, simulate

QUADRANTS = {
    "S": ("💪 Сильные стороны (Strengths)", "#e6f4ea"),
    "W": ("⚠️ Слабые стороны (Weaknesses)", "#fdecea"),
    "O": ("🚀 Возможности (Opportunities)", "#e8f0fe"),
    "T": ("🌩️ Угрозы (Threats)", "#fff4e5"),
}

PRIO = {"high": "🔴 Высокий", "mid": "🟡 Средний", "low": "🟢 Низкий"}

RULES = [
    "Уходя последним — выключи свет. Назначить ответственного за выключение в каждом кабинете (дежурный).",
    "На переменах и во время проветривания свет в пустом кабинете выключается.",
    "В солнечную погоду пользоваться естественным освещением: включать только ряд светильников у стены без окон.",
    "Раздельное включение рядов светильников: оконный ряд — отдельным выключателем.",
    "Окна и плафоны мыть не реже 2 раз в год: загрязнение снижает световой поток на 20–30 %.",
    "Светлые жалюзи вместо плотных штор; не загромождать подоконники.",
    "Перегоревшие лампы накаливания и люминесцентные заменять только на LED.",
    "Ртутьсодержащие (люминесцентные, ДРЛ) лампы сдавать на утилизацию, не выбрасывать.",
    "В коридорах, санузлах и подсобных помещениях — датчики движения или таймеры.",
    "Наружное освещение — по фотореле/таймеру, а не вручную.",
    "Компьютеры, проекторы и интерактивные панели выключать после уроков (режим ожидания тоже тратит энергию).",
    "Раз в четверть «Эко-патруль» проверяет кабинеты и публикует рейтинг самых экономных классов.",
    "Ежемесячно сверять показания счётчика с расчётом «ЭкоСвет» и обсуждать результаты с администрацией.",
]


def room_recommendations(m: dict, led_types: list[dict], settings: dict) -> list[dict]:
    recs = []
    techs = {l.get("tech") for l in m["lamps"]}
    if m["status"] == "no_lamps":
        return [{"prio": "mid", "text": "В помещении не внесены лампы — проведите обход и добавьте их карандашом на карте.",
                 "effect": 0}]
    if m["status"] in ("critical", "low"):
        add = m["lack_lamps"] or 0
        recs.append({"prio": "high" if m["status"] == "critical" else "mid",
                     "text": f"Освещённость {m['lux']:.0f} лк при норме {m['norm_lux']:.0f} лк "
                             f"({m['norm_pct']:.0f} %). Это вредно для зрения. Довести до нормы: "
                             f"+{max(add, 0)} светильник(ов) или замена на более яркие LED.",
                     "effect": 0})
    non_led = [l for l in m["lamps"] if l.get("tech") != "LED"]
    if non_led:
        sim = simulate([m], led_types, settings, led=True, to_norm=True)
        r = sim["rows"][0]
        prio = "high" if techs & {"Накаливания", "ДРЛ", "Галогенная"} else "mid"
        recs.append({"prio": prio,
                     "text": f"Заменить устаревшие лампы на LED ({r['Новые лампы']}) с доведением до нормы: "
                             f"экономия {fmt(r['Экономия, кВт·ч/год'], 0)} кВт·ч/год, инвестиции "
                             f"{fmt(r['Инвестиции, ₸'], 0)} ₸, окупаемость {fmt(r['Окупаемость, лет'], 1)} г.",
                     "effect": r["Экономия, ₸/год"]})
    if "Накаливания" in techs:
        recs.append({"prio": "high", "text": "Лампы накаливания: светоотдача ~12 лм/Вт против ~100 лм/Вт у LED — "
                                             "заменить в первую очередь (дёшево, окупается за месяцы).", "effect": 0})
    if techs & {"Люминесцентная", "ДРЛ"}:
        recs.append({"prio": "mid", "text": "Ртутьсодержащие лампы: организовать сбор и сдачу на утилизацию.",
                     "effect": 0})
    if m["status"] == "over":
        excess = 1 - 100 / m["norm_pct"]
        save = m["cost_year"] * excess
        recs.append({"prio": "mid",
                     "text": f"Пересвет {m['norm_pct']:.0f} % от нормы: можно отключить ~{excess * 100:.0f} % "
                             f"светильников (раздельные выключатели). Экономия ≈ {fmt(save, 0)} ₸/год.",
                     "effect": save})
    if m["room_type"] in SENSOR_TYPES and not m["has_sensor"]:
        recs.append({"prio": "mid", "text": f"Установить датчик движения: −30 % времени работы ≈ "
                                            f"{fmt(m['cost_year'] * 0.3, 0)} ₸/год.",
                     "effect": m["cost_year"] * 0.3})
    if m.get("win_area", 0) > 0 and m.get("daylight_pct", 0) > 0 and m["n_lamps"]:
        eff = m["cost_year"] * m["daylight_pct"] / 100
        recs.append({"prio": "mid" if m["daylight_pct"] >= 20 else "low",
                     "text": f"Окон: {m['win_count']} ({fmt(m['win_area'], 1)} м² остекления), КЕО {m['df_pct']:.2f} %, "
                             f"днём естественный свет даёт ≈ {m['lux_nat']:.0f} лк. Раздельное включение оконного ряда "
                             f"или датчик освещённости: −{m['daylight_pct']:.0f} % ≈ {fmt(eff, 0)} ₸/год.",
                     "effect": eff})
    elif m["windows"] and m["room_type"] not in SENSOR_TYPES:
        recs.append({"prio": "low", "text": f"Использовать дневной свет и раздельное включение оконного ряда: "
                                            f"−15 % ≈ {fmt(m['cost_year'] * 0.15, 0)} ₸/год.",
                     "effect": m["cost_year"] * 0.15})
    if m.get("keo_ok") is False:
        if m.get("win_count"):
            recs.append({"prio": "mid", "text": f"КЕО {m['df_pct']:.2f} % ниже ориентира {m['keo_norm']} %: "
                                                "не загораживать окна, светлые жалюзи вместо штор, мыть стёкла 2 раза в год, "
                                                "светлая отделка стен и потолка.", "effect": 0})
        else:
            recs.append({"prio": "mid", "text": "На плане у помещения не найдено окон: свет только искусственный. "
                                                "Проверьте при обходе; если окон нет — приоритет LED и датчиков.",
                         "effect": 0})
    if m["eff_class"] in ("D", "E"):
        recs.append({"prio": "mid", "text": f"Класс энергоэффективности {m['eff_class']} "
                                            f"({m['w_per_m2_100lx']:.1f} Вт/м² на 100 лк) — низкий. Цель — класс A–B."
                     , "effect": 0})
    if m["hours_per_day"] >= 10 and m["room_type"] not in SENSOR_TYPES:
        recs.append({"prio": "low", "text": f"Освещение работает {m['hours_per_day']:.0f} ч/день — проверьте, "
                                            "не горит ли свет после уроков.", "effect": 0})
    order = {"high": 0, "mid": 1, "low": 2}
    return sorted(recs, key=lambda r: (order[r["prio"]], -r["effect"]))


def auto_swot(metrics: list[dict], agg: dict, led_types: list[dict], settings: dict) -> dict[str, list[str]]:
    S, W, O, T = [], [], [], []
    tariff = float(settings.get("tariff", 32))
    led_rooms = [m for m in metrics if m["n_lamps"] and m["led_share"] >= 0.99]
    ok_rooms = [m for m in metrics if m["status"] == "ok"]
    low = [m for m in metrics if m["status"] in ("low", "critical")]
    over = [m for m in metrics if m["status"] == "over"]
    inc = sum(l["qty"] for m in metrics for l in m["lamps"] if l.get("tech") == "Накаливания")
    drl = sum(l["qty"] for m in metrics for l in m["lamps"] if l.get("tech") == "ДРЛ")
    fluo = sum(l["qty"] for m in metrics for l in m["lamps"] if l.get("tech") == "Люминесцентная")
    win = [m for m in metrics if m["windows"]]
    sensor_cand = [m for m in metrics if m["room_type"] in SENSOR_TYPES and not m["has_sensor"] and m["n_lamps"]]

    # S
    S.append(f"Проведён энергоаудит: {agg['rooms']} помещений, {agg['n_lamps']} светильников на {len({m['map_id'] for m in metrics})} планах.")
    if led_rooms:
        S.append(f"{len(led_rooms)} помещ. уже полностью на LED ({', '.join(m['name'] for m in led_rooms[:4])}{'…' if len(led_rooms) > 4 else ''}).")
    if ok_rooms:
        S.append(f"{len(ok_rooms)} помещ. соответствуют норме освещённости.")
    if win:
        S.append(f"{len(win)} помещ. имеют окна — есть ресурс дневного света.")
    wins = sum(m.get("win_count", 0) for m in metrics)
    study = [m for m in metrics if m.get("keo_norm") and m["keo_norm"] >= 1.5 and m.get("win_area", 0) > 0]
    if wins:
        S.append(f"На планах распознано {wins} окон, {sum(m.get('door_count', 0) for m in metrics)} дверей.")
    if study:
        S.append(f"Средний КЕО учебных кабинетов {sum(m['df_pct'] for m in study) / len(study):.2f} % — "
                 "естественного света в среднем достаточно.")
    S.append("Есть цифровые паспорта помещений и школы — база для контроля и отчётности.")
    S.append("Вовлечённость учеников: исследовательский проект и «Эко-патруль».")
    # W
    W.append(f"Доля LED всего {agg['led_share'] * 100:.0f} %; устаревших светильников: {agg['n_lamps'] - agg['led_n']}.")
    if fluo:
        W.append(f"{fluo} люминесцентных светильников (ртуть, мерцание, деградация потока).")
    if inc:
        W.append(f"{inc} ламп накаливания — самая неэффективная технология (~12 лм/Вт).")
    if drl:
        W.append(f"{drl} светильников ДРЛ в спортзале: высокая мощность, долгий разогрев, ртуть.")
    if low:
        W.append(f"{len(low)} помещ. ниже нормы освещённости — риск для зрения учащихся.")
    if over:
        W.append(f"{len(over)} помещ. с пересветом — лишний расход.")
    keo_bad = [m for m in metrics if m.get("keo_ok") is False]
    if keo_bad:
        W.append(f"{len(keo_bad)} помещ. с КЕО ниже ориентира или без окон: "
                 + ", ".join(m["name"] for m in keo_bad[:4]) + ("…" if len(keo_bad) > 4 else "") + ".")
    if sensor_cand:
        W.append(f"Нет датчиков движения в {len(sensor_cand)} коридорах/санузлах/подсобках.")
    W.append(f"Удельная мощность освещения {agg['w_per_m2']:.1f} Вт/м².")
    # O
    led_sim = simulate(metrics, led_types, settings, led=True, to_norm=True)
    full = simulate(metrics, led_types, settings, led=True, to_norm=True, sensors=True, daylight=True, hours_cut=0.5)
    O.append(f"Переход на LED с доведением до нормы: −{led_sim['save_pct']:.0f} % "
             f"({fmt(led_sim['save_tg'], 0)} ₸/год), окупаемость {fmt(led_sim['payback'], 1)} г.")
    O.append(f"Комплекс мер (LED + датчики + дневной свет + −0,5 ч): −{full['save_pct']:.0f} %, "
             f"{fmt(full['save_tg'], 0)} ₸/год и {fmt(full['co2'] / 1000, 1)} т CO₂/год.")
    dl = simulate(metrics, led_types, settings, daylight=True)
    O.append(f"Дневной свет по окнам (раздельное включение рядов, датчики освещённости): −{dl['save_pct']:.0f} % = "
             f"{fmt(dl['save_tg'], 0)} ₸/год почти без затрат.")
    O.append("Энергосервисный договор (ЭСКО) или софинансирование по госпрограммам энергосбережения — модернизация без разовых затрат школы.")
    O.append("Поэтапная замена: сначала накаливание и ДРЛ (быстрая окупаемость), затем люминесцентные.")
    O.append("Конкурсы и гранты по экологии и STEM; распространение опыта на другие школы области.")
    # T
    T.append(f"Рост тарифа (сейчас {tariff:.1f} ₸/кВт·ч) увеличит расходы при сохранении старых ламп.")
    T.append("Ограниченный бюджет школы на модернизацию.")
    T.append("Возврат к старым привычкам без регулярного контроля («свет горит в пустых кабинетах»).")
    T.append("Некачественные дешёвые LED (мерцание, низкий CRI) — выбирать по ГОСТ/СТ РК, пульсация < 5 %.")
    if fluo or drl:
        T.append("Экологический риск при неправильной утилизации ртутьсодержащих ламп.")
    return {"S": S, "W": W, "O": O, "T": T}
