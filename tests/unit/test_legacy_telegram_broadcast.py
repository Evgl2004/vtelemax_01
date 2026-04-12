"""Тесты инструментов рассылки legacy Telegram-пользователям."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage

from vtelemax.tools.legacy_telegram_broadcast import (
    LegacyBroadcastTarget,
    build_default_legacy_broadcast_message,
    select_legacy_broadcast_targets,
    send_legacy_broadcast,
)
from vtelemax.tools.legacy_telegram_migration import LegacyTelegramSourceRecord


def _method_stub() -> SendMessage:
    """Возвращает заглушку TelegramMethod для конструирования aiogram-исключений."""

    return SendMessage(chat_id=1, text="stub")


class TestBuildDefaultLegacyBroadcastMessage:
    """Проверки текста рассылки."""

    def test_message_contains_required_blocks(self) -> None:
        """Проверяет, что текст содержит команду /start, ссылки и пункты меню."""

        text = build_default_legacy_broadcast_message()
        assert "/start" in text
        assert "vk.me/club236296391" in text
        assert "max.ru/id7203243481_bot" in text
        assert "💰 Мой баланс" in text
        assert "🪪 Карта" in text
        assert "🚚 Доставка" in text
        assert "❓ Мне только спросить" in text
        assert "👤 Профиль" in text


class TestSelectLegacyBroadcastTargets:
    """Проверки отбора получателей из legacy source."""

    def test_deduplicates_targets_by_telegram_id(self) -> None:
        """Дубли Telegram ID схлопываются в одну цель."""

        rows = [
            LegacyTelegramSourceRecord("123", "+79129923438", "2025-01-01 00:00:00"),
            LegacyTelegramSourceRecord("123", "+79129923438", "2025-01-02 00:00:00"),
            LegacyTelegramSourceRecord("456", "+79129923439", "2025-01-03 00:00:00"),
        ]
        result = select_legacy_broadcast_targets(rows)
        assert len(result.targets) == 2
        assert result.duplicate_telegram_id_rows == 1

    def test_invalid_telegram_id_is_skipped(self) -> None:
        """Невалидный Telegram ID пропускается и считается в статистике."""

        rows = [
            LegacyTelegramSourceRecord("not_int", "+79129923438", "2025-01-01 00:00:00"),
            LegacyTelegramSourceRecord("456", "+79129923439", "2025-01-02 00:00:00"),
        ]
        result = select_legacy_broadcast_targets(rows)
        assert len(result.targets) == 1
        assert result.targets[0].telegram_user_id == 456
        assert result.invalid_telegram_id_rows == 1

    def test_phone_filter_selects_only_target_phone(self) -> None:
        """Фильтр по телефону оставляет только нужного получателя."""

        rows = [
            LegacyTelegramSourceRecord("123", "+79129923438", "2025-01-01 00:00:00"),
            LegacyTelegramSourceRecord("456", "+79129923439", "2025-01-02 00:00:00"),
        ]
        result = select_legacy_broadcast_targets(rows, phone_filter_e164="+79129923438")
        assert len(result.targets) == 1
        assert result.targets[0].telegram_user_id == 123
        assert result.skipped_by_phone_filter == 1

    def test_invalid_phone_without_filter_keeps_target(self) -> None:
        """Без фильтра запись с невалидным телефоном не теряется."""

        rows = [
            LegacyTelegramSourceRecord("123", "invalid_phone", "2025-01-01 00:00:00"),
        ]
        result = select_legacy_broadcast_targets(rows)
        assert len(result.targets) == 1
        assert result.targets[0].phone_e164 is None
        assert result.invalid_phone_rows == 1


class TestSendLegacyBroadcast:
    """Проверки отправки рассылки и классификации ошибок Telegram API."""

    @pytest.fixture
    def targets(self) -> list[LegacyBroadcastTarget]:
        """Возвращает тестовый список получателей."""

        return [
            LegacyBroadcastTarget(telegram_user_id=1001, raw_phone="+79129920001", phone_e164="+79129920001"),
            LegacyBroadcastTarget(telegram_user_id=1002, raw_phone="+79129920002", phone_e164="+79129920002"),
        ]

    @pytest.fixture
    def mock_bot(self) -> AsyncMock:
        """Создает мок aiogram.Bot для unit-тестов."""

        bot = AsyncMock()
        bot.send_message = AsyncMock()
        bot.token = "1234567890:ABCDEF1234567890"
        return bot

    @pytest.mark.asyncio
    async def test_success_with_cleanup(self, mock_bot: AsyncMock, targets: list[LegacyBroadcastTarget]) -> None:
        """При cleanup=True выполняются два шага на каждого получателя."""

        mock_bot.send_message.return_value = MagicMock()
        result = await send_legacy_broadcast(
            bot=mock_bot,
            targets=targets,
            delay_seconds=0.01,
            cleanup_before_message=True,
        )

        assert mock_bot.send_message.call_count == 4
        assert result.total_targets == 2
        assert result.sent_cleanup == 2
        assert result.sent_messages == 2
        assert result.failed_cleanup == 0
        assert result.failed_messages == 0
        assert result.chat_not_found_errors == 0

    @pytest.mark.asyncio
    async def test_success_without_cleanup_step(self, mock_bot: AsyncMock, targets: list[LegacyBroadcastTarget]) -> None:
        """При cleanup=False отправляется одно сообщение на пользователя с ReplyKeyboardRemove."""

        mock_bot.send_message.return_value = MagicMock()
        result = await send_legacy_broadcast(
            bot=mock_bot,
            targets=targets,
            delay_seconds=0.01,
            cleanup_before_message=False,
        )

        assert mock_bot.send_message.call_count == 2
        for call in mock_bot.send_message.call_args_list:
            assert call.kwargs.get("reply_markup") is not None
        assert result.sent_cleanup == 2
        assert result.sent_messages == 2

    @pytest.mark.asyncio
    async def test_classifies_chat_not_found(self, mock_bot: AsyncMock) -> None:
        """Ошибка chat not found учитывается отдельным счетчиком."""

        target = LegacyBroadcastTarget(telegram_user_id=1001, raw_phone="+79129920001", phone_e164="+79129920001")
        mock_bot.send_message.side_effect = [
            TelegramBadRequest(method=_method_stub(), message="Bad Request: chat not found"),
            MagicMock(),
        ]

        result = await send_legacy_broadcast(
            bot=mock_bot,
            targets=[target],
            delay_seconds=0.01,
            cleanup_before_message=True,
        )

        assert result.chat_not_found_errors == 1
        assert result.failed_cleanup == 1
        assert result.sent_messages == 1

    @pytest.mark.asyncio
    async def test_retry_after_on_cleanup_skips_user(self, mock_bot: AsyncMock) -> None:
        """RetryAfter на cleanup приводит к паузе и пропуску пользователя."""

        target = LegacyBroadcastTarget(telegram_user_id=1001, raw_phone="+79129920001", phone_e164="+79129920001")
        mock_bot.send_message.side_effect = [
            TelegramRetryAfter(method=_method_stub(), message="Too Many Requests", retry_after=1),
        ]

        with patch("vtelemax.tools.legacy_telegram_broadcast.asyncio.sleep", new_callable=AsyncMock) as mocked_sleep:
            result = await send_legacy_broadcast(
                bot=mock_bot,
                targets=[target],
                delay_seconds=0.01,
                cleanup_before_message=True,
            )

        assert mock_bot.send_message.call_count == 1
        assert mocked_sleep.await_count == 1
        assert result.retry_after_errors == 1
        assert result.sent_messages == 0

    @pytest.mark.asyncio
    async def test_retry_after_on_message_retries_once(self, mock_bot: AsyncMock) -> None:
        """RetryAfter на сообщении делает одну повторную попытку отправки."""

        target = LegacyBroadcastTarget(telegram_user_id=1001, raw_phone="+79129920001", phone_e164="+79129920001")
        mock_bot.send_message.side_effect = [
            TelegramRetryAfter(method=_method_stub(), message="Too Many Requests", retry_after=1),
            MagicMock(),
        ]

        with patch("vtelemax.tools.legacy_telegram_broadcast.asyncio.sleep", new_callable=AsyncMock):
            result = await send_legacy_broadcast(
                bot=mock_bot,
                targets=[target],
                delay_seconds=0.01,
                cleanup_before_message=False,
            )

        assert mock_bot.send_message.call_count == 2
        assert result.retry_after_errors == 1
        assert result.sent_messages == 1

    @pytest.mark.asyncio
    async def test_forbidden_error_is_classified(self, mock_bot: AsyncMock) -> None:
        """TelegramForbiddenError учитывается как blocked/forbidden."""

        target = LegacyBroadcastTarget(telegram_user_id=1001, raw_phone="+79129920001", phone_e164="+79129920001")
        mock_bot.send_message.side_effect = [
            TelegramForbiddenError(method=_method_stub(), message="Forbidden: bot was blocked by the user"),
        ]

        result = await send_legacy_broadcast(
            bot=mock_bot,
            targets=[target],
            delay_seconds=0.01,
            cleanup_before_message=False,
        )

        assert result.forbidden_errors == 1
        assert result.sent_messages == 0
        assert result.failed_messages == 1

