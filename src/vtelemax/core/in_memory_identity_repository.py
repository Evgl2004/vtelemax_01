"""In-memory реализация репозитория strict identity.

Модуль нужен для:

1. Юнит-тестов ядра без БД.
2. Прототипирования use-case до подключения PostgreSQL.
"""

from __future__ import annotations

from uuid import UUID

from .models import Person, PlatformAccount, PlatformName
from .ports import IdentityRepository


class InMemoryIdentityRepository(IdentityRepository):
    """Репозиторий strict identity в оперативной памяти."""

    def __init__(self) -> None:
        self._persons_by_id: dict[UUID, Person] = {}
        self._person_id_by_phone: dict[str, UUID] = {}
        self._person_id_by_account: dict[tuple[PlatformName, str], UUID] = {}

    def get_person_by_phone(self, phone_e164: str) -> Person | None:
        """Возвращает человека по каноническому телефону."""

        person_id = self._person_id_by_phone.get(phone_e164)
        if person_id is None:
            return None
        return self._persons_by_id[person_id]

    def get_person_by_account(self, platform: PlatformName, external_id: str) -> Person | None:
        """Возвращает человека по платформенному аккаунту."""

        person_id = self._person_id_by_account.get((platform, external_id))
        if person_id is None:
            return None
        return self._persons_by_id[person_id]

    def add_person(self, person: Person) -> None:
        """Сохраняет нового человека и его индексы."""

        self._persons_by_id[person.person_id] = person
        self._person_id_by_phone[person.phone_e164] = person.person_id
        for account in person.accounts:
            self._person_id_by_account[(account.platform, account.external_id)] = person.person_id

    def attach_account(self, person_id: UUID, account: PlatformAccount) -> None:
        """Привязывает аккаунт к существующему человеку."""

        person = self._persons_by_id[person_id]
        person.accounts.add(account)
        self._person_id_by_account[(account.platform, account.external_id)] = person.person_id
        self._person_id_by_phone[person.phone_e164] = person.person_id
