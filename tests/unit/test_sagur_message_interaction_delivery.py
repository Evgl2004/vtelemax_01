"""Тесты пакетной доставки нажатий интерактивных кнопок в SAGUR."""

from __future__ import annotations

import asyncio
import hashlib
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
import vtelemax.adapters.sagur_message_interaction_delivery as delivery_module
from aiohttp import ClientConnectionError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from vtelemax.adapters.sagur_message_interaction_delivery import (
    SAGUR_MESSAGE_INTERACTION_ENDPOINT_PATH,
    PeriodicSagurMessageInteractionWorker,
    SagurMessageInteractionBatchRequest,
    SagurMessageInteractionDeliveryProcessor,
    SagurMessageInteractionHttpClient,
    SagurMessageInteractionHttpOutcome,
    SagurMessageInteractionProcessingResult,
    _EventDecision,
    _decode_response_object,
    _oldest_event_age_seconds,
    _optional_text,
    _parse_successful_batch_response,
    _parse_retry_after,
    _safe_error_text,
    build_sagur_message_interaction_batch_request,
    format_rfc3339_utc,
)
from vtelemax.adapters.vtelemax_outbound_hmac import (
    build_vtelemax_outbound_canonical_string,
    build_vtelemax_outbound_signature,
    canonical_request_path,
)
from vtelemax.core.sagur_message_interactions import (
    SagurMessageInteractionDeliveryTask,
    SagurMessageInteractionIngress,
    SagurMessageInteractionQueueObservation,
)
from vtelemax.infrastructure.postgres.sagur_message_interactions_repository import (
    SQLAlchemySagurMessageInteractionsRepository,
)
from vtelemax.infrastructure.postgres.schema import Base, SagurMessageInteractionEventRow


_NOW = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
_EVENT_IDS = tuple(UUID(f"aaaaaaaa-0000-0000-0000-{index:012d}") for index in range(1, 20))
_REQUEST_IDS = tuple(UUID(f"20000000-0000-0000-0000-{index:012d}") for index in range(1, 20))


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _task(index: int = 0, **overrides: Any) -> SagurMessageInteractionDeliveryTask:
    values: dict[str, Any] = {
        "event_id": _EVENT_IDS[index],
        "interaction_id": 123456 + index,
        "action": "l",
        "occurred_at": _NOW + timedelta(seconds=index),
        "provider_message_id": f"message-{index}",
        "delivery_attempts": 1,
    }
    values.update(overrides)
    return SagurMessageInteractionDeliveryTask(**values)


def _insert_events(factory: sessionmaker[Session], count: int) -> tuple[UUID, ...]:
    identifiers = iter(_EVENT_IDS)
    with factory() as session:
        repository = SQLAlchemySagurMessageInteractionsRepository(
            session,
            event_id_factory=lambda: next(identifiers),
        )
        result = []
        for index in range(count):
            inserted = repository.record_event(
                SagurMessageInteractionIngress(
                    platform="telegram",
                    bot_scope="tg_sa_bal_bot",
                    platform_callback_id=f"callback-{index}",
                    interaction_id=123456 + index,
                    action=("l", "d", "m", "c")[index % 4],
                    provider_message_id=f"message-{index}",
                ),
                now_utc=_NOW - timedelta(seconds=count - index),
            )
            result.append(inserted.event.event_id)
        session.commit()
    return tuple(result)


def _response(
    request: SagurMessageInteractionBatchRequest,
    results: list[dict[str, object]],
    *,
    status: str = "accepted",
) -> dict[str, object]:
    return {
        "ok": True,
        "schema_version": 1,
        "request_id": request.request_id,
        "status": status,
        "received_at": "2026-08-20T10:00:01Z",
        "results": results,
    }


@dataclass(slots=True)
class _FakeHttpClient:
    outcomes: deque[SagurMessageInteractionHttpOutcome]
    prepared: list[SagurMessageInteractionBatchRequest] = field(default_factory=list)
    sent: list[SagurMessageInteractionBatchRequest] = field(default_factory=list)
    _request_ids: Any = field(default_factory=lambda: iter(_REQUEST_IDS), repr=False)
    now_factory: Any = lambda: _NOW
    request_id_factory: Any = field(init=False)

    def __post_init__(self) -> None:
        self.request_id_factory = lambda: next(self._request_ids)

    def prepare(
        self,
        tasks: tuple[SagurMessageInteractionDeliveryTask, ...],
    ) -> SagurMessageInteractionBatchRequest:
        request = build_sagur_message_interaction_batch_request(
            tasks,
            request_id=self.request_id_factory(),
            sent_at=self.now_factory(),
        )
        self.prepared.append(request)
        return request

    async def send(
        self,
        request: SagurMessageInteractionBatchRequest,
    ) -> SagurMessageInteractionHttpOutcome:
        self.sent.append(request)
        outcome = self.outcomes.popleft()
        if outcome.http_status == 200 and outcome.data == {"dynamic": True}:
            results = [
                {
                    "index": index,
                    "event_id": str(task.event_id),
                    "status": "accepted",
                    "result": "accepted",
                }
                for index, task in enumerate(request.tasks)
            ]
            return SagurMessageInteractionHttpOutcome(
                http_status=200,
                data=_response(request, results),
            )
        return outcome


def _processor(
    factory: sessionmaker[Session],
    client: _FakeHttpClient,
    **overrides: Any,
) -> SagurMessageInteractionDeliveryProcessor:
    values: dict[str, Any] = {
        "session_factory": factory,
        "http_client": client,
        "now_factory": lambda: _NOW,
        "minimum_request_interval_seconds": 0,
        "random_uniform": lambda _start, _end: 0.0,
    }
    values.update(overrides)
    return SagurMessageInteractionDeliveryProcessor(**values)


def test_common_hmac_fixture_matches_sagur_implementation() -> None:
    """Общая байтовая фикстура должна дословно совпадать на обеих сторонах."""

    body = b'{"fixture":true}'
    canonical = build_vtelemax_outbound_canonical_string(
        method="post",
        path=SAGUR_MESSAGE_INTERACTION_ENDPOINT_PATH,
        timestamp="1787200000",
        payload_body=body,
    )

    assert canonical == "\n".join(
        (
            "POST",
            SAGUR_MESSAGE_INTERACTION_ENDPOINT_PATH,
            "1787200000",
            hashlib.sha256(body).hexdigest(),
        )
    )
    assert (
        build_vtelemax_outbound_signature(
            secret="fixture-secret",
            method="POST",
            path=SAGUR_MESSAGE_INTERACTION_ENDPOINT_PATH,
            timestamp="1787200000",
            payload_body=body,
        )
        == "5606137647dfe4d99585d6773f70c5194bfc5f2bdfee45e509a9a483b872fe07"
    )


def test_batch_serialization_is_compact_stable_and_uses_single_actions() -> None:
    request = build_sagur_message_interaction_batch_request(
        (_task(0), _task(1, action="m", provider_message_id=None)),
        request_id=_REQUEST_IDS[0],
        sent_at=_NOW,
    )

    assert request.request_id == str(_REQUEST_IDS[0])
    assert b" " not in request.body
    assert request.body.decode("utf-8") == (
        '{"request_id":"20000000-0000-0000-0000-000000000001",'
        '"schema_version":1,"sent_at":"2026-08-20T10:00:00Z","items":['
        '{"event_id":"aaaaaaaa-0000-0000-0000-000000000001",'
        '"interaction_id":123456,"action":"l","occurred_at":"2026-08-20T10:00:00Z",'
        '"provider_message_id":"message-0"},'
        '{"event_id":"aaaaaaaa-0000-0000-0000-000000000002",'
        '"interaction_id":123457,"action":"m","occurred_at":"2026-08-20T10:00:01Z"}]}'
    )


@pytest.mark.parametrize("tasks", [(), tuple(_task(0) for _ in range(101))])
def test_batch_rejects_invalid_item_count(
    tasks: tuple[SagurMessageInteractionDeliveryTask, ...],
) -> None:
    with pytest.raises(ValueError, match="от 1 до 100"):
        build_sagur_message_interaction_batch_request(
            tasks,
            request_id=_REQUEST_IDS[0],
            sent_at=_NOW,
        )


def test_batch_rejects_invalid_request_id_and_naive_datetime() -> None:
    with pytest.raises(ValueError):
        build_sagur_message_interaction_batch_request(
            (_task(),),
            request_id="not-uuid",
            sent_at=_NOW,
        )
    with pytest.raises(ValueError, match="часовой пояс"):
        format_rfc3339_utc(_NOW.replace(tzinfo=None))


@pytest.mark.parametrize(
    ("endpoint", "default_path", "expected"),
    [
        ("https://example.test", "/default", "/default"),
        ("https://example.test/path?mode=1", "/default", "/path?mode=1"),
    ],
)
def test_canonical_request_path_includes_query(
    endpoint: str,
    default_path: str,
    expected: str,
) -> None:
    assert canonical_request_path(endpoint, default_path=default_path) == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_url": "", "endpoint_path": "/events", "hmac_secret": "secret"},
        {"base_url": "https://example.test", "endpoint_path": "events", "hmac_secret": "secret"},
        {"base_url": "example.test", "endpoint_path": "/events", "hmac_secret": "secret"},
        {"base_url": "https://example.test", "endpoint_path": "/events", "hmac_secret": ""},
        {
            "base_url": "http://example.test",
            "endpoint_path": "/events",
            "hmac_secret": "secret",
        },
        {
            "base_url": "https://example.test",
            "endpoint_path": "/events",
            "hmac_secret": "secret",
            "timeout_seconds": 0,
        },
    ],
)
def test_http_client_rejects_unsafe_configuration(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        SagurMessageInteractionHttpClient(**kwargs)  # type: ignore[arg-type]


def test_http_client_rejects_base_url_with_path_or_query() -> None:
    with pytest.raises(ValueError, match="не должен содержать путь"):
        SagurMessageInteractionHttpClient(
            base_url="https://example.test/root?mode=1",
            endpoint_path="/events",
            hmac_secret="secret",
        )


def test_http_client_builds_endpoint_and_new_request_ids() -> None:
    identifiers = iter(_REQUEST_IDS)
    client = SagurMessageInteractionHttpClient(
        base_url="https://example.test/ ",
        endpoint_path=SAGUR_MESSAGE_INTERACTION_ENDPOINT_PATH,
        hmac_secret="secret",
        now_factory=lambda: _NOW,
        request_id_factory=lambda: next(identifiers),
    )

    first = client.prepare((_task(),))
    second = client.prepare((_task(),))

    assert client.endpoint == f"https://example.test{SAGUR_MESSAGE_INTERACTION_ENDPOINT_PATH}"
    assert first.request_id != second.request_id
    assert first.tasks[0].event_id == second.tasks[0].event_id


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("12", 12.0),
        ("-2", 0.0),
        ("invalid", None),
        ("Thu, 20 Aug 2026 10:01:00 GMT", 60.0),
    ],
)
def test_retry_after_supports_seconds_and_http_date(
    value: str | None, expected: float | None
) -> None:
    assert _parse_retry_after(value, now=_NOW) == expected


@dataclass(slots=True)
class _FakeResponse:
    status: int
    raw_body: bytes
    headers: dict[str, str]

    async def read(self) -> bytes:
        return self.raw_body


@dataclass(slots=True)
class _AsyncContext:
    value: object | None = None
    error: Exception | None = None

    async def __aenter__(self) -> object:
        if self.error is not None:
            raise self.error
        return self.value

    async def __aexit__(self, *_args: object) -> None:
        return None


@dataclass(slots=True)
class _FakeClientSession:
    response_context: _AsyncContext
    captured: dict[str, object]
    closed: bool = False
    post_calls: int = 0
    close_calls: int = 0

    def post(self, endpoint: str, *, data: bytes, headers: dict[str, str]) -> _AsyncContext:
        self.post_calls += 1
        self.captured.update(endpoint=endpoint, data=data, headers=headers)
        return self.response_context

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


def test_real_http_client_signs_actual_bytes_and_reads_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    response = _FakeResponse(
        status=429,
        raw_body=b'{"code":"rate_limited","message":" wait "}',
        headers={"Retry-After": "12"},
    )
    fake_session = _FakeClientSession(_AsyncContext(value=response), captured)
    monkeypatch.setattr(
        delivery_module.aiohttp,
        "ClientSession",
        lambda *, timeout: fake_session,
    )
    client = SagurMessageInteractionHttpClient(
        base_url="https://example.test",
        endpoint_path=SAGUR_MESSAGE_INTERACTION_ENDPOINT_PATH,
        hmac_secret="secret",
        now_factory=lambda: _NOW,
        request_id_factory=lambda: _REQUEST_IDS[0],
    )
    request = client.prepare((_task(),))

    async def _send_and_close() -> SagurMessageInteractionHttpOutcome:
        outcome = await client.send(request)
        await client.close()
        return outcome

    outcome = asyncio.run(_send_and_close())

    assert outcome == SagurMessageInteractionHttpOutcome(
        http_status=429,
        data={"code": "rate_limited", "message": " wait "},
        error_code="rate_limited",
        error_text="wait",
        retry_after_seconds=12,
    )
    assert captured["endpoint"] == client.endpoint
    assert captured["data"] == request.body
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["X-Vtelemax-Request-Id"] == request.request_id
    assert headers["X-Vtelemax-Signature"] == build_vtelemax_outbound_signature(
        secret="secret",
        method="POST",
        path=SAGUR_MESSAGE_INTERACTION_ENDPOINT_PATH,
        timestamp=str(int(_NOW.timestamp())),
        payload_body=request.body,
    )
    assert fake_session.post_calls == 1
    assert fake_session.close_calls == 1


def test_http_client_reuses_one_session_for_multiple_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    response = _FakeResponse(status=200, raw_body=b'{"ok":true}', headers={})
    fake_session = _FakeClientSession(_AsyncContext(value=response), captured)
    session_creations = 0

    def _client_session(*, timeout: object) -> _FakeClientSession:
        nonlocal session_creations
        assert timeout is not None
        session_creations += 1
        return fake_session

    monkeypatch.setattr(delivery_module.aiohttp, "ClientSession", _client_session)
    client = SagurMessageInteractionHttpClient(
        base_url="https://example.test",
        endpoint_path="/events",
        hmac_secret="secret",
        now_factory=lambda: _NOW,
        request_id_factory=lambda: _REQUEST_IDS[0],
    )

    async def _send_twice_and_close() -> None:
        await client.send(client.prepare((_task(),)))
        await client.send(client.prepare((_task(),)))
        await client.close()
        await client.close()

    asyncio.run(_send_twice_and_close())

    assert session_creations == 1
    assert fake_session.post_calls == 2
    assert fake_session.close_calls == 1


def test_real_http_client_converts_network_error_to_retryable_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    fake_session = _FakeClientSession(
        _AsyncContext(error=ClientConnectionError("network unavailable")),
        captured,
    )
    monkeypatch.setattr(
        delivery_module.aiohttp,
        "ClientSession",
        lambda *, timeout: fake_session,
    )
    client = SagurMessageInteractionHttpClient(
        base_url="https://example.test",
        endpoint_path="/events",
        hmac_secret="secret",
        now_factory=lambda: _NOW,
        request_id_factory=lambda: _REQUEST_IDS[0],
    )

    async def _send_and_close() -> SagurMessageInteractionHttpOutcome:
        outcome = await client.send(client.prepare((_task(),)))
        await client.close()
        return outcome

    outcome = asyncio.run(_send_and_close())

    assert outcome.http_status is None
    assert outcome.error_code == "network_error"
    assert outcome.error_text == "network unavailable"


def test_processor_applies_partial_results_independently() -> None:
    factory = _session_factory()
    event_ids = _insert_events(factory, 3)
    client = _FakeHttpClient(deque())
    processor = _processor(factory, client)
    request = processor._claim_request()
    assert request is not None
    client.outcomes.append(
        SagurMessageInteractionHttpOutcome(
            http_status=200,
            data=_response(
                request,
                [
                    {
                        "index": 0,
                        "event_id": str(event_ids[0]),
                        "status": "accepted",
                        "result": "accepted",
                    },
                    {
                        "index": 1,
                        "event_id": str(event_ids[1]),
                        "status": "rejected",
                        "result": "interaction_not_found",
                        "message": "Интерактивность не найдена.",
                    },
                ],
                status="partial",
            ),
        )
    )
    decisions, count = asyncio.run(processor._send_with_splitting(request))
    processor._apply_decisions(decisions, lease_id=UUID(request.request_id))

    assert count == 1
    with factory() as session:
        rows = session.scalars(
            select(SagurMessageInteractionEventRow).order_by(
                SagurMessageInteractionEventRow.occurred_at
            )
        ).all()
    assert [row.delivery_status for row in rows] == ["delivered", "blocked", "retry_scheduled"]
    assert rows[0].delivery_result == "accepted"
    assert rows[1].delivery_error_code == "interaction_not_found"
    assert rows[2].delivery_error_code == "item_result_missing"


def test_processor_returns_empty_result_when_queue_has_no_due_events() -> None:
    result = asyncio.run(_processor(_session_factory(), _FakeHttpClient(deque())).process_once())

    assert result == SagurMessageInteractionProcessingResult()


def test_empty_queue_logs_released_count_from_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SQLAlchemySagurMessageInteractionsRepository,
        "release_stale_processing",
        lambda self, lock_timeout_seconds, now_utc=None: 1,
    )
    monkeypatch.setattr(
        SQLAlchemySagurMessageInteractionsRepository,
        "select_due_events_for_update",
        lambda self, limit, now_utc=None: (),
    )

    request = _processor(_session_factory(), _FakeHttpClient(deque()))._claim_request()

    assert request is None


def test_stale_processing_event_is_released_and_delivered() -> None:
    factory = _session_factory()
    event_id = _insert_events(factory, 1)[0]
    with factory() as session:
        repository = SQLAlchemySagurMessageInteractionsRepository(session)
        repository.mark_processing(
            [event_id],
            lease_id=_REQUEST_IDS[0],
            now_utc=_NOW - timedelta(minutes=10),
        )
        session.commit()
    client = _FakeHttpClient(
        deque([SagurMessageInteractionHttpOutcome(http_status=200, data={"dynamic": True})])
    )

    result = asyncio.run(_processor(factory, client, lock_timeout_seconds=60).process_once())

    assert result.delivered == 1


def test_claim_rolls_back_when_processing_marker_count_is_inconsistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _session_factory()
    event_id = _insert_events(factory, 1)[0]
    monkeypatch.setattr(
        SQLAlchemySagurMessageInteractionsRepository,
        "mark_processing",
        lambda self, event_ids, lease_id, now_utc=None: 0,
    )

    with pytest.raises(RuntimeError, match="Не все выбранные"):
        _processor(factory, _FakeHttpClient(deque()))._claim_request()

    with factory() as session:
        row = session.get(SagurMessageInteractionEventRow, event_id)
        assert row is not None and row.delivery_status == "pending"


def test_claim_rolls_back_database_error() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with pytest.raises(Exception):
        _processor(factory, _FakeHttpClient(deque()))._claim_request()


def test_decision_update_rolls_back_database_error(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _session_factory()
    event_id = _insert_events(factory, 1)[0]

    def _raise_write_error(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("write failed")

    monkeypatch.setattr(
        SQLAlchemySagurMessageInteractionsRepository,
        "mark_delivered",
        _raise_write_error,
    )
    decision = _EventDecision(task=_task(event_id=event_id), state="delivered", code="accepted")

    with pytest.raises(RuntimeError, match="write failed"):
        _processor(factory, _FakeHttpClient(deque()))._apply_decisions(
            (decision,),
            lease_id=_REQUEST_IDS[0],
        )


@pytest.mark.parametrize(
    ("outcome", "expected_status", "expected_code"),
    [
        (
            SagurMessageInteractionHttpOutcome(
                http_status=None,
                error_code="network_error",
                error_text="timeout",
            ),
            "retry_scheduled",
            "network_error",
        ),
        (
            SagurMessageInteractionHttpOutcome(
                http_status=429,
                error_code="rate_limited",
                retry_after_seconds=120,
            ),
            "retry_scheduled",
            "rate_limited",
        ),
        (
            SagurMessageInteractionHttpOutcome(http_status=503),
            "retry_scheduled",
            "http_503",
        ),
        (
            SagurMessageInteractionHttpOutcome(
                http_status=401,
                error_code="signature_invalid",
                error_text="bad signature",
            ),
            "blocked",
            "signature_invalid",
        ),
    ],
)
def test_processor_classifies_transport_and_envelope_failures(
    outcome: SagurMessageInteractionHttpOutcome,
    expected_status: str,
    expected_code: str,
) -> None:
    factory = _session_factory()
    event_id = _insert_events(factory, 1)[0]
    client = _FakeHttpClient(deque([outcome]))
    result = asyncio.run(_processor(factory, client).process_once())

    assert result.selected == 1
    with factory() as session:
        row = session.get(SagurMessageInteractionEventRow, event_id)
        assert row is not None
        assert row.delivery_status == expected_status
        assert row.delivery_error_code == expected_code
        if outcome.http_status == 429:
            assert row.next_attempt_at == (_NOW + timedelta(seconds=120)).replace(tzinfo=None)


def test_invalid_http_200_envelope_retries_every_item() -> None:
    factory = _session_factory()
    _insert_events(factory, 2)
    client = _FakeHttpClient(
        deque([SagurMessageInteractionHttpOutcome(http_status=200, data={"ok": False})])
    )

    result = asyncio.run(_processor(factory, client).process_once())

    assert result == SagurMessageInteractionProcessingResult(
        selected=2,
        retry_scheduled=2,
        http_requests=1,
    )


def test_malformed_item_results_never_create_false_confirmation() -> None:
    request = build_sagur_message_interaction_batch_request(
        tuple(_task(index) for index in range(4)),
        request_id=_REQUEST_IDS[0],
        sent_at=_NOW,
    )
    data = _response(
        request,
        [
            "not-an-object",  # type: ignore[list-item]
            {"index": 99},
            {
                "index": 0,
                "event_id": str(request.tasks[0].event_id),
                "status": "accepted",
                "result": "duplicate",
            },
            {
                "index": 0,
                "event_id": str(request.tasks[0].event_id),
                "status": "accepted",
                "result": "accepted",
            },
            {
                "index": 1,
                "event_id": "00000000-0000-0000-0000-000000000000",
                "status": "accepted",
                "result": "accepted",
            },
            {
                "index": 2,
                "event_id": str(request.tasks[2].event_id),
                "status": "accepted",
                "result": [],
            },
            {
                "index": 3,
                "event_id": str(request.tasks[3].event_id),
                "status": "rejected",
                "result": "event_id_conflict",
            },
        ],
        status="partial",
    )

    decisions = _parse_successful_batch_response(request=request, data=data)

    assert [decision.state for decision in decisions] == [
        "retry",
        "retry",
        "retry",
        "blocked",
    ]
    assert decisions[3].text == "SAGUR отклонил элемент пакетного запроса."


def test_unhashable_batch_status_is_an_invalid_envelope() -> None:
    request = build_sagur_message_interaction_batch_request(
        (_task(),),
        request_id=_REQUEST_IDS[0],
        sent_at=_NOW,
    )
    data = _response(request, [])
    data["status"] = []

    decisions = _parse_successful_batch_response(request=request, data=data)

    assert decisions[0].state == "retry"
    assert decisions[0].code == "response_invalid"


def test_missing_response_object_retries_without_confirmation() -> None:
    request = build_sagur_message_interaction_batch_request(
        (_task(),),
        request_id=_REQUEST_IDS[0],
        sent_at=_NOW,
    )

    decisions = _parse_successful_batch_response(request=request, data=None)

    assert decisions[0].state == "retry"


def test_http_413_splits_batch_with_new_request_id_for_every_attempt() -> None:
    factory = _session_factory()
    _insert_events(factory, 4)
    client = _FakeHttpClient(
        deque(
            [
                SagurMessageInteractionHttpOutcome(http_status=413, error_code="body_too_large"),
                SagurMessageInteractionHttpOutcome(http_status=200, data={"dynamic": True}),
                SagurMessageInteractionHttpOutcome(http_status=200, data={"dynamic": True}),
            ]
        )
    )

    result = asyncio.run(_processor(factory, client).process_once())

    assert result == SagurMessageInteractionProcessingResult(
        selected=4,
        delivered=4,
        http_requests=3,
    )
    assert [len(request.tasks) for request in client.sent] == [4, 2, 2]
    assert len({request.request_id for request in client.sent}) == 3


def test_http_413_for_single_item_blocks_it_without_deletion() -> None:
    factory = _session_factory()
    event_id = _insert_events(factory, 1)[0]
    client = _FakeHttpClient(
        deque([SagurMessageInteractionHttpOutcome(http_status=413, error_code="body_too_large")])
    )

    result = asyncio.run(_processor(factory, client).process_once())

    assert result.blocked == 1
    with factory() as session:
        row = session.get(SagurMessageInteractionEventRow, event_id)
        assert row is not None
        assert row.delivery_status == "blocked"
        assert row.delivery_error_code == "body_too_large"


def test_local_body_limit_blocks_single_item_without_http_request() -> None:
    factory = _session_factory()
    event_id = _insert_events(factory, 1)[0]
    client = _FakeHttpClient(deque())

    result = asyncio.run(_processor(factory, client, max_body_bytes=10).process_once())

    assert result == SagurMessageInteractionProcessingResult(selected=1, blocked=1)
    assert client.sent == []
    with factory() as session:
        row = session.get(SagurMessageInteractionEventRow, event_id)
        assert row is not None and row.delivery_status == "blocked"


def test_body_limit_selects_largest_fitting_prefix() -> None:
    factory = _session_factory()
    event_ids = _insert_events(factory, 2)
    client = _FakeHttpClient(
        deque([SagurMessageInteractionHttpOutcome(http_status=200, data={"dynamic": True})])
    )
    one_item_size = len(
        build_sagur_message_interaction_batch_request(
            (_task(),),
            request_id=_REQUEST_IDS[0],
            sent_at=_NOW,
        ).body
    )

    result = asyncio.run(
        _processor(factory, client, max_body_bytes=one_item_size + 2).process_once()
    )

    assert result.selected == 1
    with factory() as session:
        first = session.get(SagurMessageInteractionEventRow, event_ids[0])
        second = session.get(SagurMessageInteractionEventRow, event_ids[1])
        assert first is not None and second is not None
        assert first.delivery_status == "delivered"
        assert second.delivery_status == "pending"


def test_request_pacing_waits_before_second_http_attempt() -> None:
    factory = _session_factory()
    _insert_events(factory, 2)
    client = _FakeHttpClient(
        deque(
            [
                SagurMessageInteractionHttpOutcome(http_status=413),
                SagurMessageInteractionHttpOutcome(http_status=200, data={"dynamic": True}),
                SagurMessageInteractionHttpOutcome(http_status=200, data={"dynamic": True}),
            ]
        )
    )
    clock = [0.0]
    sleeps: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    processor = _processor(
        factory,
        client,
        minimum_request_interval_seconds=1.0,
        monotonic_factory=lambda: clock[0],
        sleep=_sleep,
    )

    result = asyncio.run(processor.process_once())

    assert result.http_requests == 3
    assert sleeps == pytest.approx([1.0, 1.0])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"batch_size": 0},
        {"batch_size": 101},
        {"max_body_bytes": 0},
        {"retry_base_seconds": 0},
        {"retry_base_seconds": 10, "retry_max_seconds": 5},
        {"retry_jitter_ratio": -0.1},
        {"retry_jitter_ratio": 1.1},
        {"lock_timeout_seconds": 0},
        {"minimum_request_interval_seconds": -1},
    ],
)
def test_processor_rejects_invalid_configuration(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _processor(_session_factory(), _FakeHttpClient(deque()), **kwargs)


@dataclass(slots=True)
class _FakeProcessor:
    results: deque[SagurMessageInteractionProcessingResult]
    calls: int = 0
    observation: SagurMessageInteractionQueueObservation = field(
        default_factory=lambda: SagurMessageInteractionQueueObservation(
            active_count=0,
            oldest_occurred_at=None,
        )
    )
    observation_calls: int = 0

    async def process_once(self) -> SagurMessageInteractionProcessingResult:
        self.calls += 1
        return self.results.popleft()

    def read_queue_observation(self) -> SagurMessageInteractionQueueObservation:
        self.observation_calls += 1
        return self.observation


def test_periodic_worker_drains_due_batches_and_supports_shutdown() -> None:
    processor = _FakeProcessor(
        deque(
            [
                SagurMessageInteractionProcessingResult(selected=2, delivered=2),
                SagurMessageInteractionProcessingResult(selected=1, blocked=1),
                SagurMessageInteractionProcessingResult(),
            ]
        )
    )
    worker = PeriodicSagurMessageInteractionWorker(processor=processor, interval_seconds=1)  # type: ignore[arg-type]

    result = asyncio.run(worker.process_due_events())
    asyncio.run(worker.shutdown())

    assert result == SagurMessageInteractionProcessingResult(selected=3, delivered=2, blocked=1)
    assert processor.calls == 3
    assert processor.observation_calls == 1
    assert worker._stop_event.is_set()


def test_periodic_worker_reports_oldest_active_event_age() -> None:
    processor = _FakeProcessor(
        deque([SagurMessageInteractionProcessingResult()]),
        observation=SagurMessageInteractionQueueObservation(
            active_count=7,
            oldest_occurred_at=_NOW - timedelta(seconds=125),
        ),
    )
    worker = PeriodicSagurMessageInteractionWorker(  # type: ignore[arg-type]
        processor=processor,
        interval_seconds=1,
        now_factory=lambda: _NOW,
    )

    asyncio.run(worker.process_due_events())

    assert processor.observation_calls == 1
    assert _oldest_event_age_seconds(processor.observation, now=_NOW) == 125


def test_periodic_worker_contains_queue_observation_error() -> None:
    @dataclass(slots=True)
    class _ObservationFailingProcessor:
        async def process_once(self) -> SagurMessageInteractionProcessingResult:
            return SagurMessageInteractionProcessingResult()

        def read_queue_observation(self) -> SagurMessageInteractionQueueObservation:
            raise RuntimeError("observation failed")

    worker = PeriodicSagurMessageInteractionWorker(  # type: ignore[arg-type]
        processor=_ObservationFailingProcessor(),
        interval_seconds=1,
    )

    assert asyncio.run(worker.process_due_events()) == SagurMessageInteractionProcessingResult()


def test_oldest_event_age_is_none_for_empty_queue_and_zero_for_future_event() -> None:
    assert _oldest_event_age_seconds(None, now=_NOW) is None
    empty = SagurMessageInteractionQueueObservation(active_count=0, oldest_occurred_at=None)
    assert _oldest_event_age_seconds(empty, now=_NOW) is None
    future = SagurMessageInteractionQueueObservation(
        active_count=1,
        oldest_occurred_at=_NOW + timedelta(seconds=1),
    )
    assert _oldest_event_age_seconds(future, now=_NOW) == 0

    naive = SagurMessageInteractionQueueObservation(
        active_count=1,
        oldest_occurred_at=_NOW.replace(tzinfo=None),
    )
    with pytest.raises(ValueError, match="часовой пояс"):
        _oldest_event_age_seconds(naive, now=_NOW)


def test_periodic_worker_skips_overlapping_pass_and_validates_interval() -> None:
    processor = _FakeProcessor(deque([SagurMessageInteractionProcessingResult()]))
    lock = asyncio.Lock()
    worker = PeriodicSagurMessageInteractionWorker(  # type: ignore[arg-type]
        processor=processor,
        interval_seconds=1,
        lock=lock,
    )

    async def _run() -> SagurMessageInteractionProcessingResult:
        await lock.acquire()
        try:
            return await worker.process_due_events()
        finally:
            lock.release()

    assert asyncio.run(_run()) == SagurMessageInteractionProcessingResult()
    assert processor.calls == 0
    with pytest.raises(ValueError, match="больше нуля"):
        PeriodicSagurMessageInteractionWorker(processor=processor, interval_seconds=0)  # type: ignore[arg-type]


def test_periodic_worker_uses_unlocked_lock_and_contains_processor_error() -> None:
    @dataclass(slots=True)
    class _FailingProcessor:
        async def process_once(self) -> SagurMessageInteractionProcessingResult:
            raise RuntimeError("processor failed")

    worker = PeriodicSagurMessageInteractionWorker(  # type: ignore[arg-type]
        processor=_FailingProcessor(),
        interval_seconds=1,
        lock=asyncio.Lock(),
    )

    result = asyncio.run(worker.process_due_events())

    assert result == SagurMessageInteractionProcessingResult()


def test_periodic_worker_run_forever_stops_cleanly_and_handles_cancellation() -> None:
    async def _clean_stop() -> None:
        processor = _FakeProcessor(deque([SagurMessageInteractionProcessingResult()]))
        worker = PeriodicSagurMessageInteractionWorker(  # type: ignore[arg-type]
            processor=processor,
            interval_seconds=60,
        )
        task = asyncio.create_task(worker.run_forever())
        await asyncio.sleep(0)
        await worker.shutdown()
        await task

    async def _cancel() -> None:
        processor = _FakeProcessor(deque([SagurMessageInteractionProcessingResult()]))
        worker = PeriodicSagurMessageInteractionWorker(  # type: ignore[arg-type]
            processor=processor,
            interval_seconds=60,
        )
        task = asyncio.create_task(worker.run_forever())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_clean_stop())
    asyncio.run(_cancel())


def test_wait_for_next_tick_handles_timeout() -> None:
    worker = PeriodicSagurMessageInteractionWorker(  # type: ignore[arg-type]
        processor=_FakeProcessor(deque()),
        interval_seconds=0.001,
    )

    asyncio.run(worker._wait_for_next_tick())


def test_stopped_worker_does_not_call_processor() -> None:
    processor = _FakeProcessor(deque())
    worker = PeriodicSagurMessageInteractionWorker(  # type: ignore[arg-type]
        processor=processor,
        interval_seconds=1,
    )

    async def _run() -> SagurMessageInteractionProcessingResult:
        await worker.shutdown()
        return await worker._process_due_events_unlocked()

    assert asyncio.run(_run()) == SagurMessageInteractionProcessingResult()
    assert processor.calls == 0


@pytest.mark.parametrize(
    ("raw_body", "expected"),
    [
        (b'{"ok":true}', {"ok": True}),
        (b"[]", None),
        (b"not-json", None),
        (b"\xff", None),
    ],
)
def test_response_decoder_accepts_only_utf8_json_object(
    raw_body: bytes,
    expected: dict[str, object] | None,
) -> None:
    assert _decode_response_object(raw_body) == expected


def test_safe_text_helpers_normalize_untrusted_values() -> None:
    assert _optional_text(None) is None
    assert _optional_text("  ") is None
    assert _optional_text(" value ") == "value"
    assert len(_safe_error_text("x" * 3_000)) == 2_000


def test_retry_after_accepts_http_date_without_timezone() -> None:
    assert _parse_retry_after("Thu, 20 Aug 2026 10:01:00", now=_NOW) == 60
