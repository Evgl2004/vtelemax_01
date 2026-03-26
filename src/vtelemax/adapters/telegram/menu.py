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
    BUTTON_BACK_TO_MAIN,
    BUTTON_BACK_TO_SUPPORT,
    BUTTON_BALANCE,
    BUTTON_DOCS_LINK,
    BUTTON_HELP,
    BUTTON_MAIN_MENU,
    BUTTON_MY_TICKETS,
    BUTTON_PROFILE,
    BUTTON_SEND_PHONE,
    BUTTON_SUPPORT,
    BUTTON_SUPPORT_CONTACTS,
    BUTTON_SUPPORT_FEEDBACK,
    BUTTON_SUPPORT_QUESTION,
    BUTTON_VACANCIES,
    BUTTON_VIRTUAL_CARD,
)

RULES_ACCEPT_CALLBACK = "rules_accept"
DOCS_URL = "https://sagur.24vds.ru/agreement/#"


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
            [InlineKeyboardButton(text=BUTTON_DOCS_LINK, url=DOCS_URL)],
            [InlineKeyboardButton(text=BUTTON_ACCEPT_RULES, callback_data=RULES_ACCEPT_CALLBACK)],
        ]
    )


def build_main_menu_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру главного меню (пять разделов, вертикальный список)."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=BUTTON_BALANCE, callback_data=BUTTON_BALANCE)],
            [InlineKeyboardButton(text=BUTTON_VIRTUAL_CARD, callback_data=BUTTON_VIRTUAL_CARD)],
            [InlineKeyboardButton(text=BUTTON_SUPPORT, callback_data=BUTTON_SUPPORT)],
            [InlineKeyboardButton(text=BUTTON_VACANCIES, callback_data=BUTTON_VACANCIES)],
            [InlineKeyboardButton(text=BUTTON_PROFILE, callback_data=BUTTON_PROFILE)],
        ]
    )


def build_support_menu_inline_keyboard(has_tickets: bool = False) -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру подменю «Отдел заботы» (вертикальный список)."""

    buttons = [
        [InlineKeyboardButton(text=BUTTON_SUPPORT_FEEDBACK, callback_data=BUTTON_SUPPORT_FEEDBACK)],
        [InlineKeyboardButton(text=BUTTON_SUPPORT_QUESTION, callback_data=BUTTON_SUPPORT_QUESTION)],
    ]
    if has_tickets:
        buttons.append([InlineKeyboardButton(text=BUTTON_MY_TICKETS, callback_data=BUTTON_MY_TICKETS)])
    buttons.extend(
        [
            [InlineKeyboardButton(text=BUTTON_SUPPORT_CONTACTS, callback_data=BUTTON_SUPPORT_CONTACTS)],
            [InlineKeyboardButton(text=BUTTON_BACK_TO_MAIN, callback_data=BUTTON_BACK_TO_MAIN)],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Создает основную клавиатуру после успешной регистрации (вертикальный список)."""

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BUTTON_BALANCE)],
            [KeyboardButton(text=BUTTON_VIRTUAL_CARD)],
            [KeyboardButton(text=BUTTON_SUPPORT)],
            [KeyboardButton(text=BUTTON_VACANCIES)],
            [KeyboardButton(text=BUTTON_PROFILE)],
        ],
        resize_keyboard=True,
    )
