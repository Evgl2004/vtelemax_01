"""Репозиторий сессий подтверждения телефона VK Mini App."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from vtelemax.infrastructure.postgres.schema import VkPhoneVerificationSessionRow


@dataclass(frozen=True, slots=True)
class VkPhoneVerificationSession:
    """Read-модель сессии VK Mini App."""

    session_id: UUID
    vk_user_id: int
    status: str
    phone_e164: str | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    verified_at: datetime | None
    completed_at: datetime | None


class SQLAlchemyVkPhoneVerificationSessionRepository:
    """CRUD-операции сессий подтверждения телефона VK Mini App."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def expire_outdated_created_sessions(self, *, now_utc: datetime) -> int:
        """Переводит просроченные `created`-сессии в `expired`."""

        statement = (
            select(VkPhoneVerificationSessionRow)
            .where(
                VkPhoneVerificationSessionRow.status == "created",
                VkPhoneVerificationSessionRow.expires_at <= now_utc,
            )
            .with_for_update(skip_locked=True)
        )
        rows = self._session.execute(statement).scalars().all()
        for row in rows:
            row.status = "expired"
            row.updated_at = now_utc
            if row.completed_at is None:
                row.completed_at = now_utc
        return len(rows)

    def get_latest_session_for_vk_user(self, *, vk_user_id: int) -> VkPhoneVerificationSession | None:
        """Возвращает последнюю сессию пользователя VK по времени создания."""

        statement = (
            select(VkPhoneVerificationSessionRow)
            .where(VkPhoneVerificationSessionRow.vk_user_id == vk_user_id)
            .order_by(VkPhoneVerificationSessionRow.created_at.desc())
            .limit(1)
        )
        row = self._session.execute(statement).scalars().first()
        if row is None:
            return None
        return _to_session_model(row)

    def get_session_by_id_for_update(self, *, session_id: UUID) -> VkPhoneVerificationSessionRow | None:
        """Возвращает сессию по id с блокировкой FOR UPDATE."""

        statement = (
            select(VkPhoneVerificationSessionRow)
            .where(VkPhoneVerificationSessionRow.session_id == session_id)
            .with_for_update(skip_locked=True)
        )
        return self._session.execute(statement).scalars().first()

    def create_or_get_active_session(
        self,
        *,
        vk_user_id: int,
        launch_uid: int | None,
        launch_ts: int | None,
        now_utc: datetime,
        ttl_seconds: int,
        payload_json: dict[str, object] | None = None,
    ) -> VkPhoneVerificationSession:
        """Возвращает активную `created`-сессию или создает новую."""

        statement = (
            select(VkPhoneVerificationSessionRow)
            .where(
                VkPhoneVerificationSessionRow.vk_user_id == vk_user_id,
                VkPhoneVerificationSessionRow.status == "created",
                VkPhoneVerificationSessionRow.expires_at > now_utc,
            )
            .order_by(VkPhoneVerificationSessionRow.created_at.desc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        existing = self._session.execute(statement).scalars().first()
        if existing is not None:
            existing.launch_uid = launch_uid
            existing.launch_ts = launch_ts
            existing.raw_payload = payload_json
            existing.updated_at = now_utc
            return _to_session_model(existing)

        created = VkPhoneVerificationSessionRow(
            session_id=uuid4(),
            vk_user_id=vk_user_id,
            status="created",
            launch_uid=launch_uid,
            launch_ts=launch_ts,
            raw_payload=payload_json,
            expires_at=now_utc + timedelta(seconds=int(ttl_seconds)),
            updated_at=now_utc,
        )
        self._session.add(created)
        self._session.flush()
        return _to_session_model(created)

    def mark_verified(
        self,
        *,
        row: VkPhoneVerificationSessionRow,
        phone_e164: str,
        now_utc: datetime,
        payload_json: dict[str, object] | None = None,
    ) -> VkPhoneVerificationSession:
        """Переводит сессию в `verified` и сохраняет подтвержденный номер."""

        row.status = "verified"
        row.phone_e164 = phone_e164
        row.failure_reason = None
        row.raw_payload = payload_json
        row.verified_at = now_utc
        row.completed_at = now_utc
        row.updated_at = now_utc
        self._session.flush()
        return _to_session_model(row)

    def mark_failed(
        self,
        *,
        row: VkPhoneVerificationSessionRow,
        reason: str,
        now_utc: datetime,
        payload_json: dict[str, object] | None = None,
    ) -> VkPhoneVerificationSession:
        """Переводит сессию в `failed` с текстом причины."""

        row.status = "failed"
        row.failure_reason = reason
        row.raw_payload = payload_json
        row.completed_at = now_utc
        row.updated_at = now_utc
        self._session.flush()
        return _to_session_model(row)

    def mark_expired_if_needed(
        self,
        *,
        row: VkPhoneVerificationSessionRow,
        now_utc: datetime,
    ) -> VkPhoneVerificationSession:
        """Переводит сессию в `expired`, если она просрочена."""

        if row.status == "created" and row.expires_at <= now_utc:
            row.status = "expired"
            row.completed_at = now_utc
            row.updated_at = now_utc
            self._session.flush()
        return _to_session_model(row)


def _to_session_model(row: VkPhoneVerificationSessionRow) -> VkPhoneVerificationSession:
    """Преобразует ORM-строку в dataclass-модель."""

    return VkPhoneVerificationSession(
        session_id=row.session_id,
        vk_user_id=row.vk_user_id,
        status=row.status,
        phone_e164=row.phone_e164,
        failure_reason=row.failure_reason,
        created_at=_ensure_aware_utc(row.created_at),
        updated_at=_ensure_aware_utc(row.updated_at),
        expires_at=_ensure_aware_utc(row.expires_at),
        verified_at=_ensure_aware_utc(row.verified_at),
        completed_at=_ensure_aware_utc(row.completed_at),
    )


def _ensure_aware_utc(value: datetime | None) -> datetime | None:
    """Нормализует datetime к aware UTC-формату."""

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

