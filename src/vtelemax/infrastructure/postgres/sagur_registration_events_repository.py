"""PostgreSQL-репозиторий исходящих событий регистрации гостей для SAGUR."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from vtelemax.core.sagur_registration_models import (
    SAGUR_GUEST_REGISTERED_EVENT_TYPE,
    SagurRegistrationContext,
    SagurRegistrationDeliveryStatus,
    SagurRegistrationEventTask,
    SagurRegistrationIikoStatus,
    SagurRegistrationRecoveryTask,
)

from .schema import (
    PersonPlatformStateRow,
    PersonRow,
    PhoneRow,
    PlatformAccountRow,
    SagurGuestRegistrationEventRow,
)

_TERMINAL_DELIVERY_STATUSES = (
    SagurRegistrationDeliveryStatus.SENT.value,
    SagurRegistrationDeliveryStatus.CONFLICT.value,
    SagurRegistrationDeliveryStatus.NOT_REQUIRED.value,
    SagurRegistrationDeliveryStatus.MANUAL_REVIEW.value,
    SagurRegistrationDeliveryStatus.FAILED_TERMINAL.value,
)


@dataclass(frozen=True, slots=True)
class _SagurRegistrationPayloadProjection:
    person_id: UUID
    phone_e164: str
    platform: str
    external_id: str
    customer_id: str
    rules_accepted: bool
    notifications_allowed: bool
    is_registered: bool
    registered_at: datetime
    state_updated_at: datetime
    account_created_at: datetime
    effective_updated_at: datetime
    profile_first_name: str | None
    profile_last_name: str | None
    profile_gender: str | None
    profile_email: str | None
    profile_birthdate: date | None


class SQLAlchemySagurRegistrationEventsRepository:
    """Репозиторий единого регистра welcome-регистраций SAGUR."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def ensure_iiko_lookup_started(
        self,
        context: SagurRegistrationContext,
        *,
        now_utc: datetime | None = None,
    ) -> UUID:
        """Создает или обновляет активную запись регистра до внешнего вызова iikoCard."""

        now = _utc_now(now_utc)
        row = self._find_active_context_row(context)
        if row is None:
            record_id = uuid4()
            self._session.add(
                SagurGuestRegistrationEventRow(
                    record_id=record_id,
                    person_id=context.person_id,
                    platform=context.platform,
                    external_id=context.external_id,
                    phone_e164=context.phone_e164,
                    registration_origin=context.registration_origin,
                    iiko_status=SagurRegistrationIikoStatus.LOOKUP_STARTED.value,
                    sagur_status=SagurRegistrationDeliveryStatus.NOT_READY.value,
                    created_new_customer=False,
                    existing_customer_found=False,
                    lookup_started_at=now,
                    next_attempt_at=now,
                )
            )
            return record_id

        row.phone_e164 = context.phone_e164
        row.lookup_started_at = now
        row.iiko_status = SagurRegistrationIikoStatus.LOOKUP_STARTED.value
        row.locked_at = None
        row.updated_at = now
        return row.record_id

    def mark_lookup_failed(
        self,
        record_id: UUID,
        *,
        error_code: str,
        error_text: str,
        next_attempt_at: datetime,
        now_utc: datetime | None = None,
    ) -> None:
        """Фиксирует ошибку поиска iikoCard до попытки создания гостя."""

        now = _utc_now(now_utc)
        row = self._get_row(record_id)
        if row is None:
            return
        row.iiko_status = SagurRegistrationIikoStatus.RESULT_UNKNOWN.value
        row.sagur_status = SagurRegistrationDeliveryStatus.NOT_READY.value
        row.lookup_finished_at = now
        row.last_error_code = error_code
        row.last_error_text = _trim_error_text(error_text)
        row.recovery_reason = "lookup_failed"
        row.next_attempt_at = next_attempt_at
        row.locked_at = None
        row.updated_at = now

    def mark_create_started(
        self,
        record_id: UUID,
        *,
        now_utc: datetime | None = None,
    ) -> None:
        """Фиксирует начало создания гостя iikoCard."""

        now = _utc_now(now_utc)
        row = self._get_row(record_id)
        if row is None:
            return
        row.iiko_status = SagurRegistrationIikoStatus.CREATE_STARTED.value
        row.create_started_at = now
        row.last_error_code = None
        row.last_error_text = None
        row.updated_at = now

    def mark_created_customer(
        self,
        record_id: UUID,
        *,
        customer_id: str,
        now_utc: datetime | None = None,
    ) -> None:
        """Фиксирует успешное создание нового гостя iikoCard."""

        now = _utc_now(now_utc)
        row = self._get_row(record_id)
        if row is None:
            return
        row.customer_id = customer_id
        row.created_new_customer = True
        row.existing_customer_found = False
        row.iiko_status = SagurRegistrationIikoStatus.CREATED.value
        row.lookup_finished_at = row.lookup_finished_at or now
        row.iiko_response_received_at = now
        row.last_error_code = None
        row.last_error_text = None
        row.recovery_reason = None
        row.locked_at = None
        row.updated_at = now

    def mark_existing_customer(
        self,
        record_id: UUID,
        *,
        customer_id: str,
        now_utc: datetime | None = None,
    ) -> None:
        """Фиксирует найденного существующего гостя iikoCard."""

        now = _utc_now(now_utc)
        row = self._get_row(record_id)
        if row is None:
            return
        row.customer_id = customer_id
        row.existing_customer_found = True
        row.iiko_status = SagurRegistrationIikoStatus.EXISTING.value
        row.lookup_finished_at = now
        row.iiko_response_received_at = now
        row.last_error_code = None
        row.last_error_text = None
        row.recovery_reason = None
        row.locked_at = None
        row.updated_at = now

    def mark_create_result_unknown(
        self,
        record_id: UUID,
        *,
        error_code: str,
        error_text: str,
        next_attempt_at: datetime,
        now_utc: datetime | None = None,
    ) -> None:
        """Фиксирует неизвестный результат создания гостя iikoCard."""

        now = _utc_now(now_utc)
        row = self._get_row(record_id)
        if row is None:
            return
        row.iiko_status = SagurRegistrationIikoStatus.RESULT_UNKNOWN.value
        row.sagur_status = SagurRegistrationDeliveryStatus.NOT_READY.value
        row.last_error_code = error_code
        row.last_error_text = _trim_error_text(error_text)
        row.recovery_reason = "create_result_unknown"
        row.next_attempt_at = next_attempt_at
        row.locked_at = None
        row.updated_at = now

    def mark_create_failed_terminal(
        self,
        record_id: UUID,
        *,
        error_code: str,
        error_text: str,
        now_utc: datetime | None = None,
    ) -> None:
        """Фиксирует финальную ошибку создания гостя iikoCard."""

        now = _utc_now(now_utc)
        row = self._get_row(record_id)
        if row is None:
            return
        row.iiko_status = SagurRegistrationIikoStatus.FAILED_TERMINAL.value
        row.sagur_status = SagurRegistrationDeliveryStatus.FAILED_TERMINAL.value
        row.last_error_code = error_code
        row.last_error_text = _trim_error_text(error_text)
        row.locked_at = None
        row.updated_at = now

    def create_pending_event_if_required(
        self,
        record_id: UUID,
        *,
        now_utc: datetime | None = None,
    ) -> bool:
        """Собирает и сохраняет событие SAGUR, если правило регистрации требует отправки."""

        now = _utc_now(now_utc)
        row = self._get_row(record_id)
        if row is None:
            return False
        if not row.customer_id:
            return False
        if row.payload_body is not None and row.event_id is not None and row.request_id is not None:
            if row.sagur_status == SagurRegistrationDeliveryStatus.NOT_READY.value:
                row.sagur_status = SagurRegistrationDeliveryStatus.PENDING.value
                row.next_attempt_at = now
                row.updated_at = now
            return True
        if not _should_create_welcome_event(row):
            row.sagur_status = SagurRegistrationDeliveryStatus.NOT_REQUIRED.value
            row.iiko_status = (
                row.iiko_status
                if row.iiko_status != SagurRegistrationIikoStatus.LOOKUP_STARTED.value
                else SagurRegistrationIikoStatus.NOT_REQUIRED.value
            )
            row.updated_at = now
            return False

        event_id = row.event_id or f"evt-welcome-{row.record_id}"
        request_id = row.request_id or f"req-welcome-{row.record_id}"
        projection = self._load_payload_projection(row)
        if projection is None:
            row.sagur_status = SagurRegistrationDeliveryStatus.FAILED_TERMINAL.value
            row.last_error_code = "payload_projection_missing"
            row.last_error_text = "Не удалось собрать обязательные поля payload SAGUR."
            row.updated_at = now
            return False

        payload = build_sagur_registration_payload(
            projection=projection,
            event_id=event_id,
            request_id=request_id,
        )
        payload_body = dump_sagur_registration_payload(payload)
        row.event_id = event_id
        row.request_id = request_id
        row.event_type = SAGUR_GUEST_REGISTERED_EVENT_TYPE
        row.payload_json = payload
        row.payload_body = payload_body
        row.payload_sha256 = hashlib.sha256(payload_body).hexdigest()
        row.sagur_status = SagurRegistrationDeliveryStatus.PENDING.value
        row.next_attempt_at = now
        row.locked_at = None
        row.updated_at = now
        return True

    def pull_pending_event_tasks(
        self,
        *,
        limit: int,
        now_utc: datetime | None = None,
    ) -> tuple[SagurRegistrationEventTask, ...]:
        """Выбирает pending/retry_scheduled события и переводит их в processing."""

        now = _utc_now(now_utc)
        safe_limit = max(int(limit), 1)
        statement = (
            select(SagurGuestRegistrationEventRow)
            .where(
                SagurGuestRegistrationEventRow.sagur_status.in_(
                    (
                        SagurRegistrationDeliveryStatus.PENDING.value,
                        SagurRegistrationDeliveryStatus.RETRY_SCHEDULED.value,
                    )
                ),
                SagurGuestRegistrationEventRow.next_attempt_at <= now,
                SagurGuestRegistrationEventRow.event_id.is_not(None),
                SagurGuestRegistrationEventRow.request_id.is_not(None),
                SagurGuestRegistrationEventRow.payload_body.is_not(None),
            )
            .order_by(
                SagurGuestRegistrationEventRow.next_attempt_at.asc(),
                SagurGuestRegistrationEventRow.created_at.asc(),
            )
            .limit(safe_limit)
            .with_for_update(skip_locked=True)
        )
        rows = self._session.execute(statement).scalars().all()
        tasks: list[SagurRegistrationEventTask] = []
        for row in rows:
            row.sagur_status = SagurRegistrationDeliveryStatus.PROCESSING.value
            row.attempts += 1
            row.locked_at = now
            row.updated_at = now
            tasks.append(
                SagurRegistrationEventTask(
                    record_id=row.record_id,
                    event_id=str(row.event_id),
                    request_id=str(row.request_id),
                    payload_body=bytes(row.payload_body or b""),
                    attempts=row.attempts,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            )
        return tuple(tasks)

    def mark_event_sent(
        self,
        record_id: UUID,
        *,
        duplicate: bool,
        now_utc: datetime | None = None,
    ) -> None:
        """Фиксирует успешный прием события SAGUR."""

        now = _utc_now(now_utc)
        row = self._get_row(record_id)
        if row is None:
            return
        row.sagur_status = SagurRegistrationDeliveryStatus.SENT.value
        row.sent_at = now
        row.locked_at = None
        row.last_error_code = "duplicate" if duplicate else None
        row.last_error_text = None
        row.updated_at = now

    def mark_event_conflict(
        self,
        record_id: UUID,
        *,
        error_code: str,
        error_text: str,
        now_utc: datetime | None = None,
    ) -> None:
        """Останавливает автоматический повтор при конфликте event_id/payload."""

        now = _utc_now(now_utc)
        row = self._get_row(record_id)
        if row is None:
            return
        row.sagur_status = SagurRegistrationDeliveryStatus.CONFLICT.value
        row.locked_at = None
        row.last_error_code = error_code
        row.last_error_text = _trim_error_text(error_text)
        row.updated_at = now

    def schedule_event_retry(
        self,
        record_id: UUID,
        *,
        error_code: str,
        error_text: str,
        next_attempt_at: datetime,
        max_attempts: int,
        now_utc: datetime | None = None,
    ) -> None:
        """Планирует повтор отправки или переводит событие в terminal failed."""

        now = _utc_now(now_utc)
        row = self._get_row(record_id)
        if row is None:
            return
        if row.attempts >= max_attempts:
            row.sagur_status = SagurRegistrationDeliveryStatus.FAILED_TERMINAL.value
        else:
            row.sagur_status = SagurRegistrationDeliveryStatus.RETRY_SCHEDULED.value
            row.next_attempt_at = next_attempt_at
        row.locked_at = None
        row.last_error_code = error_code
        row.last_error_text = _trim_error_text(error_text)
        row.updated_at = now

    def release_stale_processing(
        self,
        *,
        lock_timeout_seconds: int,
        now_utc: datetime | None = None,
    ) -> int:
        """Возвращает зависшие processing-события в повторную отправку."""

        now = _utc_now(now_utc)
        lock_deadline = now - timedelta(seconds=max(int(lock_timeout_seconds), 1))
        statement = (
            update(SagurGuestRegistrationEventRow)
            .where(
                SagurGuestRegistrationEventRow.sagur_status
                == SagurRegistrationDeliveryStatus.PROCESSING.value,
                SagurGuestRegistrationEventRow.locked_at <= lock_deadline,
            )
            .values(
                sagur_status=SagurRegistrationDeliveryStatus.RETRY_SCHEDULED.value,
                locked_at=None,
                next_attempt_at=now,
                updated_at=now,
            )
        )
        result = self._session.execute(statement)
        return int(result.rowcount or 0)

    def pull_due_recovery_tasks(
        self,
        *,
        limit: int,
        now_utc: datetime | None = None,
    ) -> tuple[SagurRegistrationRecoveryTask, ...]:
        """Выбирает проблемные записи для контрольного поиска iikoCard."""

        now = _utc_now(now_utc)
        safe_limit = max(int(limit), 1)
        statement = (
            select(SagurGuestRegistrationEventRow)
            .where(
                SagurGuestRegistrationEventRow.iiko_status
                == SagurRegistrationIikoStatus.RESULT_UNKNOWN.value,
                SagurGuestRegistrationEventRow.sagur_status
                == SagurRegistrationDeliveryStatus.NOT_READY.value,
                SagurGuestRegistrationEventRow.next_attempt_at <= now,
            )
            .order_by(
                SagurGuestRegistrationEventRow.next_attempt_at.asc(),
                SagurGuestRegistrationEventRow.created_at.asc(),
            )
            .limit(safe_limit)
            .with_for_update(skip_locked=True)
        )
        rows = self._session.execute(statement).scalars().all()
        tasks: list[SagurRegistrationRecoveryTask] = []
        for row in rows:
            row.recovery_attempts += 1
            row.locked_at = now
            row.updated_at = now
            tasks.append(
                SagurRegistrationRecoveryTask(
                    record_id=row.record_id,
                    person_id=row.person_id,
                    platform=row.platform,  # type: ignore[arg-type]
                    external_id=row.external_id,
                    phone_e164=row.phone_e164,
                    registration_origin=row.registration_origin,  # type: ignore[arg-type]
                    recovery_attempts=row.recovery_attempts,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            )
        return tuple(tasks)

    def mark_recovery_customer_found(
        self,
        record_id: UUID,
        *,
        customer_id: str,
        now_utc: datetime | None = None,
    ) -> None:
        """Фиксирует customerId, найденный контрольным поиском iikoCard."""

        self.mark_existing_customer(record_id, customer_id=customer_id, now_utc=now_utc)

    def schedule_recovery_retry(
        self,
        record_id: UUID,
        *,
        error_code: str,
        error_text: str,
        next_attempt_at: datetime,
        max_attempts: int,
        now_utc: datetime | None = None,
    ) -> None:
        """Планирует следующий контрольный поиск или переводит запись в manual_review."""

        now = _utc_now(now_utc)
        row = self._get_row(record_id)
        if row is None:
            return
        if row.recovery_attempts >= max_attempts:
            row.iiko_status = SagurRegistrationIikoStatus.MANUAL_REVIEW.value
            row.sagur_status = SagurRegistrationDeliveryStatus.MANUAL_REVIEW.value
        else:
            row.next_attempt_at = next_attempt_at
        row.locked_at = None
        row.last_error_code = error_code
        row.last_error_text = _trim_error_text(error_text)
        row.updated_at = now

    def _find_active_context_row(
        self,
        context: SagurRegistrationContext,
    ) -> SagurGuestRegistrationEventRow | None:
        statement = (
            select(SagurGuestRegistrationEventRow)
            .where(
                SagurGuestRegistrationEventRow.person_id == context.person_id,
                SagurGuestRegistrationEventRow.platform == context.platform,
                SagurGuestRegistrationEventRow.external_id == context.external_id,
                SagurGuestRegistrationEventRow.registration_origin == context.registration_origin,
                SagurGuestRegistrationEventRow.sagur_status.not_in(_TERMINAL_DELIVERY_STATUSES),
            )
            .order_by(SagurGuestRegistrationEventRow.updated_at.desc())
            .limit(1)
        )
        return self._session.execute(statement).scalars().first()

    def _get_row(self, record_id: UUID) -> SagurGuestRegistrationEventRow | None:
        return self._session.get(SagurGuestRegistrationEventRow, record_id)

    def _load_payload_projection(
        self,
        row: SagurGuestRegistrationEventRow,
    ) -> _SagurRegistrationPayloadProjection | None:
        statement = (
            select(PersonRow, PhoneRow, PlatformAccountRow, PersonPlatformStateRow)
            .join(PhoneRow, PhoneRow.person_id == PersonRow.person_id)
            .join(
                PlatformAccountRow,
                (PlatformAccountRow.person_id == PersonRow.person_id)
                & (PlatformAccountRow.platform == row.platform)
                & (PlatformAccountRow.external_id == row.external_id),
            )
            .outerjoin(
                PersonPlatformStateRow,
                (PersonPlatformStateRow.person_id == PersonRow.person_id)
                & (PersonPlatformStateRow.platform == row.platform),
            )
            .where(PersonRow.person_id == row.person_id)
            .limit(1)
        )
        db_row = self._session.execute(statement).first()
        if db_row is None:
            return None

        person_row, phone_row, account_row, state_row = db_row
        if state_row is None or not row.customer_id:
            return None
        if state_row.registered_at is None or state_row.updated_at is None:
            return None
        if not state_row.is_registered:
            return None

        effective_updated_at = max(
            _aware_utc(state_row.updated_at),
            _aware_utc(account_row.created_at),
            _aware_utc(person_row.updated_at),
        )
        return _SagurRegistrationPayloadProjection(
            person_id=person_row.person_id,
            phone_e164=phone_row.phone_e164,
            platform=account_row.platform,
            external_id=account_row.external_id,
            customer_id=row.customer_id,
            rules_accepted=bool(state_row.rules_accepted),
            notifications_allowed=bool(state_row.notifications_allowed),
            is_registered=bool(state_row.is_registered),
            registered_at=state_row.registered_at,
            state_updated_at=state_row.updated_at,
            account_created_at=account_row.created_at,
            effective_updated_at=effective_updated_at,
            profile_first_name=person_row.first_name_input,
            profile_last_name=person_row.last_name_input,
            profile_gender=person_row.gender,
            profile_email=person_row.email,
            profile_birthdate=person_row.birth_date,
        )


def build_sagur_registration_payload(
    *,
    projection: _SagurRegistrationPayloadProjection,
    event_id: str,
    request_id: str,
) -> dict[str, object]:
    """Формирует JSON payload по контракту SAGUR."""

    profile: dict[str, object] = {}
    if projection.profile_first_name:
        profile["first_name"] = projection.profile_first_name
    if projection.profile_last_name:
        profile["last_name"] = projection.profile_last_name
    if projection.profile_gender:
        profile["gender"] = projection.profile_gender
    if projection.profile_email:
        profile["email"] = projection.profile_email
    if projection.profile_birthdate is not None:
        profile["birthdate"] = projection.profile_birthdate.isoformat()

    return {
        "request_id": request_id,
        "event_id": event_id,
        "event_type": SAGUR_GUEST_REGISTERED_EVENT_TYPE,
        "person_id": str(projection.person_id),
        "platform": projection.platform,
        "phone_e164": projection.phone_e164,
        "customerId": projection.customer_id,
        "external_id": projection.external_id,
        "rules_accepted": bool(projection.rules_accepted),
        "notifications_allowed": bool(projection.notifications_allowed),
        "is_registered": bool(projection.is_registered),
        "registered_at": _format_datetime_utc(projection.registered_at),
        "state_updated_at": _format_datetime_utc(projection.state_updated_at),
        "account_created_at": _format_datetime_utc(projection.account_created_at),
        "effective_updated_at": _format_datetime_utc(projection.effective_updated_at),
        "profile": profile,
    }


def dump_sagur_registration_payload(payload: dict[str, object]) -> bytes:
    """Возвращает стабильные UTF-8 байты payload для подписи и повторов."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _should_create_welcome_event(row: SagurGuestRegistrationEventRow) -> bool:
    if row.registration_origin == "legacy_upgrade":
        return True
    return row.created_new_customer is True or row.create_started_at is not None


def _utc_now(value: datetime | None = None) -> datetime:
    return _aware_utc(value or datetime.now(timezone.utc))


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_datetime_utc(value: datetime) -> str:
    return _aware_utc(value).isoformat().replace("+00:00", "Z")


def _trim_error_text(value: str) -> str:
    return str(value)[:2000]
