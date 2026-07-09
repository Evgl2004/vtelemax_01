"""Тесты исходящего регистра событий регистрации SAGUR."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from vtelemax.adapters.sagur_registration_events import (
    SagurRegistrationDeliveryOutcome,
    SagurRegistrationEventsProcessor,
    build_vtelemax_registration_canonical_string,
    build_vtelemax_registration_signature,
)
from vtelemax.core import SagurRegistrationContext
from vtelemax.infrastructure.postgres.sagur_registration_events_repository import (
    SQLAlchemySagurRegistrationEventsRepository,
)
from vtelemax.infrastructure.postgres.schema import (
    Base,
    PersonPlatformStateRow,
    PersonRow,
    PhoneRow,
    PlatformAccountRow,
    SagurGuestRegistrationEventRow,
)


def _build_session_factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _insert_registered_person(
    session: Session,
    *,
    person_id: UUID,
    platform: str,
    external_id: str,
    phone_e164: str = "+79224800001",
) -> None:
    now = datetime(2026, 7, 9, 8, 11, tzinfo=timezone.utc)
    session.add(
        PersonRow(
            person_id=person_id,
            created_at=now,
            updated_at=now,
            rules_accepted=True,
            rules_accepted_at=now,
            notifications_allowed=True,
            notifications_allowed_at=now,
            is_legacy=False,
            is_moderator=False,
            is_registered=True,
            first_name_input="Анна",
            last_name_input="Петрова",
            email="anna@example.test",
        )
    )
    session.flush()
    session.add(
        PhoneRow(
            phone_id=uuid4(),
            person_id=person_id,
            phone_e164=phone_e164,
            created_at=now,
        )
    )
    session.add(
        PlatformAccountRow(
            account_id=uuid4(),
            person_id=person_id,
            platform=platform,
            external_id=external_id,
            lifecycle_status="pending_verification" if platform == "vk" else "active",
            created_at=now,
        )
    )
    session.add(
        PersonPlatformStateRow(
            person_id=person_id,
            platform=platform,
            rules_accepted=True,
            rules_accepted_at=now,
            notifications_allowed=True,
            notifications_allowed_at=now,
            is_registered=True,
            registered_at=now,
            created_at=now,
            updated_at=now,
        )
    )


def _create_registry_record(
    session: Session,
    *,
    person_id: UUID,
    platform: str,
    external_id: str,
    origin: str = "new_registration",
) -> UUID:
    repository = SQLAlchemySagurRegistrationEventsRepository(session)
    record_id = repository.ensure_iiko_lookup_started(
        SagurRegistrationContext(
            person_id=person_id,
            platform=platform,  # type: ignore[arg-type]
            external_id=external_id,
            phone_e164="+79224800001",
            registration_origin=origin,  # type: ignore[arg-type]
        )
    )
    session.commit()
    return record_id


def test_new_iiko_customer_creates_pending_sagur_event_with_stable_payload() -> None:
    """Новый iikoCard-гость создает pending-событие и не меняет payload при повторе."""

    session_factory = _build_session_factory()
    session = session_factory()
    person_id = uuid4()
    _insert_registered_person(
        session,
        person_id=person_id,
        platform="telegram",
        external_id="1001",
    )
    record_id = _create_registry_record(
        session,
        person_id=person_id,
        platform="telegram",
        external_id="1001",
    )
    repository = SQLAlchemySagurRegistrationEventsRepository(session)
    repository.mark_create_started(record_id)
    repository.mark_created_customer(record_id, customer_id="iiko-customer-1")

    assert repository.create_pending_event_if_required(record_id) is True
    session.commit()

    row = session.get(SagurGuestRegistrationEventRow, record_id)
    assert row is not None
    assert row.sagur_status == "pending"
    assert row.event_id is not None
    assert row.request_id is not None
    assert row.payload_json is not None
    assert row.payload_json["customerId"] == "iiko-customer-1"
    assert row.payload_json["request_id"] == row.request_id
    assert row.payload_json["event_id"] == row.event_id
    assert row.payload_json["platform"] == "telegram"
    original_body = row.payload_body
    original_event_id = row.event_id

    assert repository.create_pending_event_if_required(record_id) is True
    session.commit()

    row = session.get(SagurGuestRegistrationEventRow, record_id)
    assert row is not None
    assert row.event_id == original_event_id
    assert row.payload_body == original_body


def test_non_legacy_existing_iiko_customer_does_not_create_welcome_event() -> None:
    """Обычный не-legacy гость, уже найденный в iikoCard, не ставит welcome-событие."""

    session_factory = _build_session_factory()
    session = session_factory()
    person_id = uuid4()
    _insert_registered_person(session, person_id=person_id, platform="max", external_id="3003")
    record_id = _create_registry_record(
        session,
        person_id=person_id,
        platform="max",
        external_id="3003",
    )
    repository = SQLAlchemySagurRegistrationEventsRepository(session)
    repository.mark_existing_customer(record_id, customer_id="iiko-existing")

    assert repository.create_pending_event_if_required(record_id) is False
    session.commit()

    row = session.get(SagurGuestRegistrationEventRow, record_id)
    assert row is not None
    assert row.sagur_status == "not_required"
    assert row.event_id is None
    assert row.payload_body is None


def test_legacy_existing_iiko_customer_creates_welcome_event() -> None:
    """Legacy-регистрация ставит событие с customerId, найденным в iikoCard."""

    session_factory = _build_session_factory()
    session = session_factory()
    person_id = uuid4()
    _insert_registered_person(session, person_id=person_id, platform="vk", external_id="2002")
    record_id = _create_registry_record(
        session,
        person_id=person_id,
        platform="vk",
        external_id="2002",
        origin="legacy_upgrade",
    )
    repository = SQLAlchemySagurRegistrationEventsRepository(session)
    repository.mark_existing_customer(record_id, customer_id="iiko-legacy")

    assert repository.create_pending_event_if_required(record_id) is True
    session.commit()

    row = session.get(SagurGuestRegistrationEventRow, record_id)
    assert row is not None
    assert row.sagur_status == "pending"
    assert row.payload_json is not None
    assert row.payload_json["platform"] == "vk"
    assert row.payload_json["customerId"] == "iiko-legacy"


def test_hmac_signature_uses_actual_payload_bytes() -> None:
    """Проверяет каноническую строку и HMAC от фактических байтов тела."""

    payload_body = '{"customerId":"iiko-1","profile":{"first_name":"Анна"}}'.encode("utf-8")
    body_hash = hashlib.sha256(payload_body).hexdigest()

    canonical = build_vtelemax_registration_canonical_string(
        method="POST",
        path="/internal/integration/v1/vtelemax/registration-events",
        timestamp="1783591800",
        payload_body=payload_body,
    )
    signature = build_vtelemax_registration_signature(
        secret="secret",
        method="POST",
        path="/internal/integration/v1/vtelemax/registration-events",
        timestamp="1783591800",
        payload_body=payload_body,
    )

    assert canonical == "\n".join(
        (
            "POST",
            "/internal/integration/v1/vtelemax/registration-events",
            "1783591800",
            body_hash,
        )
    )
    assert signature == hmac.new(
        b"secret",
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@dataclass(slots=True)
class _FakeSagurHttpClient:
    outcome: SagurRegistrationDeliveryOutcome

    async def send(self, task):  # noqa: ANN001
        return self.outcome


def test_processor_treats_accepted_duplicate_as_success() -> None:
    """`202 duplicate=true` завершает отправку как успех."""

    session_factory = _build_session_factory()
    session = session_factory()
    person_id = uuid4()
    _insert_registered_person(session, person_id=person_id, platform="telegram", external_id="1001")
    record_id = _create_registry_record(
        session,
        person_id=person_id,
        platform="telegram",
        external_id="1001",
    )
    repository = SQLAlchemySagurRegistrationEventsRepository(session)
    repository.mark_create_started(record_id)
    repository.mark_created_customer(record_id, customer_id="iiko-customer-1")
    repository.create_pending_event_if_required(record_id)
    session.commit()

    processor = SagurRegistrationEventsProcessor(
        session_factory=session_factory,
        http_client=_FakeSagurHttpClient(  # type: ignore[arg-type]
            SagurRegistrationDeliveryOutcome(status="accepted", duplicate=True, http_status=202)
        ),
        max_attempts=3,
    )

    sent_count, conflict_count, retry_count, failed_count = asyncio.run(processor.process_once(limit=5))

    assert (sent_count, conflict_count, retry_count, failed_count) == (1, 0, 0, 0)
    check_session = session_factory()
    row = check_session.get(SagurGuestRegistrationEventRow, record_id)
    assert row is not None
    assert row.sagur_status == "sent"
    assert row.last_error_code == "duplicate"


def test_processor_stops_automatic_retry_on_event_payload_conflict() -> None:
    """`409 event_id_payload_conflict` переводит запись в conflict без retry."""

    session_factory = _build_session_factory()
    session = session_factory()
    person_id = uuid4()
    _insert_registered_person(session, person_id=person_id, platform="telegram", external_id="1001")
    record_id = _create_registry_record(
        session,
        person_id=person_id,
        platform="telegram",
        external_id="1001",
    )
    repository = SQLAlchemySagurRegistrationEventsRepository(session)
    repository.mark_create_started(record_id)
    repository.mark_created_customer(record_id, customer_id="iiko-customer-1")
    repository.create_pending_event_if_required(record_id)
    session.commit()

    processor = SagurRegistrationEventsProcessor(
        session_factory=session_factory,
        http_client=_FakeSagurHttpClient(  # type: ignore[arg-type]
            SagurRegistrationDeliveryOutcome(
                status="conflict",
                http_status=409,
                error_code="event_id_payload_conflict",
                error_text="conflict",
            )
        ),
        max_attempts=3,
    )

    sent_count, conflict_count, retry_count, failed_count = asyncio.run(processor.process_once(limit=5))

    assert (sent_count, conflict_count, retry_count, failed_count) == (0, 1, 0, 0)
    check_session = session_factory()
    row = check_session.get(SagurGuestRegistrationEventRow, record_id)
    assert row is not None
    assert row.sagur_status == "conflict"
    assert row.last_error_code == "event_id_payload_conflict"
