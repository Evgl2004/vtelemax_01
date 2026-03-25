"""In-memory реализация репозитория поддержки и модерации."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from .models import PlatformName
from .support_models import (
    SupportDeliveryStatus,
    SupportMessage,
    SupportMessageAuthor,
    SupportTicket,
    SupportTicketStatus,
)
from .support_ports import SupportRepository


class InMemorySupportRepository(SupportRepository):
    """Репозиторий тикетов в оперативной памяти (для unit-тестов)."""

    def __init__(self) -> None:
        self._tickets_by_id: dict[UUID, SupportTicket] = {}
        self._messages_by_ticket: dict[UUID, list[SupportMessage]] = {}
        self._messages_by_id: dict[UUID, SupportMessage] = {}

    def create_ticket(self, ticket: SupportTicket) -> None:
        self._tickets_by_id[ticket.ticket_id] = ticket
        self._messages_by_ticket.setdefault(ticket.ticket_id, [])

    def get_ticket(self, ticket_id: UUID) -> SupportTicket | None:
        return self._tickets_by_id.get(ticket_id)

    def list_open_tickets(self, limit: int = 20) -> list[SupportTicket]:
        tickets = [ticket for ticket in self._tickets_by_id.values() if ticket.status == SupportTicketStatus.OPEN]
        tickets.sort(key=lambda item: item.created_at or datetime.fromtimestamp(0, tz=timezone.utc))
        return tickets[:limit]

    def list_person_tickets(self, person_id: UUID, limit: int = 20) -> list[SupportTicket]:
        tickets = [ticket for ticket in self._tickets_by_id.values() if ticket.person_id == person_id]
        tickets.sort(key=lambda item: item.created_at or datetime.fromtimestamp(0, tz=timezone.utc), reverse=True)
        return tickets[:limit]

    def update_ticket_last_guest_platform(self, ticket_id: UUID, platform: PlatformName) -> None:
        ticket = self._tickets_by_id[ticket_id]
        ticket.last_guest_platform = platform

    def add_message(self, message: SupportMessage) -> None:
        self._messages_by_ticket.setdefault(message.ticket_id, []).append(message)
        self._messages_by_id[message.message_id] = message

        if message.author == SupportMessageAuthor.GUEST:
            ticket = self._tickets_by_id.get(message.ticket_id)
            if ticket is not None:
                ticket.last_guest_platform = message.source_platform

    def list_messages(self, ticket_id: UUID) -> list[SupportMessage]:
        return list(self._messages_by_ticket.get(ticket_id, []))

    def pull_pending_moderator_messages(
        self,
        target_platform: PlatformName,
        limit: int = 20,
    ) -> list[SupportMessage]:
        messages = [
            message
            for message in self._messages_by_id.values()
            if message.author == SupportMessageAuthor.MODERATOR
            and message.target_platform == target_platform
            and message.delivery_status == SupportDeliveryStatus.CREATED
        ]
        messages.sort(key=lambda item: item.created_at or datetime.fromtimestamp(0, tz=timezone.utc))
        return messages[:limit]

    def update_message_delivery(
        self,
        message_id: UUID,
        status: SupportDeliveryStatus,
        error_text: str | None = None,
    ) -> None:
        message = self._messages_by_id[message_id]
        message.delivery_status = status
        message.delivery_error = error_text
