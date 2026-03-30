"""Тесты вспомогательных функций Telegram-роутера."""

from __future__ import annotations

from vtelemax.adapters.telegram.router import (
    _is_button_data_invalid_error,
    _is_message_not_modified_error,
)


def test_is_message_not_modified_error_detects_known_patterns() -> None:
    """Проверяет распознавание служебной ошибки «message is not modified»."""

    assert _is_message_not_modified_error(RuntimeError("Message is not modified"))
    assert _is_message_not_modified_error(RuntimeError("MESSAGE_NOT_MODIFIED"))


def test_is_message_not_modified_error_returns_false_for_other_errors() -> None:
    """Проверяет, что посторонние ошибки не считаются «not modified»."""

    assert not _is_message_not_modified_error(RuntimeError("chat not found"))


def test_is_button_data_invalid_error_detects_known_patterns() -> None:
    """Проверяет распознавание ошибки Telegram по невалидным callback-кнопкам."""

    assert _is_button_data_invalid_error(RuntimeError("Bad Request: BUTTON_DATA_INVALID"))


def test_is_button_data_invalid_error_returns_false_for_other_errors() -> None:
    """Проверяет, что посторонние ошибки не считаются BUTTON_DATA_INVALID."""

    assert not _is_button_data_invalid_error(RuntimeError("Bad Request: chat not found"))
