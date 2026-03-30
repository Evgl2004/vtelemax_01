"""Инструменты точечной очистки тестового пользователя.

Модуль нужен для ручного QA-цикла, когда необходимо:

1. удалить пользователя из PostgreSQL по телефону;
2. удалить связанные платформенные аккаунты и support-историю (через CASCADE);
3. при необходимости очистить Redis-ключи, связанные с этим пользователем.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from vtelemax.infrastructure.postgres import (
    PersonRow,
    PhoneRow,
    PlatformAccountRow,
    SupportMessageRow,
    SupportTicketRow,
)

if TYPE_CHECKING:
    from redis import Redis


@dataclass(frozen=True, slots=True)
class PersonResetAccount:
    """Краткая модель привязанного платформенного аккаунта пользователя."""

    platform: str
    external_id: str


@dataclass(frozen=True, slots=True)
class PersonResetSnapshot:
    """Снимок данных пользователя перед удалением."""

    person_id: UUID
    phone_e164: str
    accounts: tuple[PersonResetAccount, ...]
    tickets_count: int
    messages_count: int


def get_person_snapshot_by_phone(session: Session, phone_e164: str) -> PersonResetSnapshot | None:
    """Возвращает снимок пользователя по каноническому телефону.

    Args:
        session: Активная SQLAlchemy-сессия.
        phone_e164: Телефон в формате `+7XXXXXXXXXX`.
    """

    person_id = session.execute(
        select(PhoneRow.person_id).where(PhoneRow.phone_e164 == phone_e164)
    ).scalar_one_or_none()
    if person_id is None:
        return None

    account_rows = session.execute(
        select(PlatformAccountRow.platform, PlatformAccountRow.external_id)
        .where(PlatformAccountRow.person_id == person_id)
        .order_by(PlatformAccountRow.platform, PlatformAccountRow.external_id)
    ).all()
    accounts = tuple(
        PersonResetAccount(platform=row.platform, external_id=row.external_id) for row in account_rows
    )

    tickets_count = (
        session.execute(
            select(func.count()).select_from(SupportTicketRow).where(SupportTicketRow.person_id == person_id)
        ).scalar_one()
        or 0
    )

    messages_count = (
        session.execute(
            select(func.count())
            .select_from(SupportMessageRow)
            .join(SupportTicketRow, SupportTicketRow.ticket_id == SupportMessageRow.ticket_id)
            .where(SupportTicketRow.person_id == person_id)
        ).scalar_one()
        or 0
    )

    return PersonResetSnapshot(
        person_id=person_id,
        phone_e164=phone_e164,
        accounts=accounts,
        tickets_count=int(tickets_count),
        messages_count=int(messages_count),
    )


def delete_person_by_id(session: Session, person_id: UUID) -> int:
    """Удаляет пользователя из `persons` по `person_id`.

    В схеме проекта включены FK `ON DELETE CASCADE`, поэтому при удалении `persons`
    автоматически удаляются:

    1. `phones`;
    2. `platform_accounts`;
    3. `support_tickets`;
    4. `support_messages` (через каскад от тикетов).
    """

    result = session.execute(delete(PersonRow).where(PersonRow.person_id == person_id))
    return int(result.rowcount or 0)


def build_default_redis_patterns(
    phone_e164: str,
    accounts: tuple[PersonResetAccount, ...],
) -> list[str]:
    """Строит безопасные шаблоны Redis-ключей для точечной очистки.

    Принцип: используем только ключи с префиксом `vtelemax` и идентификаторами
    конкретного пользователя (телефон и external_id платформ).
    """

    digits = "".join(ch for ch in phone_e164 if ch.isdigit())
    patterns: set[str] = {
        f"vtelemax:*{phone_e164}*",
    }
    if digits:
        patterns.add(f"vtelemax:*{digits}*")

    for account in accounts:
        patterns.add(f"vtelemax:*:{account.platform}:{account.external_id}:*")
        patterns.add(f"vtelemax:*{account.external_id}*")

    return sorted(patterns)


def collect_matching_redis_keys(
    redis_client: Redis,
    patterns: list[str],
    *,
    scan_count: int = 1000,
) -> list[str]:
    """Собирает все Redis-ключи, совпавшие с переданными шаблонами."""

    matched: set[str] = set()
    for pattern in patterns:
        for key in redis_client.scan_iter(match=pattern, count=scan_count):
            if isinstance(key, bytes):
                matched.add(key.decode("utf-8", errors="replace"))
            else:
                matched.add(str(key))
    return sorted(matched)


def delete_redis_keys(redis_client: Redis, keys: list[str]) -> int:
    """Удаляет список Redis-ключей и возвращает количество реально удаленных."""

    if not keys:
        return 0
    return int(redis_client.delete(*keys))
