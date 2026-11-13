"""Проверка formatter.py и разбора координат на тестовом JSON (без сети и без токена).

Запуск из корня репозитория: python -m pytest tests/test_telegram_formatter.py -q
Структура JSON взята из реального ответа GET /api/analyze (backend/main.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

from formatter import format_report  # noqa: E402

SAMPLE = {
    "location": {"lat": 41.2995, "lon": 69.2401},
    "climate": {"shift": {
        "t_mean": {"baseline": 13.1, "recent": 14.4, "delta": 1.3},
        "precip_mm": {"baseline": 420, "recent": 380, "delta_pct": -9.5},
        "hot_days": {"baseline": 38, "recent": 49},
    }},
    "now": {"recent": {"rain_mm": 12.5, "t_mean": 22.4}},
    "rotations": {
        "best_id": "r1",
        "items": [{
            "id": "r1",
            "name": {"en": "Wheat + mung bean", "uz": "Bug'doy + mosh"},
            "scores": {"total": 71.2},
            "water_m3_ha": {"p50": 5200},
            "income_usd_ha": {"p50": 900},
        }],
    },
    "advice": [{"group": "climate", "severity": "warning", "text": "Hot days: 38 -> 49 <per year>"}],
    "warnings": [{"provider": "nasa_power", "severity": "warning", "text": "Monthly data used."}],
}


def test_full_report_has_units():
    text = format_report(SAMPLE, "en")
    for part in ("°C", "mm", "%", "m³/ha", "USD/ha", "Wheat + mung bean"):
        assert part in text
    assert "&lt;per year&gt;" in text  # HTML из текста экранируется


def test_uzbek_language():
    assert "Dala hisoboti" in format_report(SAMPLE, "uz")


def test_missing_fields_do_not_crash():
    # Бэкенд ставит null, когда NASA не ответил
    empty = {"climate": None, "rotations": None, "now": None, "advice": None, "warnings": None}
    assert "No climate data" in format_report(empty, "en")
    assert format_report({}, "en")
    assert format_report(None, "en")


def test_short_enough_for_telegram():
    big = dict(SAMPLE, advice=[{"severity": "info", "text": "x" * 5000}] * 3)
    assert len(format_report(big, "en")) < 4096
