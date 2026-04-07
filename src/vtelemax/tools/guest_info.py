"""Инструменты для получения детальной информации о госте по телефону.

Модуль предоставляет функцию, которая выполняет SQL-запрос, аналогичный
ручному запросу через docker compose exec, и возвращает структурированные данные
по всем трём платформам (telegram, vk, max) даже при отсутствии записей.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select, union_all, literal_column
from sqlalchemy.orm import Session

from vtelemax.infrastructure.postgres import (
    PersonRow,
    PhoneRow,
    PersonPlatformStateRow,
    PlatformAccountRow,
)

PlatformName = Literal["telegram", "vk", "max"]
SUPPORTED_PLATFORMS: tuple[PlatformName, ...] = ("telegram", "vk", "max")


@dataclass(frozen=True, slots=True)
class GuestPlatformInfo:
    """Информация о состоянии гостя на конкретной платформе."""

    platform: PlatformName
    external_id: str | None
    rules_accepted: bool | None
    rules_accepted_at: datetime | None
    notifications_allowed: bool | None
    notifications_allowed_at: datetime | None
    is_registered: bool | None
    registered_at: datetime | None


@dataclass(frozen=True, slots=True)
class GuestInfo:
    """Детальная информация о госте (person) по телефону."""

    person_id: UUID
    phone_e164: str
    is_legacy: bool
    profile_is_registered: bool
    first_name_input: str | None
    phone_verification_method: str | None
    platforms: tuple[GuestPlatformInfo, ...]


def get_guest_info_by_phone(session: Session, phone_e164: str) -> GuestInfo | None:
    """Возвращает детальную информацию о госте по каноническому телефону.

    Args:
        session: Активная SQLAlchemy-сессия.
        phone_e164: Телефон в формате `+7XXXXXXXXXX`.

    Returns:
        GuestInfo с данными по всем трём платформам или None, если телефон не найден.
    """
    # 1. Находим person и phone
    person_stmt = (
        select(
            PersonRow.person_id,
            PersonRow.is_legacy,
            PersonRow.is_registered.label("profile_is_registered"),
            PersonRow.first_name_input,
            PersonRow.phone_verification_method,
            PhoneRow.phone_e164,
        )
        .join(PhoneRow, PhoneRow.person_id == PersonRow.person_id)
        .where(PhoneRow.phone_e164 == phone_e164)
    )
    person_row = session.execute(person_stmt).first()
    if person_row is None:
        return None

    person_id = person_row.person_id
    phone_e164 = person_row.phone_e164
    is_legacy = person_row.is_legacy
    profile_is_registered = person_row.profile_is_registered
    first_name_input = person_row.first_name_input
    phone_verification_method = person_row.phone_verification_method

    # 2. Для каждой платформы собираем данные
    platform_infos = []
    for platform in SUPPORTED_PLATFORMS:
        # Запрос для состояния платформы
        state_stmt = (
            select(
                PersonPlatformStateRow.rules_accepted,
                PersonPlatformStateRow.rules_accepted_at,
                PersonPlatformStateRow.notifications_allowed,
                PersonPlatformStateRow.notifications_allowed_at,
                PersonPlatformStateRow.is_registered,
                PersonPlatformStateRow.registered_at,
            )
            .where(
                PersonPlatformStateRow.person_id == person_id,
                PersonPlatformStateRow.platform == platform,
            )
            .limit(1)
        )
        state_row = session.execute(state_stmt).first()

        # Запрос для аккаунта платформы
        account_stmt = (
            select(PlatformAccountRow.external_id)
            .where(
                PlatformAccountRow.person_id == person_id,
                PlatformAccountRow.platform == platform,
            )
            .limit(1)
        )
        account_row = session.execute(account_stmt).first()
        external_id = account_row.external_id if account_row else None

        platform_infos.append(
            GuestPlatformInfo(
                platform=platform,
                external_id=external_id,
                rules_accepted=state_row.rules_accepted if state_row else None,
                rules_accepted_at=state_row.rules_accepted_at if state_row else None,
                notifications_allowed=state_row.notifications_allowed if state_row else None,
                notifications_allowed_at=state_row.notifications_allowed_at if state_row else None,
                is_registered=state_row.is_registered if state_row else None,
                registered_at=state_row.registered_at if state_row else None,
            )
        )

    # Сортировка уже по порядку SUPPORTED_PLATFORMS
    return GuestInfo(
        person_id=person_id,
        phone_e164=phone_e164,
        is_legacy=is_legacy,
        profile_is_registered=profile_is_registered,
        first_name_input=first_name_input,
        phone_verification_method=phone_verification_method,
        platforms=tuple(platform_infos),
    )