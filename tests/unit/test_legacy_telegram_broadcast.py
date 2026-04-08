"""Тесты утилит рассылки legacy Telegram-пользователям."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from vtelemax.tools.legacy_telegram_broadcast import (
    LegacyBroadcastTarget,
    LegacyBroadcastSelectionResult,
    LegacyBroadcastSendResult,
    build_default_legacy_broadcast_message,
    select_legacy_broadcast_targets,
    send_legacy_broadcast,
)
from vtelemax.tools.legacy_telegram_migration import LegacyTelegramSourceRecord


class TestBuildDefaultLegacyBroadcastMessage:
    """Тесты формирования текста рассылки."""

    def test_message_contains_required_elements(self) -> None:
        """Текст содержит ключевые элементы: приветствие, команду /start, ссылки, меню."""
        text = build_default_legacy_broadcast_message()

        assert "👋 Привет!" in text
        assert "/start" in text
        assert "vk.me/club236296391" in text
        assert "max.ru/id7203243481_bot" in text
        assert "💰 Мой баланс" in text
        assert "🪪 Карта" in text
        assert "🚚 Доставка" in text
        assert "❓ Мне только спросить" in text
        assert "✍️ Оставить отзыв" in text
        assert "👤 Профиль" in text
        assert "старые кнопки" in text


class TestSelectLegacyBroadcastTargets:
    """Тесты отбора получателей рассылки."""

    def test_empty_source_records(self) -> None:
        """Пустой список source-записей даёт пустой результат."""
        result = select_legacy_broadcast_targets([])

        assert len(result.targets) == 0
        assert result.invalid_telegram_id_rows == 0
        assert result.invalid_phone_rows == 0
        assert result.skipped_by_phone_filter == 0
        assert result.duplicate_telegram_id_rows == 0

    def test_valid_records_deduplicated(self) -> None:
        """Дубликаты telegram_user_id схлопываются."""
        records = [
            LegacyTelegramSourceRecord(
                telegram_user_id="123",
                raw_phone="+79129923438",
                created_at_raw="2025-01-01 12:00:00",
            ),
            LegacyTelegramSourceRecord(
                telegram_user_id="123",
                raw_phone="+79129923438",
                created_at_raw="2025-01-02 12:00:00",
            ),
            LegacyTelegramSourceRecord(
                telegram_user_id="456",
                raw_phone="+79129923439",
                created_at_raw="2025-01-03 12:00:00",
            ),
        ]
        result = select_legacy_broadcast_targets(records)

        assert len(result.targets) == 2
        user_ids = {t.telegram_user_id for t in result.targets}
        assert user_ids == {123, 456}
        assert result.duplicate_telegram_id_rows == 1

    def test_invalid_telegram_id_skipped(self) -> None:
        """Некорректные telegram_user_id пропускаются."""
        records = [
            LegacyTelegramSourceRecord(
                telegram_user_id="not_a_number",
                raw_phone="+79129923438",
                created_at_raw="2025-01-01 12:00:00",
            ),
            LegacyTelegramSourceRecord(
                telegram_user_id="456",
                raw_phone="+79129923439",
                created_at_raw="2025-01-02 12:00:00",
            ),
        ]
        result = select_legacy_broadcast_targets(records)

        assert len(result.targets) == 1
        assert result.targets[0].telegram_user_id == 456
        assert result.invalid_telegram_id_rows == 1

    def test_invalid_phone_skipped(self) -> None:
        """Некорректные телефоны отмечаются, но запись может быть включена."""
        records = [
            LegacyTelegramSourceRecord(
                telegram_user_id="123",
                raw_phone="invalid",
                created_at_raw="2025-01-01 12:00:00",
            ),
        ]
        result = select_legacy_broadcast_targets(records)

        assert len(result.targets) == 1
        assert result.targets[0].telegram_user_id == 123
        assert result.targets[0].phone_e164 is None
        assert result.invalid_phone_rows == 1

    def test_phone_filter(self) -> None:
        """Фильтр по номеру оставляет только совпадающие записи."""
        records = [
            LegacyTelegramSourceRecord(
                telegram_user_id="123",
                raw_phone="+79129923438",
                created_at_raw="2025-01-01 12:00:00",
            ),
            LegacyTelegramSourceRecord(
                telegram_user_id="456",
                raw_phone="+79129923439",
                created_at_raw="2025-01-02 12:00:00",
            ),
        ]
        result = select_legacy_broadcast_targets(
            records,
            phone_filter_e164="+79129923438",
        )

        assert len(result.targets) == 1
        assert result.targets[0].telegram_user_id == 123
        assert result.skipped_by_phone_filter == 1

    def test_phone_filter_with_invalid_phone(self) -> None:
        """При фильтре по номеру записи с невалидным телефоном пропускаются."""
        records = [
            LegacyTelegramSourceRecord(
                telegram_user_id="123",
                raw_phone="invalid",
                created_at_raw="2025-01-01 12:00:00",
            ),
        ]
        result = select_legacy_broadcast_targets(
            records,
            phone_filter_e164="+79129923438",
        )

        assert len(result.targets) == 0
        # invalid_phone_rows увеличивается, но skipped_by_phone_filter тоже?
        # В реализации при phone_filter_e164 != None и невалидном телефоне
        # увеличивается invalid_phone_rows и continue (пропуск).
        # Поэтому skipped_by_phone_filter не увеличивается.
        assert result.invalid_phone_rows == 1
        assert result.skipped_by_phone_filter == 0


class TestSendLegacyBroadcast:
    """Тесты отправки рассылки."""

    @pytest.fixture
    def mock_bot(self) -> AsyncMock:
        """Создает мок aiogram.Bot."""
        bot = AsyncMock()
        bot.send_message = AsyncMock()
        return bot

    @pytest.fixture
    def sample_targets(self) -> list[LegacyBroadcastTarget]:
        """Тестовые получатели."""
        return [
            LegacyBroadcastTarget(
                telegram_user_id=123,
                raw_phone="+79129923438",
                phone_e164="+79129923438",
            ),
            LegacyBroadcastTarget(
                telegram_user_id=456,
                raw_phone="+79129923439",
                phone_e164="+79129923439",
            ),
        ]

    @pytest.mark.asyncio
    async def test_successful_send_with_cleanup(
        self,
        mock_bot: AsyncMock,
        sample_targets: list[LegacyBroadcastTarget],
    ) -> None:
        """Успешная отправка очистки и сообщения."""
        # Настраиваем мок
        mock_bot.send_message.return_value = MagicMock()

        result = await send_legacy_broadcast(
            bot=mock_bot,
            targets=sample_targets,
            delay_seconds=0.01,
            cleanup_before_message=True,
        )

        # Проверяем вызовы
        assert mock_bot.send_message.call_count == 4  # 2 очистки + 2 сообщения
        calls = mock_bot.send_message.call_args_list
        # Очистка для 123
        assert calls[0].kwargs["chat_id"] == 123
        assert calls[0].kwargs["reply_markup"] is not None
        # Сообщение для 123
        assert calls[1].kwargs["chat_id"] == 123
        assert "Привет" in calls[1].kwargs["text"]
        # Очистка для 456
        assert calls[2].kwargs["chat_id"] == 456
        assert calls[2].kwargs["reply_markup"] is not None
        # Сообщение для 456
        assert calls[3].kwargs["chat_id"] == 456
        assert "Привет" in calls[3].kwargs["text"]

        # Проверяем результат
        assert result.total_targets == 2
        assert result.sent_cleanup == 2
        assert result.sent_messages == 2
        assert result.failed_cleanup == 0
        assert result.failed_messages == 0
        assert result.retry_after_errors == 0
        assert result.forbidden_errors == 0
        assert result.other_errors == 0

    @pytest.mark.asyncio
    async def test_send_without_cleanup(
        self,
        mock_bot: AsyncMock,
        sample_targets: list[LegacyBroadcastTarget],
    ) -> None:
        """Отправка без очистки кэша."""
        mock_bot.send_message.return_value = MagicMock()

        result = await send_legacy_broadcast(
            bot=mock_bot,
            targets=sample_targets,
            delay_seconds=0.01,
            cleanup_before_message=False,
        )

        # Только сообщения, без ReplyKeyboardRemove
        assert mock_bot.send_message.call_count == 2
        for call in mock_bot.send_message.call_args_list:
            assert "reply_markup" not in call.kwargs

        assert result.sent_cleanup == 0
        assert result.sent_messages == 2

    @pytest.mark.asyncio
    async def test_telegram_forbidden_error(
        self,
        mock_bot: AsyncMock,
        sample_targets: list[LegacyBroadcastTarget],
    ) -> None:
        """Ошибка 'бот заблокирован' при очистке."""
        from aiogram.exceptions import TelegramForbiddenError

        # Первый вызов (очистка) вызывает ошибку, второй успешен
        mock_bot.send_message.side_effect = [
            TelegramForbiddenError(method='sendMessage', message='Forbidden'),
            MagicMock(),  # очистка для второго пользователя
            MagicMock(),  # сообщение для второго пользователя
        ]

        result = await send_legacy_broadcast(
            bot=mock_bot,
            targets=sample_targets,
            delay_seconds=0.01,
            cleanup_before_message=True,
        )

        # Первый пользователь пропущен, второй обработан
        assert mock_bot.send_message.call_count == 3  # очистка1 (ошибка), очистка2, сообщение2
        assert result.sent_cleanup == 1
        assert result.sent_messages == 1
        assert result.forbidden_errors == 1
        assert result.failed_cleanup == 0  # ошибка Forbidden не считается failed_cleanup
        assert result.failed_messages == 0

    @pytest.mark.asyncio
    async def test_telegram_retry_after_error(
        self,
        mock_bot: AsyncMock,
        sample_targets: list[LegacyBroadcastTarget],
    ) -> None:
        """Ошибка лимита TelegramRetryAfter."""
        from aiogram.exceptions import TelegramRetryAfter

        # Первый вызов вызывает RetryAfter с retry_after=0.1
        mock_bot.send_message.side_effect = [
            TelegramRetryAfter(method='sendMessage', message='Too Many Requests', retry_after=0.1),
        ]

        result = await send_legacy_broadcast(
            bot=mock_bot,
            targets=sample_targets[:1],  # один пользователь
            delay_seconds=0.01,
            cleanup_before_message=True,
        )

        # После ошибки RetryAfter пользователь пропускается (continue)
        assert mock_bot.send_message.call_count == 1
        assert result.retry_after_errors == 1
        assert result.sent_cleanup == 0
        assert result.sent_messages == 0

    @pytest.mark.asyncio
    async def test_generic_error_during_message(
        self,
        mock_bot: AsyncMock,
        sample_targets: list[LegacyBroadcastTarget],
    ) -> None:
        """Общая ошибка при отправке сообщения."""
        from aiogram.exceptions import TelegramBadRequest

        mock_bot.send_message.side_effect = [
            MagicMock(),  # очистка успешна
            TelegramBadRequest(method='sendMessage', message='Bad request'),  # сообщение с ошибкой
        ]

        result = await send_legacy_broadcast(
            bot=mock_bot,
            targets=sample_targets[:1],
            delay_seconds=0.01,
            cleanup_before_message=True,
        )

        assert result.sent_cleanup == 1
        assert result.sent_messages == 0
        assert result.failed_messages == 1
        assert result.other_errors == 0  # TelegramBadRequest считается failed_messages

    @pytest.mark.asyncio
    async def test_delay_respected(
        self,
        mock_bot: AsyncMock,
        sample_targets: list[LegacyBroadcastTarget],
    ) -> None:
        """Задержка между отправками соблюдается."""
        import asyncio
        from unittest.mock import call

        mock_bot.send_message.return_value = MagicMock()
        # Заменим asyncio.sleep на мок, чтобы измерить вызовы
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await send_legacy_broadcast(
                bot=mock_bot,
                targets=sample_targets,
                delay_seconds=0.5,
                cleanup_before_message=True,
            )

            # Должен быть вызов sleep между пользователями (один раз)
            mock_sleep.assert_any_call(0.5)
            # Количество вызовов sleep: между пользователями (1) + возможно после ошибок нет
            assert mock_sleep.call_count == 1