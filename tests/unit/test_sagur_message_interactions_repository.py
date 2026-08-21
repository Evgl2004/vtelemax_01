"""Тесты однотабличного регистра нажатий интерактивных сообщений SAGUR."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vtelemax.core.sagur_message_interactions import SagurMessageInteractionIngress
from vtelemax.infrastructure.postgres.sagur_message_interactions_repository import (
    SQLAlchemySagurMessageInteractionsRepository,
)
from vtelemax.infrastructure.postgres.schema import Base, SagurMessageInteractionEventRow


_NOW = datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc)
_EVENT_IDS = (
    UUID("aaaaaaaa-0000-0000-0000-000000000001"),
    UUID("aaaaaaaa-0000-0000-0000-000000000002"),
    UUID("aaaaaaaa-0000-0000-0000-000000000003"),
    UUID("aaaaaaaa-0000-0000-0000-000000000004"),
)
_LEASE_IDS = (
    UUID("bbbbbbbb-0000-0000-0000-000000000001"),
    UUID("bbbbbbbb-0000-0000-0000-000000000002"),
)


def _build_repository() -> tuple[Session, SQLAlchemySagurMessageInteractionsRepository]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    identifiers = iter(_EVENT_IDS)
    return session, SQLAlchemySagurMessageInteractionsRepository(
        session,
        event_id_factory=lambda: next(identifiers),
    )


def _ingress(**overrides: Any) -> SagurMessageInteractionIngress:
    values: dict[str, Any] = {
        "platform": "telegram",
        "bot_scope": "tg_sa_bal_bot",
        "platform_callback_id": "987654321",
        "interaction_id": 123456,
        "action": "l",
        "provider_message_id": "654587",
    }
    values.update(overrides)
    return SagurMessageInteractionIngress(**values)


def _record(
    repository: SQLAlchemySagurMessageInteractionsRepository,
    **overrides: Any,
) -> UUID:
    result = repository.record_event(_ingress(**overrides), now_utc=_NOW)
    assert result.created is True
    return result.event.event_id


def test_new_event_uses_atomic_insert_without_history_select() -> None:
    session, repository = _build_repository()
    sql_statements: list[str] = []

    @event.listens_for(session.get_bind(), "before_cursor_execute")
    def _capture_sql(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        sql_statements.append(statement.lstrip().upper())

    result = repository.record_event(_ingress(), now_utc=_NOW)
    session.commit()

    assert result.created is True
    assert result.immutable_fields_match is True
    assert result.event.event_id == _EVENT_IDS[0]
    assert result.event.occurred_at == _NOW
    assert sql_statements[0].startswith("INSERT")
    assert not any(statement.startswith("SELECT") for statement in sql_statements)

    row = session.get(SagurMessageInteractionEventRow, result.event.event_id)
    assert row is not None
    assert row.delivery_status == "pending"
    assert row.user_action_status == "pending"
    assert row.delivery_attempts == 0
    assert row.next_attempt_at == _NOW.replace(tzinfo=None)


def test_same_platform_key_returns_original_event_without_second_row() -> None:
    session, repository = _build_repository()
    first = repository.record_event(_ingress(), now_utc=_NOW)
    second = repository.record_event(_ingress(), now_utc=_NOW + timedelta(minutes=5))
    session.commit()

    assert first.created is True
    assert second.created is False
    assert second.immutable_fields_match is True
    assert second.event.event_id == first.event.event_id
    assert second.event.occurred_at == _NOW
    row_count = session.scalar(select(func.count()).select_from(SagurMessageInteractionEventRow))
    assert row_count == 1


def test_same_platform_key_with_changed_fact_is_reported_and_never_overwritten() -> None:
    session, repository = _build_repository()
    first = repository.record_event(_ingress(), now_utc=_NOW)
    conflict = repository.record_event(
        _ingress(interaction_id=999, action="d", provider_message_id="other"),
        now_utc=_NOW + timedelta(seconds=1),
    )
    session.commit()

    assert conflict.created is False
    assert conflict.immutable_fields_match is False
    assert conflict.event == first.event


def test_missing_row_after_unique_conflict_is_reported_as_invariant_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session, repository = _build_repository()
    repository.record_event(_ingress(), now_utc=_NOW)
    monkeypatch.setattr(repository, "_find_by_platform_key", lambda _ingress: None)

    with pytest.raises(RuntimeError, match="не найдено после конфликта"):
        repository.record_event(_ingress(), now_utc=_NOW)


def test_new_callback_identifier_creates_new_event_for_repeated_real_click() -> None:
    session, repository = _build_repository()
    first = repository.record_event(_ingress(), now_utc=_NOW)
    second = repository.record_event(
        _ingress(platform_callback_id="987654322"),
        now_utc=_NOW + timedelta(seconds=1),
    )
    session.commit()

    assert first.event.event_id != second.event.event_id
    assert second.created is True
    row_count = session.scalar(select(func.count()).select_from(SagurMessageInteractionEventRow))
    assert row_count == 2


@pytest.mark.parametrize(
    "ingress",
    [
        _ingress(platform="other"),
        _ingress(bot_scope=""),
        _ingress(bot_scope="x" * 129),
        _ingress(platform_callback_id=""),
        _ingress(platform_callback_id="x" * 513),
        _ingress(interaction_id=0),
        _ingress(interaction_id=9_223_372_036_854_775_808),
        _ingress(action="x"),
        _ingress(provider_message_id="x" * 256),
    ],
)
def test_invalid_ingress_is_rejected_before_database_write(
    ingress: SagurMessageInteractionIngress,
) -> None:
    session, repository = _build_repository()

    with pytest.raises(ValueError):
        repository.record_event(ingress, now_utc=_NOW)

    assert session.scalar(select(func.count()).select_from(SagurMessageInteractionEventRow)) == 0


def test_user_action_result_is_independent_from_delivery_state() -> None:
    session, repository = _build_repository()
    success_id = _record(repository)
    failed_id = _record(repository, platform_callback_id="second", action="m")
    missing_id = UUID("aaaaaaaa-0000-0000-0000-000000000099")
    attempt_started = _NOW + timedelta(seconds=1)
    finished = _NOW + timedelta(seconds=2)

    assert repository.mark_user_action_succeeded(
        success_id,
        attempted_at=attempt_started,
        now_utc=finished,
    )
    assert repository.mark_user_action_failed(
        failed_id,
        attempted_at=attempt_started,
        error_code="platform_error" * 20,
        error_text="я" * 2_100,
        now_utc=finished,
    )
    assert not repository.mark_user_action_succeeded(
        missing_id,
        attempted_at=attempt_started,
        now_utc=finished,
    )
    session.commit()

    success = session.get(SagurMessageInteractionEventRow, success_id)
    failed = session.get(SagurMessageInteractionEventRow, failed_id)
    assert success is not None and failed is not None
    assert success.user_action_status == "succeeded"
    assert success.delivery_status == "pending"
    assert success.user_action_error_code is None
    assert failed.user_action_status == "failed"
    assert failed.delivery_status == "pending"
    assert len(failed.user_action_error_code or "") == 128
    assert len(failed.user_action_error_text or "") == 2_000


def test_due_queue_transitions_cover_success_retry_and_permanent_block() -> None:
    session, repository = _build_repository()
    accepted_id = _record(repository)
    retry_id = _record(repository, platform_callback_id="retry", action="d")
    blocked_id = _record(repository, platform_callback_id="blocked", action="c")
    future_id = _record(repository, platform_callback_id="future", action="m")
    future_row = session.get(SagurMessageInteractionEventRow, future_id)
    assert future_row is not None
    future_row.next_attempt_at = _NOW + timedelta(hours=1)
    session.commit()

    tasks = repository.select_due_events_for_update(limit=500, now_utc=_NOW)
    assert [task.event_id for task in tasks] == [accepted_id, retry_id, blocked_id]
    assert all(task.delivery_attempts == 1 for task in tasks)
    assert (
        repository.mark_processing(
            [task.event_id for task in tasks],
            lease_id=_LEASE_IDS[0],
            now_utc=_NOW,
        )
        == 3
    )
    assert repository.mark_processing([], lease_id=_LEASE_IDS[0], now_utc=_NOW) == 0
    session.commit()

    response_time = _NOW + timedelta(seconds=2)
    assert repository.mark_delivered(
        accepted_id,
        lease_id=_LEASE_IDS[0],
        result="accepted",
        now_utc=response_time,
    )
    assert repository.schedule_retry(
        retry_id,
        lease_id=_LEASE_IDS[0],
        error_code="temporary",
        error_text="временная ошибка",
        next_attempt_at=_NOW + timedelta(seconds=30),
        now_utc=response_time,
    )
    assert repository.mark_blocked(
        blocked_id,
        lease_id=_LEASE_IDS[0],
        error_code="interaction_not_found",
        error_text="интерактивность не найдена",
        now_utc=response_time,
    )
    session.commit()

    accepted = session.get(SagurMessageInteractionEventRow, accepted_id)
    retry = session.get(SagurMessageInteractionEventRow, retry_id)
    blocked = session.get(SagurMessageInteractionEventRow, blocked_id)
    assert accepted is not None and retry is not None and blocked is not None
    assert (accepted.delivery_status, accepted.delivery_result) == ("delivered", "accepted")
    assert accepted.delivered_at == response_time.replace(tzinfo=None)
    assert retry.delivery_status == "retry_scheduled"
    assert retry.delivery_attempts == 1
    assert retry.locked_at is None
    assert retry.delivery_lease_id is None
    assert blocked.delivery_status == "blocked"
    assert blocked.delivery_attempts == 1


@pytest.mark.parametrize("result", ["duplicate", "rating_already_recorded"])
def test_all_confirmed_sagur_results_finish_delivery(result: str) -> None:
    session, repository = _build_repository()
    event_id = _record(repository)
    repository.mark_processing([event_id], lease_id=_LEASE_IDS[0], now_utc=_NOW)

    assert repository.mark_delivered(
        event_id,
        lease_id=_LEASE_IDS[0],
        result=result,
        now_utc=_NOW,
    )
    session.commit()

    row = session.get(SagurMessageInteractionEventRow, event_id)
    assert row is not None
    assert row.delivery_status == "delivered"
    assert row.delivery_result == result


def test_unknown_success_result_is_rejected() -> None:
    _session, repository = _build_repository()

    with pytest.raises(ValueError, match="Неподдерживаемый"):
        repository.mark_delivered(
            _EVENT_IDS[0],
            lease_id=_LEASE_IDS[0],
            result="rejected",
            now_utc=_NOW,
        )


def test_stale_processing_is_released_but_fresh_lock_is_preserved() -> None:
    session, repository = _build_repository()
    stale_id = _record(repository)
    fresh_id = _record(repository, platform_callback_id="fresh")
    repository.mark_processing(
        [stale_id, fresh_id],
        lease_id=_LEASE_IDS[0],
        now_utc=_NOW,
    )
    stale = session.get(SagurMessageInteractionEventRow, stale_id)
    fresh = session.get(SagurMessageInteractionEventRow, fresh_id)
    assert stale is not None and fresh is not None
    stale.locked_at = _NOW - timedelta(minutes=10)
    fresh.locked_at = _NOW - timedelta(seconds=10)
    session.commit()

    released = repository.release_stale_processing(
        lock_timeout_seconds=60,
        now_utc=_NOW,
    )
    session.commit()

    assert released == 1
    session.refresh(stale)
    session.refresh(fresh)
    assert stale.delivery_status == "retry_scheduled"
    assert stale.next_attempt_at == _NOW.replace(tzinfo=None)
    assert stale.locked_at is None
    assert stale.delivery_lease_id is None
    assert stale.delivery_error_code == "processing_timeout"
    assert fresh.delivery_status == "processing"
    assert fresh.delivery_lease_id == _LEASE_IDS[0]


def test_late_result_from_released_lease_cannot_overwrite_new_attempt() -> None:
    """Проверяет защиту новой попытки от запоздавшего результата старого работника."""

    session, repository = _build_repository()
    event_id = _record(repository)
    repository.mark_processing(
        [event_id],
        lease_id=_LEASE_IDS[0],
        now_utc=_NOW - timedelta(minutes=10),
    )
    session.commit()

    assert repository.release_stale_processing(lock_timeout_seconds=60, now_utc=_NOW) == 1
    assert repository.mark_processing(
        [event_id],
        lease_id=_LEASE_IDS[1],
        now_utc=_NOW,
    ) == 1
    session.commit()

    assert not repository.mark_delivered(
        event_id,
        lease_id=_LEASE_IDS[0],
        result="accepted",
        now_utc=_NOW + timedelta(seconds=1),
    )
    session.commit()
    row = session.get(SagurMessageInteractionEventRow, event_id)
    assert row is not None
    assert row.delivery_status == "processing"
    assert row.delivery_lease_id == _LEASE_IDS[1]

    assert repository.mark_delivered(
        event_id,
        lease_id=_LEASE_IDS[1],
        result="accepted",
        now_utc=_NOW + timedelta(seconds=2),
    )
    session.commit()
    session.refresh(row)
    assert row.delivery_status == "delivered"
    assert row.delivery_lease_id is None


@pytest.mark.parametrize(
    "values",
    [
        pytest.param(
            {"delivery_status": "processing", "delivery_attempts": 1},
            id="processing_without_lease",
        ),
        pytest.param(
            {"delivery_status": "delivered", "delivery_attempts": 1},
            id="delivered_without_result",
        ),
        pytest.param(
            {"user_action_status": "succeeded"},
            id="succeeded_without_timestamps",
        ),
    ],
)
def test_database_rejects_inconsistent_interaction_state(values: dict[str, object]) -> None:
    """Проверяет, что несогласованный статус нельзя сохранить в обход репозитория."""

    session, repository = _build_repository()
    event_id = _record(repository)
    session.commit()
    row = session.get(SagurMessageInteractionEventRow, event_id)
    assert row is not None
    for field_name, value in values.items():
        setattr(row, field_name, value)

    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_naive_clock_is_interpreted_as_utc() -> None:
    _session, repository = _build_repository()
    naive_now = _NOW.replace(tzinfo=None)

    result = repository.record_event(_ingress(), now_utc=naive_now)

    assert result.event.occurred_at == _NOW


def test_atomic_insert_builder_supports_postgresql_dialect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, repository = _build_repository()
    fake_bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    monkeypatch.setattr(session, "get_bind", lambda: fake_bind)

    statement = repository._build_atomic_insert({})

    assert statement is not None


def test_atomic_insert_builder_rejects_unknown_database_dialect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, repository = _build_repository()
    fake_bind = SimpleNamespace(dialect=SimpleNamespace(name="other"))
    monkeypatch.setattr(session, "get_bind", lambda: fake_bind)

    with pytest.raises(RuntimeError, match="Неподдерживаемый диалект"):
        repository._build_atomic_insert({})
