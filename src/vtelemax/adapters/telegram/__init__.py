"""Telegram-адаптер.

Здесь будет размещаться интеграция с aiogram:

1. Регистрация роутеров.
2. Маппинг Telegram update -> команды ядра.
3. Маппинг ответов ядра -> Telegram сообщения и клавиатуры.
"""

from .identity_adapter import (
    TelegramIdentityAdapter,
    TelegramMenuActionResult,
    TelegramRegistrationResult,
)
from .menu import (
    build_contact_request_keyboard,
    build_main_menu_keyboard,
    build_rules_consent_keyboard,
)
from .router import build_telegram_identity_router

__all__ = [
    "TelegramIdentityAdapter",
    "TelegramMenuActionResult",
    "TelegramRegistrationResult",
    "build_contact_request_keyboard",
    "build_main_menu_keyboard",
    "build_rules_consent_keyboard",
    "build_telegram_identity_router",
]
