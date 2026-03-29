"""Доменные модели strict identity.

В модуле хранятся основные сущности ядра, независимые от инфраструктуры:

1. `Person` — человек в единой системе.
2. `PlatformAccount` — привязанный аккаунт конкретной платформы.
3. `PlatformName` — допустимые платформы на текущем этапе.
4. `PersonProfilePatch` — частичное обновление регистрационного профиля.
"""

from __future__ import annotations

from datetime import date, datetime
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

PlatformName = Literal["telegram", "vk", "max"]
SUPPORTED_PLATFORMS: tuple[PlatformName, ...] = ("telegram", "vk", "max")


@dataclass(frozen=True, slots=True)
class PlatformAccount:
    """Привязка аккаунта платформы к человеку.

    Args:
        platform: Название платформы (`telegram`, `vk`, `max`).
        external_id: Идентификатор пользователя в платформе.
    """

    platform: PlatformName
    external_id: str


@dataclass(slots=True)
class Person:
    """Доменная модель человека в strict identity.

    Args:
        person_id: Внутренний идентификатор человека.
        phone_e164: Канонический телефон в формате `+7XXXXXXXXXX`.
        accounts: Набор связанных аккаунтов мессенджеров.
        rules_accepted: Признак согласия с правилами и политикой ПДн.
        rules_accepted_at: Дата/время принятия правил.
        notifications_allowed: Выбор пользователя по уведомлениям.
        notifications_allowed_at: Дата/время фиксации выбора по уведомлениям.
        is_legacy: Признак legacy-профиля.
        is_registered: Признак завершения регистрации.
        first_name_input: Имя, введенное пользователем при регистрации.
        last_name_input: Фамилия, введенная пользователем при регистрации.
        gender: Пол пользователя.
        birth_date: Дата рождения.
        email: E-mail пользователя.
        phone_verified_at: Дата/время подтверждения телефона.
        phone_verification_method: Канал/способ подтверждения телефона.
    """

    person_id: UUID
    phone_e164: str
    accounts: set[PlatformAccount] = field(default_factory=set)
    rules_accepted: bool = False
    rules_accepted_at: datetime | None = None
    notifications_allowed: bool = False
    notifications_allowed_at: datetime | None = None
    is_legacy: bool = False
    is_registered: bool = False
    first_name_input: str | None = None
    last_name_input: str | None = None
    gender: str | None = None
    birth_date: date | None = None
    email: str | None = None
    phone_verified_at: datetime | None = None
    phone_verification_method: str | None = None


@dataclass(frozen=True, slots=True)
class PersonProfilePatch:
    """Частичное обновление регистрационных полей `Person`.

    Все поля опциональны. Если поле равно `None`, значение в профиле не меняется.
    Для булевых значений `False` считается валидным обновлением.
    """

    rules_accepted: bool | None = None
    rules_accepted_at: datetime | None = None
    notifications_allowed: bool | None = None
    notifications_allowed_at: datetime | None = None
    is_legacy: bool | None = None
    is_registered: bool | None = None
    first_name_input: str | None = None
    last_name_input: str | None = None
    gender: str | None = None
    birth_date: date | None = None
    email: str | None = None
    phone_verified_at: datetime | None = None
    phone_verification_method: str | None = None

    def has_updates(self) -> bool:
        """Проверяет, есть ли хотя бы одно поле для изменения."""

        return any(
            value is not None
            for value in (
                self.rules_accepted,
                self.rules_accepted_at,
                self.notifications_allowed,
                self.notifications_allowed_at,
                self.is_legacy,
                self.is_registered,
                self.first_name_input,
                self.last_name_input,
                self.gender,
                self.birth_date,
                self.email,
                self.phone_verified_at,
                self.phone_verification_method,
            )
        )
