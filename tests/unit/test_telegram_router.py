"""Тесты вспомогательных функций Telegram-роутера."""

from __future__ import annotations

from uuid import uuid4

import pytest

from vtelemax.adapters.telegram.router import (
    build_telegram_pending_delivery_sender,
    _is_button_data_invalid_error,
    _is_message_cant_be_edited_error,
    _is_message_not_modified_error,
)
from vtelemax.core import PendingModeratorDelivery, SupportMessageAuthor


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


def test_is_message_cant_be_edited_error_detects_known_patterns() -> None:
    """Проверяет распознавание ошибки Telegram «message can't be edited»."""

    assert _is_message_cant_be_edited_error(RuntimeError("Bad Request: message can't be edited"))
    assert _is_message_cant_be_edited_error(RuntimeError("BAD REQUEST: MESSAGE CANT BE EDITED"))


def test_is_message_cant_be_edited_error_returns_false_for_other_errors() -> None:
    """Проверяет, что посторонние ошибки не считаются «message can't be edited»."""

    assert not _is_message_cant_be_edited_error(RuntimeError("Bad Request: message is not modified"))


@pytest.mark.asyncio
async def test_telegram_pending_delivery_sender_adds_coupon_menu_button() -> None:
    """Проверяет кнопку перехода в купоны под Telegram-рассылкой купона."""

    class _FakeBot:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def send_message(self, **kwargs: object) -> None:
            self.calls.append(kwargs)

    bot = _FakeBot()
    sender = build_telegram_pending_delivery_sender(bot)
    await sender(
        PendingModeratorDelivery(
            message_id=uuid4(),
            author=SupportMessageAuthor.SYSTEM,
            ticket_id=uuid4(),
            source_platform="telegram",
            target_platform="telegram",
            target_external_id="1001",
            body="Код купона: E2E-OVT89GWN",
            created_at=None,
        ),
        "Код купона: E2E-OVT89GWN",
    )

    reply_markup = bot.calls[0]["reply_markup"]
    button = reply_markup.inline_keyboard[0][0]

    assert bot.calls[0]["chat_id"] == 1001
    assert button.text == "🎟️ Перейти к купонам"
    assert button.callback_data == "coupons"
