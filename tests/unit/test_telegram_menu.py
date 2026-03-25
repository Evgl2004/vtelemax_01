"""Тесты Telegram-клавиатур меню."""

from __future__ import annotations

from vtelemax.adapters.telegram.menu import (
    RULES_ACCEPT_CALLBACK,
    build_rules_consent_inline_keyboard,
)
from vtelemax.core import BUTTON_ACCEPT_RULES


def test_build_rules_consent_keyboard_contains_accept_button() -> None:
    """Проверяет, что inline-клавиатура правил содержит кнопку «✅ Согласен»."""

    keyboard = build_rules_consent_inline_keyboard()

    assert keyboard.inline_keyboard
    button = keyboard.inline_keyboard[0][0]
    assert button.text == BUTTON_ACCEPT_RULES
    assert button.callback_data == RULES_ACCEPT_CALLBACK
