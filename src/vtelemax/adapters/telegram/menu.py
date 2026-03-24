"""Константы и вспомогательные функции меню Telegram-адаптера."""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BUTTON_SEND_PHONE = "Отправить номер телефона"
BUTTON_MAIN_MENU = "Главное меню"
BUTTON_PROFILE = "Мой профиль"
BUTTON_HELP = "Помощь"
BUTTON_ABOUT = "О проекте"


def build_contact_request_keyboard() -> ReplyKeyboardMarkup:
    """Создает клавиатуру с кнопкой отправки контакта."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text=BUTTON_SEND_PHONE,
                    request_contact=True,
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def build_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Создает основную клавиатуру после успешной регистрации."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BUTTON_PROFILE), KeyboardButton(text=BUTTON_HELP)],
            [KeyboardButton(text=BUTTON_ABOUT), KeyboardButton(text=BUTTON_MAIN_MENU)],
        ],
        resize_keyboard=True,
    )
