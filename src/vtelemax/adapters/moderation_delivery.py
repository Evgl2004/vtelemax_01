"""Утилита доставки pending-сообщений outbox в один проход.

Файл реализует MVP-контур:

1. Берем pending-сообщения из core use-case.
2. Пытаемся отправить каждое сообщение в целевой мессенджер ровно один раз.
3. Фиксируем результат (`sent` или `failed`) в базе.

Ретраи в этот этап не входят и будут добавлены отдельной задачей.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from loguru import logger

from vtelemax.core import (
    PendingModeratorDelivery,
    PlatformName,
    PullPendingModeratorMessagesTransactionalUseCase,
    SupportDeliveryStatus,
    SupportMessageAuthor,
    UpdateModeratorMessageDeliveryStatusCommand,
    UpdateModeratorMessageDeliveryStatusTransactionalUseCase,
)


@dataclass(slots=True)
class PendingModeratorDeliveryProcessor:
    """Оркестратор одноразовой доставки pending-сообщений модератора."""

    target_platform: PlatformName
    pull_pending_use_case: PullPendingModeratorMessagesTransactionalUseCase
    update_status_use_case: UpdateModeratorMessageDeliveryStatusTransactionalUseCase

    async def process_once(
        self,
        *,
        sender: Callable[[PendingModeratorDelivery, str], Awaitable[None]],
        limit: int = 20,
    ) -> tuple[int, int]:
        """Выполняет одну доставку очереди pending-сообщений.

        Args:
            sender: Асинхронный callback отправки (`delivery`, `text`).
            limit: Максимум сообщений за один проход.

        Returns:
            Кортеж `(sent_count, failed_count)`.
        """

        processor_logger = logger.bind(
            platform=self.target_platform,
            component="moderation_delivery",
            stage="process_once",
        )
        processor_logger.debug(
            "Старт обработки pending-сообщений модератора. limit={limit}.",
            limit=limit,
        )
        deliveries = self.pull_pending_use_case.execute(
            target_platform=self.target_platform,
            limit=limit,
        )
        sent_count = 0
        failed_count = 0
        processor_logger.debug(
            "Получено pending-сообщений: {count}.",
            count=len(deliveries),
        )

        for delivery in deliveries:
            message_logger = processor_logger.bind(
                stage="message_delivery",
                user_id=str(delivery.target_external_id),
            )
            external_id = str(delivery.target_external_id).strip()
            if not external_id:
                self._mark_failed(
                    message_id=delivery.message_id,
                    error_text="Пустой target_external_id для доставки.",
                )
                message_logger.warning(
                    "Сообщение {message_id} не доставлено: пустой target_external_id.",
                    message_id=delivery.message_id,
                )
                failed_count += 1
                continue

            text = self._build_delivery_text(author=delivery.author, body=delivery.body)
            try:
                await sender(delivery, text)
            except Exception as error:  # noqa: BLE001
                self._mark_failed(
                    message_id=delivery.message_id,
                    error_text=self._normalize_error_text(error),
                )
                message_logger.warning(
                    "Сообщение {message_id} не доставлено: {error}.",
                    message_id=delivery.message_id,
                    error=self._normalize_error_text(error),
                )
                failed_count += 1
                continue

            self.update_status_use_case.execute(
                UpdateModeratorMessageDeliveryStatusCommand(
                    message_id=delivery.message_id,
                    status=SupportDeliveryStatus.SENT,
                )
            )
            message_logger.debug(
                "Сообщение {message_id} успешно доставлено.",
                message_id=delivery.message_id,
            )
            sent_count += 1

        processor_logger.info(
            "Обработка pending-сообщений завершена. sent={sent}, failed={failed}.",
            sent=sent_count,
            failed=failed_count,
        )
        return sent_count, failed_count

    def _mark_failed(self, *, message_id: UUID, error_text: str) -> None:
        """Ставит статус `failed` для сообщения, где доставка не удалась."""

        self.update_status_use_case.execute(
            UpdateModeratorMessageDeliveryStatusCommand(
                message_id=message_id,
                status=SupportDeliveryStatus.FAILED,
                error_text=error_text,
            )
        )

    @staticmethod
    def _build_delivery_text(*, author: SupportMessageAuthor, body: str) -> str:
        """Формирует итоговый текст доставки по типу сообщения."""

        if author == SupportMessageAuthor.MODERATOR:
            return "\n".join(("📬 Ответ модератора:", body))
        return body

    @staticmethod
    def _normalize_error_text(error: Exception) -> str:
        """Нормализует текст ошибки доставки для записи в БД."""

        raw = str(error).strip()
        if not raw:
            return "Неизвестная ошибка доставки."
        return raw[:500]
