"""Тесты Telegram-клавиатур меню."""

from __future__ import annotations

from vtelemax.adapters.telegram.menu import build_rules_consent_keyboard
from vtelemax.core import BUTTON_ACCEPT_RULES


def test_build_rules_consent_keyboard_contains_accept_button() -> None:
    """Проверяет, что клавиатура правил содержит кнопку «✅ Согласен»."""

    keyboard = build_rules_consent_keyboard()

    assert keyboard.keyboard
    assert keyboard.keyboard[0][0].text == BUTTON_ACCEPT_RULES

