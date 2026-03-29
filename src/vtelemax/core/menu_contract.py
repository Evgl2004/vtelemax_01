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
    HELP = "help"
    ABOUT = "about"
    SHARE_CONTACT = "share_contact"
    BALANCE = "balance"
    VIRTUAL_CARD = "virtual_card"
    SUPPORT = "support"
    VACANCIES = "vacancies"
    SUPPORT_FEEDBACK = "support_feedback"
    SUPPORT_QUESTION = "support_question"
    MY_TICKETS = "my_tickets"
    SUPPORT_CONTACTS = "support_contacts"
    BACK_TO_MAIN = "back_to_main"
    BACK_TO_SUPPORT = "back_to_support"
    OPEN_DOCS = "open_docs"
    NOTIFY_YES = "notify_yes"
    NOTIFY_NO = "notify_no"


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
