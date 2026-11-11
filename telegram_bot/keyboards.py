"""Клавиатуры бота: кнопка геолокации и выбор языка."""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Подписи кнопки геолокации на двух языках
LOCATION_BUTTON_TEXT = {
    "en": "📍 Send my location",
    "uz": "📍 Joylashuvni yuborish",
}


def location_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """Обычная клавиатура с одной кнопкой: Telegram сам спросит разрешение на геолокацию."""
    button = KeyboardButton(text=LOCATION_BUTTON_TEXT.get(lang, LOCATION_BUTTON_TEXT["en"]), request_location=True)
    return ReplyKeyboardMarkup(keyboard=[[button]], resize_keyboard=True)


def language_keyboard() -> InlineKeyboardMarkup:
    """Кнопки под сообщением для выбора языка. В callback_data лежит код языка."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang:uz"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
            ]
        ]
    )
