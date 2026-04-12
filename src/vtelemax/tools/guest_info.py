"""Инструменты получения детальной информации о госте по телефону.

Модуль предоставляет диагностические функции для операторской проверки:

1. Поиск гостя по каноническому телефону (`+7XXXXXXXXXX`).
2. Получение единого снимка по платформам `telegram`, `vk`, `max`.
3. Возврат данных в структурированном виде для CLI и автоматизированных проверок.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, case, literal, select, true, union_all
from sqlalchemy.orm import Session

from vtelemax.infrastructure.postgres import (
    PersonPlatformStateRow,
    PersonRow,
    PhoneRow,
    PlatformAccountRow,
)

PlatformName = Literal["telegram", "vk", "max"]
SUPPORTED_PLATFORMS: tuple[PlatformName, ...] = ("telegram", "vk", "max")


@dataclass(frozen=True, slots=True)
class GuestPlatformInfo:
    """Состояние регистрации гостя на конкретной платформе."""

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
    """Детальная информация о госте по номеру телефона."""

    person_id: UUID
    phone_e164: str
    is_legacy: bool
    profile_is_registered: bool
    first_name_input: str | None
    phone_verification_method: str | None
    platforms: tuple[GuestPlatformInfo, ...]


def _build_platforms_subquery() -> Any:
    """Возвращает подзапрос со списком поддерживаемых платформ."""

    telegram_q = select(literal("telegram").label("platform"))
    vk_q = select(literal("vk").label("platform"))
    max_q = select(literal("max").label("platform"))
    return union_all(telegram_q, vk_q, max_q).subquery("platforms")


def _build_guest_info_query(phone_e164: str):
    """Строит SQLAlchemy-запрос для выборки данных гостя по всем платформам."""

    platforms_sq = _build_platforms_subquery()
    platform_col = platforms_sq.c.platform
    platform_order = case(
        (platform_col == "telegram", 1),
        (platform_col == "vk", 2),
        (platform_col == "max", 3),
        else_=99,
    )

    return (
        select(
            PersonRow.person_id,
            PhoneRow.phone_e164,
            PersonRow.is_legacy,
            PersonRow.is_registered.label("profile_is_registered"),
            PersonRow.first_name_input,
            PersonRow.phone_verification_method,
            platform_col.label("platform"),
            PlatformAccountRow.external_id,
            PersonPlatformStateRow.rules_accepted,
            PersonPlatformStateRow.rules_accepted_at,
            PersonPlatformStateRow.notifications_allowed,
            PersonPlatformStateRow.notifications_allowed_at,
            PersonPlatformStateRow.is_registered.label("platform_is_registered"),
            PersonPlatformStateRow.registered_at,
        )
        .select_from(PersonRow)
        .join(PhoneRow, PhoneRow.person_id == PersonRow.person_id)
        .join(platforms_sq, true())
        .outerjoin(
            PersonPlatformStateRow,
            and_(
                PersonPlatformStateRow.person_id == PersonRow.person_id,
                PersonPlatformStateRow.platform == platform_col,
            ),
        )
        .outerjoin(
            PlatformAccountRow,
            and_(
                PlatformAccountRow.person_id == PersonRow.person_id,
                PlatformAccountRow.platform == platform_col,
            ),
        )
        .where(PhoneRow.phone_e164 == phone_e164)
        .order_by(platform_order)
    )


def get_guest_info_rows_by_phone(session: Session, phone_e164: str) -> tuple[dict[str, Any], ...]:
    """Возвращает сырые строки гостя по платформам в виде mapping-словарей."""

    rows = session.execute(_build_guest_info_query(phone_e164)).mappings().all()
    return tuple(dict(row) for row in rows)


def get_guest_info_by_phone(session: Session, phone_e164: str) -> GuestInfo | None:
    """Возвращает структурированный снимок гостя по телефону.

    Args:
        session: Активная SQLAlchemy-сессия.
        phone_e164: Канонический номер телефона (`+7XXXXXXXXXX`).
    """

    rows = get_guest_info_rows_by_phone(session, phone_e164)
    if not rows:
        return None

    first = rows[0]
    platforms: list[GuestPlatformInfo] = []

    for row in rows:
        platform = str(row["platform"])
        if platform not in SUPPORTED_PLATFORMS:
            # Защита от некорректной платформы в БД/запросе.
            continue
        platforms.append(
            GuestPlatformInfo(
                platform=platform,  # type: ignore[arg-type]
                external_id=row["external_id"],
                rules_accepted=row["rules_accepted"],
                rules_accepted_at=row["rules_accepted_at"],
                notifications_allowed=row["notifications_allowed"],
                notifications_allowed_at=row["notifications_allowed_at"],
                is_registered=row["platform_is_registered"],
                registered_at=row["registered_at"],
            )
        )

    return GuestInfo(
        person_id=first["person_id"],
        phone_e164=first["phone_e164"],
        is_legacy=bool(first["is_legacy"]),
        profile_is_registered=bool(first["profile_is_registered"]),
        first_name_input=first["first_name_input"],
        phone_verification_method=first["phone_verification_method"],
        platforms=tuple(platforms),
    )

