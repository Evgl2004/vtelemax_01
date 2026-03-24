"""Доменные модели strict identity.

В модуле хранятся основные сущности ядра, независимые от инфраструктуры:

1. `Person` — человек в единой системе.
2. `PlatformAccount` — привязанный аккаунт конкретной платформы.
3. `PlatformName` — допустимые платформы на текущем этапе.
"""

from __future__ import annotations

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
    """

    person_id: UUID
    phone_e164: str
    accounts: set[PlatformAccount] = field(default_factory=set)
