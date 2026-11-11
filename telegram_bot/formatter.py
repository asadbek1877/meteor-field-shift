"""Превращает JSON от GET /api/analyze в короткое сообщение для Telegram (HTML).

Поля берём из реального кода бэкенда (backend/main.py, climate.py, agro.py).
Любого поля может не быть (бэкенд ставит null, если источник данных не ответил),
поэтому везде используем безопасные функции get() и num().
"""
from html import escape

# Тексты самого бота (тексты советов приходят уже переведёнными из бэкенда)
T = {
    "en": {
        "title": "Field report",
        "place": "Location",
        "climate": "Climate shift (recent vs 1991-2010)",
        "temp": "Mean temperature",
        "rain": "Yearly precipitation",
        "hot": "Days above 35 °C",
        "per_year": "per year",
        "now": "Last 30 days",
        "now_rain": "Rain",
        "now_temp": "Mean temperature",
        "rotation": "Best rotation",
        "score": "Score",
        "water": "Water",
        "income": "Income",
        "advice": "Advice",
        "warnings": "Warnings",
        "no_data": "No climate data for this point.",
        "disclaimer": "Numbers compare options; they are not a yield forecast.",
    },
    "uz": {
        "title": "Dala hisoboti",
        "place": "Joylashuv",
        "climate": "Iqlim o'zgarishi (hozirgi va 1991-2010)",
        "temp": "O'rtacha harorat",
        "rain": "Yillik yog'in",
        "hot": "35 °C dan issiq kunlar",
        "per_year": "yiliga",
        "now": "Oxirgi 30 kun",
        "now_rain": "Yomg'ir",
        "now_temp": "O'rtacha harorat",
        "rotation": "Eng yaxshi rotatsiya",
        "score": "Ball",
        "water": "Suv",
        "income": "Daromad",
        "advice": "Maslahat",
        "warnings": "Ogohlantirishlar",
        "no_data": "Bu nuqta uchun iqlim ma'lumoti yo'q.",
        "disclaimer": "Raqamlar variantlarni solishtirish uchun, hosil prognozi emas.",
    },
}

# Telegram не принимает сообщения длиннее 4096 символов; оставляем запас
MAX_LENGTH = 3800


def get(data, *path):
    """Безопасно идёт по вложенным словарям: get(d, 'a', 'b') -> d['a']['b'] или None."""
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def num(value, unit: str = "", digits: int = 1, signed: bool = False) -> str:
    """Число с единицей измерения. Если числа нет, возвращает «—»."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "—"
    text = f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"
    return f"{text}{unit}" if unit == "%" else f"{text} {unit}".strip()


def name_of(obj, lang: str) -> str:
    """Название вида {'en': ..., 'uz': ...} на нужном языке (или пустая строка)."""
    names = get(obj, "name")
    if isinstance(names, dict):
        return str(names.get(lang) or names.get("en") or "")
    return ""


def format_report(data: dict, lang: str = "en") -> str:
    """Главная функция: JSON ответа -> текст сообщения (HTML parse mode)."""
    lang = lang if lang in T else "en"
    t = T[lang]
    lines = []

    # Заголовок и координаты
    lat, lon = get(data, "location", "lat"), get(data, "location", "lon")
    lines.append(f"🌾 <b>{t['title']}</b>")
    if lat is not None and lon is not None:
        lines.append(f"📍 {t['place']}: {num(lat, '', 4)}, {num(lon, '', 4)}")

    # Сдвиг климата: средняя температура, осадки, жаркие дни
    shift = get(data, "climate", "shift")
    lines.append("")
    if shift:
        lines.append(f"🌡 <b>{t['climate']}</b>")
        temp = get(shift, "t_mean")
        if temp:
            lines.append(
                f"• {t['temp']}: {num(get(temp, 'baseline'), '°C')} → {num(get(temp, 'recent'), '°C')}"
                f" ({num(get(temp, 'delta'), '°C', 1, signed=True)})"
            )
        rain = get(shift, "precip_mm")
        if rain:
            lines.append(
                f"• {t['rain']}: {num(get(rain, 'baseline'), 'mm', 0)} → {num(get(rain, 'recent'), 'mm', 0)}"
                f" ({num(get(rain, 'delta_pct'), '%', 0, signed=True)})"
            )
        hot = get(shift, "hot_days")  # этого поля нет, если данные только месячные
        if hot:
            lines.append(
                f"• {t['hot']}: {num(get(hot, 'baseline'), '', 0)} → {num(get(hot, 'recent'), '', 0)} {t['per_year']}"
            )
    else:
        lines.append(f"⚠️ {t['no_data']}")

    # Последние 30 дней
    recent = get(data, "now", "recent")
    if recent:
        lines.append("")
        lines.append(f"🌦 <b>{t['now']}</b>")
        lines.append(f"• {t['now_rain']}: {num(get(recent, 'rain_mm'), 'mm')}")
        lines.append(f"• {t['now_temp']}: {num(get(recent, 't_mean'), '°C')}")

    # Лучший севооборот по оценке бэкенда
    rotations = get(data, "rotations")
    items = get(rotations, "items") or []
    best = next((it for it in items if it.get("id") == get(rotations, "best_id")), None)
    if best:
        lines.append("")
        lines.append(f"🔄 <b>{t['rotation']}</b>: {escape(name_of(best, lang), quote=False)}")
        lines.append(f"• {t['score']}: {num(get(best, 'scores', 'total'), '/ 100')}")
        lines.append(f"• {t['water']}: {num(get(best, 'water_m3_ha', 'p50'), 'm³/ha', 0)}")
        lines.append(f"• {t['income']}: {num(get(best, 'income_usd_ha', 'p50'), 'USD/ha', 0)}")

    # Советы: бэкенд уже пишет их на нужном языке. Берём не больше трёх, важные сверху.
    order = {"critical": 0, "warning": 1, "tip": 2, "info": 3}
    advice = [a for a in (get(data, "advice") or []) if get(a, "text")]
    advice.sort(key=lambda a: order.get(a.get("severity"), 9))
    if advice:
        lines.append("")
        lines.append(f"💡 <b>{t['advice']}</b>")
        for a in advice[:3]:
            lines.append(f"• {escape(str(a['text'])[:500], quote=False)}")

    # Предупреждения (например, NASA не ответил): только первые два
    warnings = [w for w in (get(data, "warnings") or []) if get(w, "text")]
    if warnings:
        lines.append("")
        lines.append(f"⚠️ <b>{t['warnings']}</b>")
        for w in warnings[:2]:
            lines.append(f"• {escape(str(w['text'])[:500], quote=False)}")

    lines.append("")
    lines.append(f"<i>{t['disclaimer']}</i>")

    text = "\n".join(lines)
    # Слишком длинно: обрезаем целыми строками (перед припиской), чтобы не порвать HTML-теги
    while len(text) > MAX_LENGTH and len(lines) > 4:
        del lines[-3]
        text = "\n".join(lines)
    return text
