"""Доменные модели поддержки и модерации.

Модуль реализует person-centric подход:

1. Тикет связан с `Person`, а не с конкретным мессенджером.
2. Сообщения тикета знают канал источника и канал доставки.
3. Ответ модератора может быть маршрутизирован в любой подключенный канал гостя.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from .models import PlatformName


class SupportTicketStatus(StrEnum):
    """Статусы тикета поддержки."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class SupportMessageAuthor(StrEnum):
    """Автор сообщения тикета."""

    GUEST = "guest"
    MODERATOR = "moderator"
    SYSTEM = "system"


class SupportDeliveryStatus(StrEnum):
    """Статус доставки модераторского сообщения."""

    CREATED = "created"
    SENT = "sent"
    FAILED = "failed"


@dataclass(slots=True)
class SupportTicket:
    """Доменная модель тикета поддержки."""

    ticket_id: UUID
    person_id: UUID
    source_platform: PlatformName
    status: SupportTicketStatus
    created_at: datetime | None = None
    closed_at: datetime | None = None
    last_guest_platform: PlatformName | None = None
    last_guest_external_id: str | None = None


@dataclass(slots=True)
class SupportMessage:
    """Доменная модель сообщения тикета."""

    message_id: UUID
    ticket_id: UUID
    author: SupportMessageAuthor
    body: str
    source_platform: PlatformName
    created_at: datetime | None = None
    target_platform: PlatformName | None = None
    target_external_id: str | None = None
    delivery_status: SupportDeliveryStatus | None = None
    delivery_error: str | None = None
