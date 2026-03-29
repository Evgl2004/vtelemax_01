"""Тесты Telegram-клавиатур меню."""

from __future__ import annotations

from vtelemax.adapters.telegram.menu import (
    DOCS_URL,
    RULES_ACCEPT_CALLBACK,
    build_rules_consent_inline_keyboard,
)
from vtelemax.core import BUTTON_ACCEPT_RULES, BUTTON_DOCS_LINK


def test_build_rules_consent_keyboard_contains_docs_and_accept_buttons() -> None:
    """Проверяет, что клавиатура правил содержит кнопку документов и кнопку согласия."""

    keyboard = build_rules_consent_inline_keyboard()

    assert keyboard.inline_keyboard
    assert len(keyboard.inline_keyboard) == 2

    docs_row = keyboard.inline_keyboard[0]
    accept_row = keyboard.inline_keyboard[1]
    assert len(docs_row) == 1
    assert len(accept_row) == 1

    docs_button = docs_row[0]
    accept_button = accept_row[0]

    assert docs_button.text == BUTTON_DOCS_LINK
    assert docs_button.url == DOCS_URL

    assert accept_button.text == BUTTON_ACCEPT_RULES
    assert accept_button.callback_data == RULES_ACCEPT_CALLBACK
