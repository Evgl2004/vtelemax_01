"""Порты (контракты) доменного слоя поддержки и модерации."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol
from uuid import UUID

from .models import PlatformName
from .ports import IdentityRepository
from .support_models import SupportDeliveryStatus, SupportMessage, SupportTicket


class SupportRepository(Protocol):
    """Контракт репозитория тикетов и сообщений поддержки."""

    def create_ticket(self, ticket: SupportTicket) -> None:
        """Сохраняет новый тикет."""

    def get_ticket(self, ticket_id: UUID) -> SupportTicket | None:
        """Возвращает тикет по идентификатору."""

    def list_open_tickets(self, limit: int = 20) -> list[SupportTicket]:
        """Возвращает список открытых тикетов."""

    def update_ticket_last_guest_platform(self, ticket_id: UUID, platform: PlatformName) -> None:
        """Обновляет канал последней активности гостя."""

    def add_message(self, message: SupportMessage) -> None:
        """Сохраняет сообщение тикета."""

    def list_messages(self, ticket_id: UUID) -> list[SupportMessage]:
        """Возвращает сообщения тикета в порядке создания."""

    def pull_pending_moderator_messages(
        self,
        target_platform: PlatformName,
        limit: int = 20,
    ) -> list[SupportMessage]:
        """Возвращает сообщения модератора, ожидающие доставки в платформу."""

    def update_message_delivery(
        self,
        message_id: UUID,
        status: SupportDeliveryStatus,
        error_text: str | None = None,
    ) -> None:
        """Обновляет статус доставки сообщения модератора."""


class SupportUnitOfWork(Protocol):
    """Контракт UoW для сценариев модерации и поддержки."""

    identity_repository: IdentityRepository
    support_repository: SupportRepository

    def __enter__(self) -> "SupportUnitOfWork":
        """Открывает транзакционный контекст."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Закрывает транзакционный контекст."""

    def commit(self) -> None:
        """Подтверждает транзакцию."""

    def rollback(self) -> None:
        """Откатывает транзакцию."""

