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
    BUTTON_NOTIFICATIONS_DOCS,
    BUTTON_NOTIFICATIONS_NO,
    BUTTON_NOTIFICATIONS_YES,
    BUTTON_PROFILE,
    BUTTON_PROFILE_EDIT,
    BUTTON_PROFILE_EDIT_BIRTH_DATE,
    BUTTON_PROFILE_EDIT_CANCEL,
    BUTTON_PROFILE_EDIT_EMAIL,
    BUTTON_PROFILE_EDIT_FIRST_NAME,
    BUTTON_PROFILE_EDIT_GENDER,
    BUTTON_PROFILE_EDIT_GENDER_FEMALE,
    BUTTON_PROFILE_EDIT_GENDER_MALE,
    BUTTON_PROFILE_EDIT_LAST_NAME,
    BUTTON_SEND_PHONE,
    BUTTON_SUPPORT,
    BUTTON_SUPPORT_CONTACTS,
    BUTTON_SUPPORT_FEEDBACK,
    BUTTON_SUPPORT_QUESTION,
    BUTTON_VACANCIES,
    BUTTON_VIRTUAL_CARD,
)

RULES_ACCEPT_CALLBACK = "rules_accept"
NOTIFY_YES_CALLBACK = "notify_yes"
NOTIFY_NO_CALLBACK = "notify_no"
DOCS_URL = "https://sagur.24vds.ru/agreement/#"
NOTIFICATIONS_DOCS_URL = "https://sagur.24vds.ru/notifications/#"


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


def build_notifications_consent_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру шага согласия на уведомления."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=BUTTON_NOTIFICATIONS_DOCS, url=NOTIFICATIONS_DOCS_URL)],
            [InlineKeyboardButton(text=BUTTON_NOTIFICATIONS_YES, callback_data=NOTIFY_YES_CALLBACK)],
            [InlineKeyboardButton(text=BUTTON_NOTIFICATIONS_NO, callback_data=NOTIFY_NO_CALLBACK)],
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


def build_back_to_main_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру с кнопкой возврата в главное меню."""

    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=BUTTON_BACK_TO_MAIN, callback_data=BUTTON_BACK_TO_MAIN)]]
    )


def build_back_to_support_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру с кнопкой возврата в подменю отдела заботы."""

    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=BUTTON_BACK_TO_SUPPORT, callback_data=BUTTON_BACK_TO_SUPPORT)]]
    )


def build_profile_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру экрана профиля."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=BUTTON_PROFILE_EDIT, callback_data=BUTTON_PROFILE_EDIT)],
            [InlineKeyboardButton(text=BUTTON_BACK_TO_MAIN, callback_data=BUTTON_BACK_TO_MAIN)],
        ]
    )


def build_profile_edit_inline_keyboard(*, can_edit_birth_date: bool) -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру выбора редактируемого поля профиля."""

    rows = [
        [InlineKeyboardButton(text=BUTTON_PROFILE_EDIT_FIRST_NAME, callback_data=BUTTON_PROFILE_EDIT_FIRST_NAME)],
        [InlineKeyboardButton(text=BUTTON_PROFILE_EDIT_LAST_NAME, callback_data=BUTTON_PROFILE_EDIT_LAST_NAME)],
        [InlineKeyboardButton(text=BUTTON_PROFILE_EDIT_GENDER, callback_data=BUTTON_PROFILE_EDIT_GENDER)],
    ]
    if can_edit_birth_date:
        rows.append(
            [InlineKeyboardButton(text=BUTTON_PROFILE_EDIT_BIRTH_DATE, callback_data=BUTTON_PROFILE_EDIT_BIRTH_DATE)]
        )
    rows.extend(
        [
            [InlineKeyboardButton(text=BUTTON_PROFILE_EDIT_EMAIL, callback_data=BUTTON_PROFILE_EDIT_EMAIL)],
            [InlineKeyboardButton(text=BUTTON_PROFILE_EDIT_CANCEL, callback_data=BUTTON_PROFILE_EDIT_CANCEL)],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_profile_gender_inline_keyboard() -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру выбора пола в режиме редактирования профиля."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=BUTTON_PROFILE_EDIT_GENDER_MALE,
                    callback_data=BUTTON_PROFILE_EDIT_GENDER_MALE,
                )
            ],
            [
                InlineKeyboardButton(
                    text=BUTTON_PROFILE_EDIT_GENDER_FEMALE,
                    callback_data=BUTTON_PROFILE_EDIT_GENDER_FEMALE,
                )
            ],
            [InlineKeyboardButton(text=BUTTON_PROFILE_EDIT_CANCEL, callback_data=BUTTON_PROFILE_EDIT_CANCEL)],
        ]
    )


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
