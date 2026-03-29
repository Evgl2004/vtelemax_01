"""In-memory реализация репозитория strict identity.

Модуль нужен для:

1. Юнит-тестов ядра без БД.
2. Прототипирования use-case до подключения PostgreSQL.
"""

from __future__ import annotations

from uuid import UUID

from .models import Person, PersonProfilePatch, PlatformAccount, PlatformName
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

    def get_person_by_id(self, person_id: UUID) -> Person | None:
        """Возвращает человека по внутреннему идентификатору."""

        return self._persons_by_id.get(person_id)

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

    def update_person_profile(self, person_id: UUID, patch: PersonProfilePatch) -> None:
        """Частично обновляет профиль человека в памяти."""

        person = self._persons_by_id[person_id]
        if patch.rules_accepted is not None:
            person.rules_accepted = patch.rules_accepted
        if patch.rules_accepted_at is not None:
            person.rules_accepted_at = patch.rules_accepted_at
        if patch.notifications_allowed is not None:
            person.notifications_allowed = patch.notifications_allowed
        if patch.notifications_allowed_at is not None:
            person.notifications_allowed_at = patch.notifications_allowed_at
        if patch.is_legacy is not None:
            person.is_legacy = patch.is_legacy
        if patch.is_registered is not None:
            person.is_registered = patch.is_registered
        if patch.first_name_input is not None:
            person.first_name_input = patch.first_name_input
        if patch.last_name_input is not None:
            person.last_name_input = patch.last_name_input
        if patch.gender is not None:
            person.gender = patch.gender
        if patch.birth_date is not None:
            person.birth_date = patch.birth_date
        if patch.email is not None:
            person.email = patch.email
        if patch.phone_verified_at is not None:
            person.phone_verified_at = patch.phone_verified_at
        if patch.phone_verification_method is not None:
            person.phone_verification_method = patch.phone_verification_method
