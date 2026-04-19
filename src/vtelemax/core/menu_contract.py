"""Единый контракт меню и текстовых ответов ядра.

Контракт используется всеми адаптерами (Telegram/VK/MAX), чтобы:

1. хранить единые тексты и сценарии;
2. не дублировать контент между платформами;
3. гарантировать одинаковую бизнес-логику взаимодействия с гостем.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class GuestMenuAction(StrEnum):
    """Ключи действий гостевого меню."""

    MAIN_MENU = "main_menu"
    PROFILE = "profile"
    PROFILE_EDIT = "profile_edit"
    PROFILE_EDIT_FIRST_NAME = "profile_edit_first_name"
    PROFILE_EDIT_LAST_NAME = "profile_edit_last_name"
    PROFILE_EDIT_GENDER = "profile_edit_gender"
    PROFILE_EDIT_GENDER_MALE = "profile_edit_gender_male"
    PROFILE_EDIT_GENDER_FEMALE = "profile_edit_gender_female"
    PROFILE_EDIT_BIRTH_DATE = "profile_edit_birth_date"
    PROFILE_EDIT_EMAIL = "profile_edit_email"
    PROFILE_EDIT_NOTIFICATIONS = "profile_edit_notifications"
    PROFILE_NOTIFICATIONS_ENABLE = "profile_notifications_enable"
    PROFILE_NOTIFICATIONS_TOGGLE = "profile_notifications_toggle"
    PROFILE_EDIT_CANCEL = "profile_edit_cancel"
    HELP = "help"
    ABOUT = "about"
    SHARE_CONTACT = "share_contact"
    BALANCE = "balance"
    VIRTUAL_CARD = "virtual_card"
    DELIVERY = "delivery"
    SUPPORT = "support"
    VACANCIES = "vacancies"
    SUPPORT_FEEDBACK = "support_feedback"
    SUPPORT_QUESTION = "support_question"
    SUPPORT_QUESTION_FROM_LIST = "support_question_from_list"
    MY_TICKETS = "my_tickets"
    VIEW_TICKET_DETAILS = "view_ticket_details"
    SUPPORT_CONTACTS = "support_contacts"
    BACK_TO_MAIN = "back_to_main"
    BACK_TO_SUPPORT = "back_to_support"
    ACCEPT_RULES = "accept_rules"
    OPEN_DOCS = "open_docs"
    NOTIFY_YES = "notify_yes"
    NOTIFY_NO = "notify_no"
    RETRY_IIKO_SYNC = "retry_iiko_sync"
    BUSINESS_LUNCH = "business_lunch"
    TABLE_BOOKING = "table_booking"
    VK_PHONE_VERIFICATION_CHECK = "vk_phone_verification_check"


@dataclass(frozen=True, slots=True)
class MenuButtonContract:
    """Единое описание кнопки меню."""

    action: GuestMenuAction
    label: str
    url: str | None = None


@dataclass(frozen=True, slots=True)
class MenuScreenContract:
    """Единое описание экрана меню/ответа."""

    screen_id: str
    text: str
    buttons: tuple[MenuButtonContract, ...] = ()
    parse_mode: Literal["plain", "markdown"] = "plain"
