"""Тесты Telegram-клавиатур меню."""

from __future__ import annotations

from vtelemax.adapters.telegram.menu import (
    DOCS_URL,
    RULES_ACCEPT_CALLBACK,
    build_rules_consent_inline_keyboard,
)
from vtelemax.core import BUTTON_ACCEPT_RULES, BUTTON_DOCS_LINK


def test_build_rules_consent_keyboard_contains_two_buttons() -> None:
    """Проверяет, что inline-клавиатура правил содержит две кнопки: документы и согласие."""

    keyboard = build_rules_consent_inline_keyboard()

    assert keyboard.inline_keyboard
    row = keyboard.inline_keyboard[0]
    assert len(row) == 2

    docs_button = row[0]
    accept_button = row[1]

    assert docs_button.text == BUTTON_DOCS_LINK
    assert docs_button.url == DOCS_URL

    assert accept_button.text == BUTTON_ACCEPT_RULES
    assert accept_button.callback_data == RULES_ACCEPT_CALLBACK
