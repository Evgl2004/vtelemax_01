"""PostgreSQL-репозиторий выборок получателей для SAGUR integration API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, case, cast, false, func, or_, select, tuple_
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select
from sqlalchemy.types import String

from .schema import PersonPlatformStateRow, PersonRow, PhoneRow, PlatformAccountRow


@dataclass(frozen=True, slots=True)
class SagurRecipientProjection:
    """Плоская проекция строки получателя для snapshot/delta выдачи."""

    person_id: str
    phone_e164: str
    platform: str
    external_id: str | None
    rules_accepted: bool
    notifications_allowed: bool
    is_registered: bool
    registered_at: datetime | None
    state_updated_at: datetime | None
    account_created_at: datetime
    effective_updated_at: datetime
    profile_first_name: str | None
    profile_last_name: str | None
    profile_gender: str | None
    profile_email: str | None
    profile_birthdate: date | None


class SQLAlchemySagurRecipientsRepository:
    """Read-only репозиторий выборок получателей для интеграции с SAGUR."""

    def __init__(self, session: Session, *, include_vk_pending_verification: bool = False) -> None:
        self._session = session
        self._include_vk_pending_verification = include_vk_pending_verification

    def fetch_snapshot_page(
        self,
        *,
        page_size: int,
        cursor_account_created_at: datetime | None = None,
        cursor_person_id: str | None = None,
        cursor_platform: str | None = None,
    ) -> tuple[SagurRecipientProjection, ...]:
        """Возвращает страницу snapshot-выдачи в стабильном детерминированном порядке."""

        statement = _build_snapshot_statement(
            page_size=page_size,
            cursor_account_created_at=cursor_account_created_at,
            cursor_person_id=cursor_person_id,
            cursor_platform=cursor_platform,
            include_vk_pending_verification=self._include_vk_pending_verification,
        )
        rows = self._session.execute(statement).mappings().all()
        return tuple(_to_projection(row) for row in rows)

    def fetch_delta_page(
        self,
        *,
        since: datetime,
        page_size: int,
        cursor_effective_updated_at: datetime | None = None,
        cursor_person_id: str | None = None,
        cursor_platform: str | None = None,
    ) -> tuple[SagurRecipientProjection, ...]:
        """Возвращает страницу delta-выдачи в стабильном детерминированном порядке."""

        statement = _build_delta_statement(
            since=since,
            page_size=page_size,
            cursor_effective_updated_at=cursor_effective_updated_at,
            cursor_person_id=cursor_person_id,
            cursor_platform=cursor_platform,
            include_vk_pending_verification=self._include_vk_pending_verification,
        )
        rows = self._session.execute(statement).mappings().all()
        return tuple(_to_projection(row) for row in rows)


def _to_projection(row: Any) -> SagurRecipientProjection:
    external_id_raw = row["external_id"]
    return SagurRecipientProjection(
        person_id=str(row["person_id"]),
        phone_e164=str(row["phone_e164"]),
        platform=str(row["platform"]),
        external_id=None if external_id_raw is None else str(external_id_raw),
        rules_accepted=bool(row["rules_accepted"]),
        notifications_allowed=bool(row["notifications_allowed"]),
        is_registered=bool(row["is_registered"]),
        registered_at=row["registered_at"],
        state_updated_at=row["state_updated_at"],
        account_created_at=row["account_created_at"],
        effective_updated_at=row["effective_updated_at"],
        profile_first_name=row["profile_first_name"],
        profile_last_name=row["profile_last_name"],
        profile_gender=row["profile_gender"],
        profile_email=row["profile_email"],
        profile_birthdate=row["profile_birthdate"],
    )


def _build_lifecycle_filter(*, include_vk_pending_verification: bool) -> Any:
    vk_statuses: tuple[str, ...] = (
        ("active", "pending_verification")
        if include_vk_pending_verification
        else ("active",)
    )
    return or_(
        and_(
            PlatformAccountRow.platform.in_(("telegram", "max")),
            PlatformAccountRow.lifecycle_status == "active",
        ),
        and_(
            PlatformAccountRow.platform == "vk",
            PlatformAccountRow.lifecycle_status.in_(vk_statuses),
        ),
    )


def _build_ranked_accounts_cte(*, include_vk_pending_verification: bool) -> Any:
    lifecycle_priority = case(
        (PlatformAccountRow.lifecycle_status == "active", 0),
        (PlatformAccountRow.lifecycle_status == "pending_verification", 1),
        else_=2,
    )
    return (
        select(
            PlatformAccountRow.person_id.label("person_id"),
            PlatformAccountRow.platform.label("platform"),
            PlatformAccountRow.external_id.label("external_id"),
            PlatformAccountRow.created_at.label("account_created_at"),
            func.row_number()
            .over(
                partition_by=(PlatformAccountRow.person_id, PlatformAccountRow.platform),
                order_by=(
                    lifecycle_priority.asc(),
                    PlatformAccountRow.created_at.desc(),
                    PlatformAccountRow.account_id.desc(),
                ),
            )
            .label("row_rank"),
        )
        .where(
            _build_lifecycle_filter(
                include_vk_pending_verification=include_vk_pending_verification
            )
        )
        .cte("ranked_accounts")
    )


def _build_resolved_accounts_cte(*, include_vk_pending_verification: bool) -> Any:
    ranked_accounts = _build_ranked_accounts_cte(
        include_vk_pending_verification=include_vk_pending_verification
    )
    return (
        select(
            ranked_accounts.c.person_id,
            ranked_accounts.c.platform,
            ranked_accounts.c.external_id,
            ranked_accounts.c.account_created_at,
        )
        .where(ranked_accounts.c.row_rank == 1)
        .cte("resolved_accounts")
    )


def _build_enriched_cte(*, include_vk_pending_verification: bool) -> Any:
    resolved_accounts = _build_resolved_accounts_cte(
        include_vk_pending_verification=include_vk_pending_verification
    )
    return (
        select(
            cast(resolved_accounts.c.person_id, String).label("person_id"),
            PhoneRow.phone_e164.label("phone_e164"),
            resolved_accounts.c.platform.label("platform"),
            resolved_accounts.c.external_id.label("external_id"),
            func.coalesce(PersonPlatformStateRow.rules_accepted, false()).label("rules_accepted"),
            func.coalesce(PersonPlatformStateRow.notifications_allowed, false()).label(
                "notifications_allowed"
            ),
            func.coalesce(PersonPlatformStateRow.is_registered, false()).label("is_registered"),
            PersonPlatformStateRow.registered_at.label("registered_at"),
            PersonPlatformStateRow.updated_at.label("state_updated_at"),
            resolved_accounts.c.account_created_at.label("account_created_at"),
            PersonRow.first_name_input.label("profile_first_name"),
            PersonRow.last_name_input.label("profile_last_name"),
            PersonRow.gender.label("profile_gender"),
            PersonRow.email.label("profile_email"),
            PersonRow.birth_date.label("profile_birthdate"),
            PersonRow.updated_at.label("profile_updated_at"),
            func.greatest(
                func.coalesce(PersonPlatformStateRow.updated_at, resolved_accounts.c.account_created_at),
                resolved_accounts.c.account_created_at,
                PersonRow.updated_at,
            ).label("effective_updated_at"),
        )
        .select_from(
            resolved_accounts.join(PersonRow, PersonRow.person_id == resolved_accounts.c.person_id)
            .join(PhoneRow, PhoneRow.person_id == resolved_accounts.c.person_id)
            .outerjoin(
                PersonPlatformStateRow,
                and_(
                    PersonPlatformStateRow.person_id == resolved_accounts.c.person_id,
                    PersonPlatformStateRow.platform == resolved_accounts.c.platform,
                ),
            )
        )
        .cte("enriched")
    )


def _select_projection_from_enriched(enriched: Any) -> Select[Any]:
    return select(
        enriched.c.person_id,
        enriched.c.phone_e164,
        enriched.c.platform,
        enriched.c.external_id,
        enriched.c.rules_accepted,
        enriched.c.notifications_allowed,
        enriched.c.is_registered,
        enriched.c.registered_at,
        enriched.c.state_updated_at,
        enriched.c.account_created_at,
        enriched.c.effective_updated_at,
        enriched.c.profile_first_name,
        enriched.c.profile_last_name,
        enriched.c.profile_gender,
        enriched.c.profile_email,
        enriched.c.profile_birthdate,
    )


def _build_snapshot_statement(
    *,
    page_size: int,
    cursor_account_created_at: datetime | None = None,
    cursor_person_id: str | None = None,
    cursor_platform: str | None = None,
    include_vk_pending_verification: bool = False,
) -> Select[Any]:
    enriched = _build_enriched_cte(
        include_vk_pending_verification=include_vk_pending_verification
    )
    statement = _select_projection_from_enriched(enriched)

    if (
        cursor_account_created_at is not None
        and cursor_person_id is not None
        and cursor_platform is not None
    ):
        statement = statement.where(
            tuple_(enriched.c.account_created_at, enriched.c.person_id, enriched.c.platform)
            > tuple_(cursor_account_created_at, cursor_person_id, cursor_platform)
        )

    return statement.order_by(
        enriched.c.account_created_at.asc(),
        enriched.c.person_id.asc(),
        enriched.c.platform.asc(),
    ).limit(page_size)


def _build_delta_statement(
    *,
    since: datetime,
    page_size: int,
    cursor_effective_updated_at: datetime | None = None,
    cursor_person_id: str | None = None,
    cursor_platform: str | None = None,
    include_vk_pending_verification: bool = False,
) -> Select[Any]:
    enriched = _build_enriched_cte(
        include_vk_pending_verification=include_vk_pending_verification
    )
    statement = _select_projection_from_enriched(enriched).where(enriched.c.effective_updated_at > since)

    if (
        cursor_effective_updated_at is not None
        and cursor_person_id is not None
        and cursor_platform is not None
    ):
        statement = statement.where(
            tuple_(enriched.c.effective_updated_at, enriched.c.person_id, enriched.c.platform)
            > tuple_(cursor_effective_updated_at, cursor_person_id, cursor_platform)
        )

    return statement.order_by(
        enriched.c.effective_updated_at.asc(),
        enriched.c.person_id.asc(),
        enriched.c.platform.asc(),
    ).limit(page_size)
