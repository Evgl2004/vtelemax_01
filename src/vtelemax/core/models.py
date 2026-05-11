"""Доменные модели strict identity.

В модуле хранятся основные сущности ядра, независимые от инфраструктуры:

1. `Person` — человек в единой системе.
2. `PlatformAccount` — привязанный аккаунт конкретной платформы.
3. `PlatformRegistrationState` — отдельное состояние регистрации/согласий по платформе.
4. `PlatformName` — допустимые платформы на текущем этапе.
5. `PersonProfilePatch` — частичное обновление регистрационного профиля.
"""

from __future__ import annotations

from datetime import date, datetime
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

PlatformName = Literal["telegram", "vk", "max"]
SUPPORTED_PLATFORMS: tuple[PlatformName, ...] = ("telegram", "vk", "max")
PlatformAccountLifecycleStatus = Literal["active", "pending_verification", "historical"]
SUPPORTED_PLATFORM_ACCOUNT_LIFECYCLE_STATUSES: tuple[PlatformAccountLifecycleStatus, ...] = (
    "active",
    "pending_verification",
    "historical",
)


@dataclass(frozen=True, slots=True)
class PlatformAccount:
    """Привязка аккаунта платформы к человеку.

    Args:
        platform: Название платформы (`telegram`, `vk`, `max`).
        external_id: Идентификатор пользователя в платформе.
    """

    platform: PlatformName
    external_id: str
    lifecycle_status: PlatformAccountLifecycleStatus = field(default="active", compare=False)


@dataclass(slots=True)
class PlatformRegistrationState:
    """Платформо-специфичное состояние onboarding/регистрации.

    Поля отражают юридические согласия и факт завершения регистрации
    отдельно для каждого канала (Telegram/VK/MAX).
    """

    platform: PlatformName
    rules_accepted: bool = False
    rules_accepted_at: datetime | None = None
    notifications_allowed: bool = False
    notifications_allowed_at: datetime | None = None
    is_registered: bool = False
    registered_at: datetime | None = None


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
    is_moderator: bool = False
    is_registered: bool = False
    first_name_input: str | None = None
    last_name_input: str | None = None
    gender: str | None = None
    birth_date: date | None = None
    email: str | None = None
    phone_verified_at: datetime | None = None
    phone_verification_method: str | None = None
    platform_states: dict[PlatformName, PlatformRegistrationState] = field(default_factory=dict)

    # Legacy-поля оставлены временно для обратной совместимости с текущими тестами/скриптами.
    rules_accepted_tg: bool = False
    rules_accepted_tg_at: datetime | None = None
    rules_accepted_vk: bool = False
    rules_accepted_vk_at: datetime | None = None
    rules_accepted_max: bool = False
    rules_accepted_max_at: datetime | None = None
    notifications_allowed_tg: bool = False
    notifications_allowed_tg_at: datetime | None = None
    notifications_allowed_vk: bool = False
    notifications_allowed_vk_at: datetime | None = None
    notifications_allowed_max: bool = False
    notifications_allowed_max_at: datetime | None = None

    def get_platform_state(self, platform: PlatformName) -> PlatformRegistrationState:
        """Возвращает состояние регистрации для платформы.

        Если состояние отсутствует в новой модели `platform_states`, формируется fallback
        из legacy-полей `rules_accepted_*`/`notifications_allowed_*`.
        """

        state = self.platform_states.get(platform)
        if state is not None:
            return state

        legacy_rules_accepted, legacy_rules_accepted_at = self._legacy_rules_fields(platform)
        legacy_notifications_allowed, legacy_notifications_allowed_at = self._legacy_notifications_fields(platform)
        legacy_registered = bool(
            self.is_registered
            and legacy_rules_accepted
            and legacy_notifications_allowed_at is not None
        )
        fallback_state = PlatformRegistrationState(
            platform=platform,
            rules_accepted=legacy_rules_accepted,
            rules_accepted_at=legacy_rules_accepted_at,
            notifications_allowed=legacy_notifications_allowed,
            notifications_allowed_at=legacy_notifications_allowed_at,
            is_registered=legacy_registered,
            registered_at=None,
        )
        self.platform_states[platform] = fallback_state
        self._sync_global_registration_flag()
        return fallback_state

    def set_platform_state(self, state: PlatformRegistrationState) -> None:
        """Сохраняет платформенное состояние и синхронизирует агрегированные флаги."""

        self.platform_states[state.platform] = state
        self._sync_legacy_platform_fields(state)
        self._sync_global_registration_flag()

    def is_registered_for_platform(self, platform: PlatformName) -> bool:
        """Проверяет факт завершения регистрации для конкретной платформы."""

        return self.get_platform_state(platform).is_registered

    def get_rules_accepted_for_platform(self, platform: PlatformName) -> bool:
        """Возвращает признак согласия с правилами для указанной платформы."""
        return self.get_platform_state(platform).rules_accepted

    def get_rules_accepted_at_for_platform(self, platform: PlatformName) -> datetime | None:
        """Возвращает дату согласия с правилами для указанной платформы."""
        return self.get_platform_state(platform).rules_accepted_at

    def get_notifications_allowed_for_platform(self, platform: PlatformName) -> bool:
        """Возвращает признак разрешения уведомлений для указанной платформы."""
        return self.get_platform_state(platform).notifications_allowed

    def get_notifications_allowed_at_for_platform(self, platform: PlatformName) -> datetime | None:
        """Возвращает дату разрешения уведомлений для указанной платформы."""
        return self.get_platform_state(platform).notifications_allowed_at

    def get_registered_at_for_platform(self, platform: PlatformName) -> datetime | None:
        """Возвращает дату завершения регистрации для указанной платформы."""

        return self.get_platform_state(platform).registered_at

    def _sync_global_registration_flag(self) -> None:
        """Синхронизирует агрегированный `is_registered` для обратной совместимости."""

        self.is_registered = any(
            self.platform_states.get(platform, PlatformRegistrationState(platform=platform)).is_registered
            for platform in SUPPORTED_PLATFORMS
        )

    def _sync_legacy_platform_fields(self, state: PlatformRegistrationState) -> None:
        """Обновляет legacy-поля согласий из новой платформенной модели."""

        if state.platform == "telegram":
            self.rules_accepted_tg = state.rules_accepted
            self.rules_accepted_tg_at = state.rules_accepted_at
            self.notifications_allowed_tg = state.notifications_allowed
            self.notifications_allowed_tg_at = state.notifications_allowed_at
            return
        if state.platform == "vk":
            self.rules_accepted_vk = state.rules_accepted
            self.rules_accepted_vk_at = state.rules_accepted_at
            self.notifications_allowed_vk = state.notifications_allowed
            self.notifications_allowed_vk_at = state.notifications_allowed_at
            return
        if state.platform == "max":
            self.rules_accepted_max = state.rules_accepted
            self.rules_accepted_max_at = state.rules_accepted_at
            self.notifications_allowed_max = state.notifications_allowed
            self.notifications_allowed_max_at = state.notifications_allowed_at
            return
        raise ValueError(f"Неподдерживаемая платформа: {state.platform}")

    def _legacy_rules_fields(self, platform: PlatformName) -> tuple[bool, datetime | None]:
        """Возвращает legacy-поля согласия с правилами по платформе."""

        if platform == "telegram":
            return self.rules_accepted_tg, self.rules_accepted_tg_at
        if platform == "vk":
            return self.rules_accepted_vk, self.rules_accepted_vk_at
        if platform == "max":
            return self.rules_accepted_max, self.rules_accepted_max_at
        raise ValueError(f"Неподдерживаемая платформа: {platform}")

    def _legacy_notifications_fields(self, platform: PlatformName) -> tuple[bool, datetime | None]:
        """Возвращает legacy-поля согласия на рассылку по платформе."""

        if platform == "telegram":
            return self.notifications_allowed_tg, self.notifications_allowed_tg_at
        if platform == "vk":
            return self.notifications_allowed_vk, self.notifications_allowed_vk_at
        if platform == "max":
            return self.notifications_allowed_max, self.notifications_allowed_max_at
        raise ValueError(f"Неподдерживаемая платформа: {platform}")


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
    is_moderator: bool | None = None
    is_registered: bool | None = None
    first_name_input: str | None = None
    last_name_input: str | None = None
    gender: str | None = None
    birth_date: date | None = None
    email: str | None = None
    phone_verified_at: datetime | None = None
    phone_verification_method: str | None = None
    rules_accepted_tg: bool | None = None
    rules_accepted_tg_at: datetime | None = None
    rules_accepted_vk: bool | None = None
    rules_accepted_vk_at: datetime | None = None
    rules_accepted_max: bool | None = None
    rules_accepted_max_at: datetime | None = None
    notifications_allowed_tg: bool | None = None
    notifications_allowed_tg_at: datetime | None = None
    notifications_allowed_vk: bool | None = None
    notifications_allowed_vk_at: datetime | None = None
    notifications_allowed_max: bool | None = None
    notifications_allowed_max_at: datetime | None = None
    platform: PlatformName | None = None
    platform_rules_accepted: bool | None = None
    platform_rules_accepted_at: datetime | None = None
    platform_notifications_allowed: bool | None = None
    platform_notifications_allowed_at: datetime | None = None
    platform_is_registered: bool | None = None
    platform_registered_at: datetime | None = None

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
                self.is_moderator,
                self.is_registered,
                self.first_name_input,
                self.last_name_input,
                self.gender,
                self.birth_date,
                self.email,
                self.phone_verified_at,
                self.phone_verification_method,
                self.rules_accepted_tg,
                self.rules_accepted_tg_at,
                self.rules_accepted_vk,
                self.rules_accepted_vk_at,
                self.rules_accepted_max,
                self.rules_accepted_max_at,
                self.notifications_allowed_tg,
                self.notifications_allowed_tg_at,
                self.notifications_allowed_vk,
                self.notifications_allowed_vk_at,
                self.notifications_allowed_max,
                self.notifications_allowed_max_at,
                self.platform,
                self.platform_rules_accepted,
                self.platform_rules_accepted_at,
                self.platform_notifications_allowed,
                self.platform_notifications_allowed_at,
                self.platform_is_registered,
                self.platform_registered_at,
            )
        )
