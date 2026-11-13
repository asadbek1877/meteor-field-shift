"""Telegram-бот Meteor Field Shift: присылает отчёт по полю из бэкенда /api/analyze.

Запуск: python telegram_bot/bot.py  (из корня репозитория)
"""
import asyncio
import logging
import os

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from dotenv import load_dotenv

from formatter import format_report
from keyboards import language_keyboard, location_keyboard

# Читаем .env, который лежит рядом с bot.py (там BOT_TOKEN и API_BASE_URL)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = 15  # секунд ждём ответ бэкенда

dp = Dispatcher()

# Язык каждого пользователя хранится в памяти: после перезапуска бота сбросится на "en"
user_lang: dict[int, str] = {}

# Тексты бота на двух языках
TEXTS = {
    "en": {
        "welcome": (
            "👋 Hi! I show how the climate changed at your field (NASA data) and which crop "
            "rotation fits best.\n\nChoose a language, then send your location with the button below."
        ),
        "lang_set": "Language: English. Now send your location with the button below.",
        "wait": "⏳ Analysing NASA data, this can take up to 15 seconds...",
        "bad_coords": "❌ Wrong coordinates. Latitude must be from -90 to 90, longitude from -180 to 180.\nExample: /start 41.2995_69.2401",
        "timeout": "⌛ The server took too long to answer. Please try again in a minute.",
        "down": "🔌 The analysis server is not available now. Please try again later.",
        "error": "⚠️ The server could not analyse this point. Try another location.",
        "help": "Send your location with the button, or open a link like t.me/<bot>?start=41.2995_69.2401",
    },
    "uz": {
        "welcome": (
            "👋 Salom! Men dalangizda iqlim qanday o'zgarganini (NASA ma'lumotlari) va qaysi "
            "ekin rotatsiyasi mosligini ko'rsataman.\n\nTilni tanlang, so'ng pastdagi tugma bilan joylashuvni yuboring."
        ),
        "lang_set": "Til: o'zbekcha. Endi pastdagi tugma bilan joylashuvni yuboring.",
        "wait": "⏳ NASA ma'lumotlari tahlil qilinmoqda, 15 soniyagacha vaqt ketishi mumkin...",
        "bad_coords": "❌ Koordinatalar noto'g'ri. Kenglik -90 dan 90 gacha, uzunlik -180 dan 180 gacha bo'lishi kerak.\nMisol: /start 41.2995_69.2401",
        "timeout": "⌛ Server juda uzoq javob bermadi. Bir daqiqadan so'ng qayta urinib ko'ring.",
        "down": "🔌 Tahlil serveri hozir mavjud emas. Keyinroq qayta urinib ko'ring.",
        "error": "⚠️ Server bu nuqtani tahlil qila olmadi. Boshqa joyni sinab ko'ring.",
        "help": "Tugma orqali joylashuvni yuboring yoki t.me/<bot>?start=41.2995_69.2401 kabi havoladan foydalaning",
    },
}


def lang_of(user_id: int) -> str:
    """Язык пользователя; по умолчанию английский."""
    return user_lang.get(user_id, "en")


def parse_coords(payload: str) -> tuple[float, float] | None:
    """Разбирает строку вида '41.2995_69.2401'. Возвращает (lat, lon) или None, если что-то не так."""
    parts = payload.strip().split("_")
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    # float('nan') и float('inf') проходят преобразование, но проверку диапазона не пройдут
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


async def fetch_analysis(lat: float, lon: float, lang: str) -> dict:
    """Запрашивает отчёт у бэкенда. Ошибки httpx пробрасываются наверх, их ловит send_report."""
    params = {"lat": lat, "lon": lon, "lang": lang}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(f"{API_BASE_URL}/api/analyze", params=params)
        response.raise_for_status()
        return response.json()


async def send_report(message: Message, lat: float, lon: float) -> None:
    """Запрашивает отчёт и отправляет его пользователю. Вместо traceback показываем понятный текст."""
    lang = lang_of(message.from_user.id)
    t = TEXTS[lang]
    await message.answer(t["wait"], reply_markup=location_keyboard(lang))
    try:
        data = await fetch_analysis(lat, lon, lang)
        text = format_report(data, lang)
    except httpx.TimeoutException:
        await message.answer(t["timeout"])
    except httpx.HTTPStatusError as error:
        # 4xx/5xx от бэкенда: подробности только в лог, пользователю короткий текст
        logging.warning("Бэкенд ответил %s", error.response.status_code)
        await message.answer(t["error"])
    except (httpx.TransportError, ValueError):
        # Нет соединения с бэкендом или в ответе не JSON
        logging.warning("Бэкенд недоступен или вернул не JSON", exc_info=True)
        await message.answer(t["down"])
    else:
        await message.answer(text, reply_markup=location_keyboard(lang))


@dp.message(CommandStart())
async def on_start(message: Message, command: CommandObject) -> None:
    """/start без параметров: приветствие. /start 41.2995_69.2401: сразу отчёт."""
    lang = lang_of(message.from_user.id)
    if command.args:
        coords = parse_coords(command.args)
        if coords is None:
            await message.answer(TEXTS[lang]["bad_coords"])
            return
        await send_report(message, *coords)
        return
    await message.answer(TEXTS[lang]["welcome"], reply_markup=language_keyboard())
    # Вторым сообщением показываем кнопку геолокации (у одного сообщения может быть только одна клавиатура)
    await message.answer("📍", reply_markup=location_keyboard(lang))


@dp.callback_query(F.data.startswith("lang:"))
async def on_language(callback: CallbackQuery) -> None:
    """Пользователь нажал кнопку языка."""
    lang = callback.data.split(":", 1)[1]
    if lang not in TEXTS:
        await callback.answer()
        return
    user_lang[callback.from_user.id] = lang
    await callback.message.answer(TEXTS[lang]["lang_set"], reply_markup=location_keyboard(lang))
    await callback.answer()


@dp.message(F.location)
async def on_location(message: Message) -> None:
    """Пользователь прислал геолокацию."""
    await send_report(message, message.location.latitude, message.location.longitude)


@dp.message(Command("help"))
async def on_help(message: Message) -> None:
    await message.answer(TEXTS[lang_of(message.from_user.id)]["help"])


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # Токен берём только из переменной окружения (или .env), в коде его нет
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN не задан. Скопируйте .env.example в .env и впишите токен от @BotFather.")
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
