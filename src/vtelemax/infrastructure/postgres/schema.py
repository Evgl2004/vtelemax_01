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

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
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
