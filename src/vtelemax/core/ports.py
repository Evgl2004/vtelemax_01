"""Порты (контракты) доменного ядра strict identity.

Порты описывают интерфейсы, с которыми работает ядро.
Такой подход позволяет менять инфраструктуру (in-memory, PostgreSQL и т.д.)
без изменения бизнес-логики.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol
from uuid import UUID

from .models import Person, PersonProfilePatch, PlatformAccount, PlatformName


class IdentityRepository(Protocol):
    """Контракт репозитория идентификации."""

    def get_person_by_phone(self, phone_e164: str) -> Person | None:
        """Возвращает человека по каноническому телефону."""

    def get_person_by_account(self, platform: PlatformName, external_id: str) -> Person | None:
        """Возвращает человека по аккаунту платформы."""

    def get_person_by_id(self, person_id: UUID) -> Person | None:
        """Возвращает человека по внутреннему идентификатору."""

    def add_person(self, person: Person) -> None:
        """Сохраняет нового человека."""

    def attach_account(self, person_id: UUID, account: PlatformAccount) -> None:
        """Привязывает аккаунт к существующему человеку."""

    def update_person_profile(self, person_id: UUID, patch: PersonProfilePatch) -> None:
        """Частично обновляет профиль пользователя."""


class IdentityUnitOfWork(Protocol):
    """Контракт unit-of-work для операций strict identity.

    Через unit-of-work use-case работает с транзакцией как с единой
    атомарной границей сохранения.
    """

    identity_repository: IdentityRepository

    def __enter__(self) -> "IdentityUnitOfWork":
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
