"""SQLAlchemy-схема strict identity для PostgreSQL.

Схема фиксирует строгую модель идентификации:

1. Один телефон (`phone_e164`) принадлежит только одному человеку.
2. Одна пара (`platform`, `external_id`) принадлежит только одному человеку.
3. Каждый человек имеет ровно один активный канонический телефон на текущем этапе.

В будущем таблица `phones` может быть расширена до истории номеров
и статусов подтверждения, но базовые ограничения strict identity
сохраняются неизменными.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Базовый declarative-класс для ORM-сущностей PostgreSQL."""


class PersonRow(Base):
    """Таблица `persons` — единый человек в системе."""

    __tablename__ = "persons"

    person_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    rules_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    rules_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notifications_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    notifications_allowed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_legacy: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_registered: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    first_name_input: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name_input: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    phone_verification_method: Mapped[str | None] = mapped_column(String(20), nullable=True)


class PhoneRow(Base):
    """Таблица `phones` — канонический телефон человека.

    Ограничения strict identity:

    1. `phone_e164` уникален в системе.
    2. `person_id` уникален (один человек = один основной телефон).
    """

    __tablename__ = "phones"
    __table_args__ = (
        UniqueConstraint("phone_e164", name="uq_phones_phone_e164"),
        UniqueConstraint("person_id", name="uq_phones_person_id"),
    )

    phone_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    person_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("persons.person_id", ondelete="CASCADE"),
        nullable=False,
    )
    phone_e164: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class PlatformAccountRow(Base):
    """Таблица `platform_accounts` — аккаунты Telegram/VK/MAX пользователя."""

    __tablename__ = "platform_accounts"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "external_id",
            name="uq_platform_accounts_platform_external_id",
        ),
        CheckConstraint(
            "platform IN ('telegram', 'vk', 'max')",
            name="ck_platform_accounts_platform_allowed",
        ),
        Index("ix_platform_accounts_person_id", "person_id"),
    )

    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    person_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("persons.person_id", ondelete="CASCADE"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class SupportTicketRow(Base):
    """Таблица `support_tickets` — тикеты поддержки, привязанные к Person."""

    __tablename__ = "support_tickets"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'closed')", name="ck_support_tickets_status_allowed"),
        CheckConstraint(
            "source_platform IN ('telegram', 'vk', 'max')",
            name="ck_support_tickets_source_platform_allowed",
        ),
        CheckConstraint(
            "last_guest_platform IS NULL OR last_guest_platform IN ('telegram', 'vk', 'max')",
            name="ck_support_tickets_last_guest_platform_allowed",
        ),
        Index("ix_support_tickets_person_id", "person_id"),
        Index("ix_support_tickets_status", "status"),
    )

    ticket_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    person_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("persons.person_id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    source_platform: Mapped[str] = mapped_column(String(16), nullable=False)
    last_guest_platform: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SupportMessageRow(Base):
    """Таблица `support_messages` — сообщения тикета и маршрутизация доставки."""

    __tablename__ = "support_messages"
    __table_args__ = (
        CheckConstraint("author IN ('guest', 'moderator')", name="ck_support_messages_author_allowed"),
        CheckConstraint(
            "source_platform IN ('telegram', 'vk', 'max')",
            name="ck_support_messages_source_platform_allowed",
        ),
        CheckConstraint(
            "target_platform IS NULL OR target_platform IN ('telegram', 'vk', 'max')",
            name="ck_support_messages_target_platform_allowed",
        ),
        CheckConstraint(
            "delivery_status IS NULL OR delivery_status IN ('created', 'sent', 'failed')",
            name="ck_support_messages_delivery_status_allowed",
        ),
        Index("ix_support_messages_ticket_id", "ticket_id"),
        Index("ix_support_messages_target_platform_status", "target_platform", "delivery_status"),
    )

    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    ticket_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("support_tickets.ticket_id", ondelete="CASCADE"),
        nullable=False,
    )
    author: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text(), nullable=False)
    source_platform: Mapped[str] = mapped_column(String(16), nullable=False)
    target_platform: Mapped[str | None] = mapped_column(String(16), nullable=True)
    target_external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    delivery_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    delivery_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
