"""Константы и вспомогательные функции меню Telegram-адаптера."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from vtelemax.core import (
    BUTTON_ACCEPT_RULES,
    BUTTON_ABOUT,
    BUTTON_BALANCE,
    BUTTON_DOCS_LINK,
    BUTTON_HELP,
    BUTTON_MAIN_MENU,
    BUTTON_PROFILE,
    BUTTON_SEND_PHONE,
    BUTTON_SUPPORT,
    BUTTON_VACANCIES,
    BUTTON_VIRTUAL_CARD,
)

RULES_ACCEPT_CALLBACK = "rules_accept"
DOCS_URL = "https://example.com/documents"  # временный URL, позже заменить


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


def build_rules_consent_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру шага согласия с правилами."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=BUTTON_DOCS_LINK, url=DOCS_URL),
                InlineKeyboardButton(text=BUTTON_ACCEPT_RULES, callback_data=RULES_ACCEPT_CALLBACK),
            ]
        ]
    )


def build_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Создает основную клавиатуру после успешной регистрации."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BUTTON_BALANCE), KeyboardButton(text=BUTTON_VIRTUAL_CARD)],
            [KeyboardButton(text=BUTTON_SUPPORT), KeyboardButton(text=BUTTON_VACANCIES)],
            [KeyboardButton(text=BUTTON_PROFILE), KeyboardButton(text=BUTTON_HELP)],
            [KeyboardButton(text=BUTTON_ABOUT), KeyboardButton(text=BUTTON_MAIN_MENU)],
        ],
        resize_keyboard=True,
    )
