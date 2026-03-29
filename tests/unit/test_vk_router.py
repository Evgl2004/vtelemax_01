"""Тесты вспомогательных функций VK-роутера."""

from __future__ import annotations

from vtelemax.adapters.vk.router import _is_message_not_modified_error, _normalize_vk_message


def test_is_message_not_modified_error_detects_known_patterns() -> None:
    """Проверяет распознавание служебной ошибки «сообщение не изменилось»."""

    assert _is_message_not_modified_error(RuntimeError("Message is not modified"))
    assert _is_message_not_modified_error(RuntimeError("message is same as before"))


def test_is_message_not_modified_error_returns_false_for_other_errors() -> None:
    """Проверяет, что посторонние ошибки не считаются «not modified»."""

    assert not _is_message_not_modified_error(RuntimeError("invalid access token"))


def test_normalize_vk_message_strips_markdown_when_needed() -> None:
    """Проверяет, что markdown-текст приводится к плоскому виду для VK."""

    text, parse_mode = _normalize_vk_message("*Жирный* `код`", "markdown")

    assert text == "Жирный код"
    assert parse_mode is None

