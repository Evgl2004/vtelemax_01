"""Telegram-адаптер.

Здесь будет размещаться интеграция с aiogram:

1. Регистрация роутеров.
2. Маппинг Telegram update -> команды ядра.
3. Маппинг ответов ядра -> Telegram сообщения и клавиатуры.
"""

from .identity_adapter import TelegramIdentityAdapter, TelegramRegistrationResult
from .router import build_telegram_identity_router

__all__ = [
    "TelegramIdentityAdapter",
    "TelegramRegistrationResult",
    "build_telegram_identity_router",
]
