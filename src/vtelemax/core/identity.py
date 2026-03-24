"""Строгая модель идентификации пользователя по телефону.

Этот модуль реализует стартовую доменную модель strict identity:

1. Один канонический телефон принадлежит только одному человеку.
2. Один аккаунт платформы (`platform + external_id`) может быть привязан только к одному человеку.
3. Попытка конфликтной перепривязки считается доменной ошибкой.

Реализация сделана in-memory для ранних unit-тестов и прототипирования
бизнес-правил до подключения постоянного хранилища.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID, uuid4

from .phone import normalize_phone

PlatformName = Literal["telegram", "vk", "max"]


class IdentityConflictError(ValueError):
    """Ошибка конфликта строгой идентификации.

    Поднимается, когда:

    1. Один и тот же аккаунт платформы пытаются связать с другим телефоном.
    2. Один и тот же телефон пытаются связать с аккаунтом, уже привязанным к другому человеку.
    """


@dataclass(frozen=True, slots=True)
class PlatformAccount:
    """Привязка аккаунта платформы к человеку."""

    platform: PlatformName
    external_id: str


@dataclass(slots=True)
class Person:
    """Доменная модель человека в strict identity.

    Args:
        person_id: Внутренний идентификатор человека.
        phone_e164: Канонический телефон в формате `+7XXXXXXXXXX`.
        accounts: Набор связанных аккаунтов мессенджеров.
    """

    person_id: UUID
    phone_e164: str
    accounts: set[PlatformAccount] = field(default_factory=set)


class StrictIdentityService:
    """In-memory сервис строгой идентификации.

    Сервис хранит три индекса:

    1. `phone -> person_id`
    2. `platform+external_id -> person_id`
    3. `person_id -> Person`
    """

    def __init__(self) -> None:
        self._persons_by_id: dict[UUID, Person] = {}
        self._person_id_by_phone: dict[str, UUID] = {}
        self._person_id_by_account: dict[tuple[PlatformName, str], UUID] = {}

    def register_or_attach_account(
        self,
        platform: PlatformName,
        external_id: str,
        raw_phone: str,
    ) -> Person:
        """Регистрирует или до-привязывает аккаунт к человеку.

        Правила:

        1. Телефон нормализуется в канонический формат.
        2. Если по телефону уже есть человек — аккаунт привязывается к нему.
        3. Если по аккаунту уже есть человек — сверяем, что телефон совпадает.
        4. Если телефон и аккаунт указывают на разных людей — поднимаем конфликт.
        """

        external_id_value = str(external_id).strip()
        if not external_id_value:
            raise ValueError("Внешний идентификатор аккаунта не может быть пустым.")

        phone_e164 = normalize_phone(raw_phone)
        account_key = (platform, external_id_value)

        person_id_by_phone = self._person_id_by_phone.get(phone_e164)
        person_id_by_account = self._person_id_by_account.get(account_key)

        if (
            person_id_by_phone is not None
            and person_id_by_account is not None
            and person_id_by_phone != person_id_by_account
        ):
            raise IdentityConflictError(
                "Конфликт strict identity: телефон и аккаунт уже привязаны к разным людям."
            )

        person_id = person_id_by_phone or person_id_by_account

        if person_id is None:
            person = Person(person_id=uuid4(), phone_e164=phone_e164)
            self._persons_by_id[person.person_id] = person
            self._person_id_by_phone[phone_e164] = person.person_id
        else:
            person = self._persons_by_id[person_id]
            if person.phone_e164 != phone_e164:
                raise IdentityConflictError(
                    "Конфликт strict identity: аккаунт уже связан с другим телефоном."
                )

        account = PlatformAccount(platform=platform, external_id=external_id_value)
        person.accounts.add(account)
        self._person_id_by_account[account_key] = person.person_id
        self._person_id_by_phone[person.phone_e164] = person.person_id
        return person

    def get_person_by_phone(self, raw_phone: str) -> Person | None:
        """Возвращает человека по телефону, если он уже зарегистрирован."""

        phone_e164 = normalize_phone(raw_phone)
        person_id = self._person_id_by_phone.get(phone_e164)
        if person_id is None:
            return None
        return self._persons_by_id[person_id]

    def get_person_by_account(self, platform: PlatformName, external_id: str) -> Person | None:
        """Возвращает человека по аккаунту платформы."""

        account_key = (platform, str(external_id).strip())
        person_id = self._person_id_by_account.get(account_key)
        if person_id is None:
            return None
        return self._persons_by_id[person_id]

