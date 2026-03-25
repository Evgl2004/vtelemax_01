"""SQLAlchemy-репозиторий поддержки и модерации."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid import UUID

from vtelemax.core.models import PlatformName
from vtelemax.core.support_models import (
    SupportDeliveryStatus,
    SupportMessage,
    SupportMessageAuthor,
    SupportTicket,
    SupportTicketStatus,
)
from vtelemax.core.support_ports import SupportRepository

from .schema import SupportMessageRow, SupportTicketRow


class SQLAlchemySupportRepository(SupportRepository):
    """Репозиторий тикетов и модерации на базе SQLAlchemy Session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_ticket(self, ticket: SupportTicket) -> None:
        self._session.add(
            SupportTicketRow(
                ticket_id=ticket.ticket_id,
                person_id=ticket.person_id,
                status=ticket.status.value,
                source_platform=ticket.source_platform,
                last_guest_platform=ticket.last_guest_platform,
                closed_at=ticket.closed_at,
            )
        )
        # Явный flush фиксирует порядок INSERT:
        # сначала ticket, затем связанные messages в рамках одной транзакции.
        # Это важно для PostgreSQL с реальной проверкой FK.
        self._session.flush()

    def get_ticket(self, ticket_id: UUID) -> SupportTicket | None:
        row = self._session.get(SupportTicketRow, ticket_id)
        if row is None:
            return None
        return self._to_ticket(row)

    def list_open_tickets(self, limit: int = 20) -> list[SupportTicket]:
        statement = (
            select(SupportTicketRow)
            .where(SupportTicketRow.status == SupportTicketStatus.OPEN.value)
            .order_by(SupportTicketRow.created_at.desc())
            .limit(limit)
        )
        rows = self._session.execute(statement).scalars().all()
        return [self._to_ticket(row) for row in rows]

    def list_person_tickets(self, person_id: UUID, limit: int = 20) -> list[SupportTicket]:
        statement = (
            select(SupportTicketRow)
            .where(SupportTicketRow.person_id == person_id)
            .order_by(SupportTicketRow.created_at.desc())
            .limit(limit)
        )
        rows = self._session.execute(statement).scalars().all()
        return [self._to_ticket(row) for row in rows]

    def update_ticket_last_guest_platform(self, ticket_id: UUID, platform: PlatformName) -> None:
        row = self._session.get(SupportTicketRow, ticket_id)
        if row is None:
            raise ValueError("Тикет не найден.")
        row.last_guest_platform = platform

    def add_message(self, message: SupportMessage) -> None:
        self._session.add(
            SupportMessageRow(
                message_id=message.message_id,
                ticket_id=message.ticket_id,
                author=message.author.value,
                body=message.body,
                source_platform=message.source_platform,
                target_platform=message.target_platform,
                target_external_id=message.target_external_id,
                delivery_status=message.delivery_status.value if message.delivery_status else None,
                delivery_error=message.delivery_error,
            )
        )
        if message.author == SupportMessageAuthor.GUEST:
            ticket_row = self._session.get(SupportTicketRow, message.ticket_id)
            if ticket_row is not None:
                ticket_row.last_guest_platform = message.source_platform

    def list_messages(self, ticket_id: UUID) -> list[SupportMessage]:
        statement = (
            select(SupportMessageRow)
            .where(SupportMessageRow.ticket_id == ticket_id)
            .order_by(SupportMessageRow.created_at.asc())
        )
        rows = self._session.execute(statement).scalars().all()
        return [self._to_message(row) for row in rows]

    def pull_pending_moderator_messages(
        self,
        target_platform: PlatformName,
        limit: int = 20,
    ) -> list[SupportMessage]:
        statement = (
            select(SupportMessageRow)
            .where(
                SupportMessageRow.author == SupportMessageAuthor.MODERATOR.value,
                SupportMessageRow.target_platform == target_platform,
                SupportMessageRow.delivery_status == SupportDeliveryStatus.CREATED.value,
            )
            .order_by(SupportMessageRow.created_at.asc())
            .limit(limit)
        )
        rows = self._session.execute(statement).scalars().all()
        return [self._to_message(row) for row in rows]

    def update_message_delivery(
        self,
        message_id: UUID,
        status: SupportDeliveryStatus,
        error_text: str | None = None,
    ) -> None:
        row = self._session.get(SupportMessageRow, message_id)
        if row is None:
            raise ValueError("Сообщение модератора не найдено.")
        row.delivery_status = status.value
        row.delivery_error = error_text

    @staticmethod
    def _to_ticket(row: SupportTicketRow) -> SupportTicket:
        return SupportTicket(
            ticket_id=row.ticket_id,
            person_id=row.person_id,
            source_platform=row.source_platform,  # type: ignore[arg-type]
            status=SupportTicketStatus(row.status),
            created_at=row.created_at,
            closed_at=row.closed_at,
            last_guest_platform=row.last_guest_platform,  # type: ignore[arg-type]
        )

    @staticmethod
    def _to_message(row: SupportMessageRow) -> SupportMessage:
        return SupportMessage(
            message_id=row.message_id,
            ticket_id=row.ticket_id,
            author=SupportMessageAuthor(row.author),
            body=row.body,
            source_platform=row.source_platform,  # type: ignore[arg-type]
            target_platform=row.target_platform,  # type: ignore[arg-type]
            target_external_id=row.target_external_id,
            delivery_status=SupportDeliveryStatus(row.delivery_status) if row.delivery_status else None,
            delivery_error=row.delivery_error,
            created_at=row.created_at,
        )
