"""Тесты транзакционной границы приёма нажатий SAGUR."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from vtelemax.adapters.sagur_message_interactions import (
    SagurMessageInteractionService,
    SagurMessageInteractionStorageError,
    platform_callback_fingerprint,
    utc_now,
)
from vtelemax.core.sagur_message_interactions import SagurMessageInteractionIngress
from vtelemax.infrastructure.postgres.schema import Base, SagurMessageInteractionEventRow


def _session_factory(*, create_schema: bool = True) -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    if create_schema:
        Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _ingress() -> SagurMessageInteractionIngress:
    return SagurMessageInteractionIngress(
        platform="telegram",
        bot_scope="tg_sa_bal_bot",
        platform_callback_id="987654321",
        interaction_id=123456,
        action="l",
        provider_message_id="654587",
    )


def test_service_commits_new_event_and_returns_same_event_for_duplicate() -> None:
    factory = _session_factory()
    service = SagurMessageInteractionService(factory)

    first = service.record_event(_ingress())
    duplicate = service.record_event(_ingress())

    assert first.created is True
    assert duplicate.created is False
    assert duplicate.event.event_id == first.event.event_id
    with factory() as session:
        assert session.get(SagurMessageInteractionEventRow, first.event.event_id) is not None


def test_service_does_not_report_success_when_database_write_fails() -> None:
    service = SagurMessageInteractionService(_session_factory(create_schema=False))

    with pytest.raises(SagurMessageInteractionStorageError) as error:
        service.record_event(_ingress())

    assert isinstance(error.value.__cause__, Exception)


def test_service_records_success_and_failure_of_user_action() -> None:
    factory = _session_factory()
    service = SagurMessageInteractionService(factory)
    success = service.record_event(_ingress())
    failure_ingress = SagurMessageInteractionIngress(
        platform="telegram",
        bot_scope="tg_sa_bal_bot",
        platform_callback_id="987654322",
        interaction_id=123456,
        action="m",
        provider_message_id="654587",
    )
    failure = service.record_event(failure_ingress)
    attempted_at = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)

    service.mark_user_action_succeeded(success.event.event_id, attempted_at=attempted_at)
    service.mark_user_action_failed(
        failure.event.event_id,
        attempted_at=attempted_at,
        error_code="platform_error",
        error_text="Платформа отклонила действие.",
    )

    with factory() as session:
        success_row = session.get(SagurMessageInteractionEventRow, success.event.event_id)
        failure_row = session.get(SagurMessageInteractionEventRow, failure.event.event_id)
        assert success_row is not None and failure_row is not None
        assert success_row.user_action_status == "succeeded"
        assert failure_row.user_action_status == "failed"


@pytest.mark.parametrize("method_name", ["mark_user_action_succeeded", "mark_user_action_failed"])
def test_service_rejects_user_action_result_for_missing_event(method_name: str) -> None:
    service = SagurMessageInteractionService(_session_factory())
    missing_id = UUID("aaaaaaaa-0000-0000-0000-000000000099")
    attempted_at = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    method = getattr(service, method_name)
    kwargs = {"attempted_at": attempted_at}
    if method_name == "mark_user_action_failed":
        kwargs.update(error_code="missing", error_text="Событие отсутствует.")

    with pytest.raises(SagurMessageInteractionStorageError, match="не найдено"):
        method(missing_id, **kwargs)


def test_safe_callback_fingerprint_is_stable_and_does_not_expose_source() -> None:
    source = "секретный-платформенный-идентификатор"

    first = platform_callback_fingerprint(source)
    second = platform_callback_fingerprint(source)

    assert first == second
    assert len(first) == 16
    assert source not in first


def test_utc_now_returns_aware_utc_time() -> None:
    result = utc_now()

    assert result.tzinfo is timezone.utc
