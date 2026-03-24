"""Порты (контракты) доменного ядра strict identity.

Порты описывают интерфейсы, с которыми работает ядро.
Такой подход позволяет менять инфраструктуру (in-memory, PostgreSQL и т.д.)
без изменения бизнес-логики.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from .models import Person, PlatformAccount, PlatformName


class IdentityRepository(Protocol):
    """Контракт репозитория идентификации."""

    def get_person_by_phone(self, phone_e164: str) -> Person | None:
        """Возвращает человека по каноническому телефону."""

    def get_person_by_account(self, platform: PlatformName, external_id: str) -> Person | None:
        """Возвращает человека по аккаунту платформы."""

    def add_person(self, person: Person) -> None:
        """Сохраняет нового человека."""

    def attach_account(self, person_id: UUID, account: PlatformAccount) -> None:
        """Привязывает аккаунт к существующему человеку."""
