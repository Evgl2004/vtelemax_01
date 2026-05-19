"""Unit tests for SAGUR integration API app bootstrap."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from aiohttp.test_utils import make_mocked_request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vtelemax.apps import sagur_integration_api_app as sagur_api
from vtelemax.apps.sagur_integration_api_app import (
    DeltaCursor,
    SnapshotCursor,
    _build_hmac_payload,
    _build_hmac_signature,
    _build_metrics_payload,
    _delta_handler,
    _decode_delta_cursor,
    _decode_snapshot_cursor,
    _encode_delta_cursor,
    _encode_snapshot_cursor,
    _hash_for_log,
    _is_sagur_protected_path,
    _parse_since_from_query,
    _parse_limit_from_query,
    _sign_cursor_payload,
    _validate_hmac_auth,
    _validate_service_settings,
    build_web_app,
)
from vtelemax.infrastructure.postgres import (
    Base,
    PersonRow,
    SQLAlchemySagurCouponsRepository,
    build_session_factory,
)
from vtelemax.infrastructure.postgres.sagur_coupons_repository import ApplyCouponEventResult
from vtelemax.infrastructure.postgres.sagur_recipients_repository import _build_delta_statement
from vtelemax.settings import AppSettings


def test_sagur_integration_api_module_is_importable() -> None:
    assert callable(build_web_app)


def test_sagur_integration_app_registers_required_routes() -> None:
    settings = AppSettings()
    app = build_web_app(settings=settings, session_factory=sessionmaker())

    route_paths = {route.resource.canonical for route in app.router.routes()}

    assert "/health" in route_paths
    assert "/metrics" in route_paths
    assert "/internal/integration/v1/sagur/recipients/snapshot" in route_paths
    assert "/internal/integration/v1/sagur/recipients/delta" in route_paths
    assert "/internal/integration/v1/sagur/coupons/events" in route_paths


def test_sagur_integration_settings_validation_rejects_bad_limits() -> None:
    settings = AppSettings(
        SAGUR_INTEGRATION_DEFAULT_LIMIT=5001,
        SAGUR_INTEGRATION_MAX_LIMIT=5000,
    )

    with pytest.raises(ValueError):
        _validate_service_settings(settings)


def test_snapshot_cursor_roundtrip() -> None:
    original = SnapshotCursor(
        account_created_at=datetime(2026, 5, 5, 10, 12, 30, tzinfo=timezone.utc),
        person_id="7c0bf8b8-0848-4434-a6d9-f2fe810dc5de",
        platform="telegram",
        limit=1000,
    )

    encoded = _encode_snapshot_cursor(original)
    decoded = _decode_snapshot_cursor(encoded)

    assert decoded == original


def test_snapshot_cursor_decode_rejects_invalid_payload() -> None:
    with pytest.raises(ValueError):
        _decode_snapshot_cursor("not-a-valid-cursor")


def test_delta_cursor_roundtrip() -> None:
    original = DeltaCursor(
        since=datetime(2026, 5, 5, 10, 0, 0, tzinfo=timezone.utc),
        effective_updated_at=datetime(2026, 5, 5, 10, 12, 30, tzinfo=timezone.utc),
        person_id="7c0bf8b8-0848-4434-a6d9-f2fe810dc5de",
        platform="vk",
        limit=1000,
    )

    encoded = _encode_delta_cursor(original)
    decoded = _decode_delta_cursor(encoded)

    assert decoded == original


def test_parse_since_from_query_parses_rfc3339_and_rejects_empty() -> None:
    request_ok = make_mocked_request(
        "GET",
        "/internal/integration/v1/sagur/recipients/delta?since=2026-05-05T10:00:00Z",
    )
    parsed = _parse_since_from_query(request_ok)
    assert parsed == datetime(2026, 5, 5, 10, 0, 0, tzinfo=timezone.utc)

    request_empty = make_mocked_request("GET", "/internal/integration/v1/sagur/recipients/delta")
    with pytest.raises(ValueError):
        _parse_since_from_query(request_empty)


def test_parse_limit_from_query_uses_default_and_rejects_overflow() -> None:
    settings = AppSettings(
        SAGUR_INTEGRATION_DEFAULT_LIMIT=1000,
        SAGUR_INTEGRATION_MAX_LIMIT=5000,
    )

    request_default = make_mocked_request("GET", "/internal/integration/v1/sagur/recipients/snapshot")
    assert _parse_limit_from_query(request=request_default, settings=settings) == 1000

    request_overflow = make_mocked_request(
        "GET",
        "/internal/integration/v1/sagur/recipients/snapshot?limit=5001",
    )
    with pytest.raises(ValueError):
        _parse_limit_from_query(request=request_overflow, settings=settings)


def test_hash_for_log_returns_none_for_empty_and_short_hash_for_value() -> None:
    assert _hash_for_log(None) is None
    assert _hash_for_log("") is None
    result = _hash_for_log("cursor-value")
    assert isinstance(result, str)
    assert len(result) == 12


def test_is_sagur_protected_path_detects_integration_routes() -> None:
    assert _is_sagur_protected_path("/internal/integration/v1/sagur/recipients/snapshot") is True
    assert _is_sagur_protected_path("/internal/integration/v1/sagur/recipients/delta") is True
    assert _is_sagur_protected_path("/health") is False


def test_validate_hmac_auth_accepts_valid_signature() -> None:
    settings = AppSettings(
        SAGUR_INTEGRATION_HMAC_SECRET="test-secret",
        SAGUR_INTEGRATION_HMAC_MAX_SKEW_SECONDS=60,
    )
    timestamp = 1_777_777_777
    path_qs = "/internal/integration/v1/sagur/recipients/snapshot?limit=1000"
    payload = _build_hmac_payload(method="GET", path_qs=path_qs, timestamp=timestamp)
    signature = _build_hmac_signature(secret="test-secret", payload=payload)

    request = make_mocked_request(
        "GET",
        path_qs,
        headers={
            "X-Sagur-Timestamp": str(timestamp),
            "X-Sagur-Signature": signature,
        },
    )

    auth_error = _validate_hmac_auth(request=request, settings=settings, now_epoch=timestamp)
    assert auth_error is None


def test_validate_hmac_auth_accepts_batch_body_hash_signature() -> None:
    settings = AppSettings(
        SAGUR_INTEGRATION_HMAC_SECRET="test-secret",
        SAGUR_INTEGRATION_HMAC_MAX_SKEW_SECONDS=60,
    )
    timestamp = 1_777_777_777
    path = "/internal/integration/v1/sagur/coupons/events"
    raw_body = b'{"request_id":"11111111-1111-4111-8111-111111111111","items":[]}'
    body_hash = hashlib.sha256(raw_body).hexdigest()
    payload = _build_hmac_payload(
        method="POST",
        path_qs=path,
        timestamp=timestamp,
        body_sha256=body_hash,
    )
    signature = _build_hmac_signature(secret="test-secret", payload=payload)

    request = make_mocked_request(
        "POST",
        path,
        headers={
            "X-Sagur-Timestamp": str(timestamp),
            "X-Sagur-Signature": signature,
        },
    )

    auth_error = _validate_hmac_auth(
        request=request,
        settings=settings,
        now_epoch=timestamp,
        raw_body=raw_body,
    )
    assert auth_error is None


def test_validate_hmac_auth_rejects_invalid_signature_or_stale_timestamp() -> None:
    settings = AppSettings(
        SAGUR_INTEGRATION_HMAC_SECRET="test-secret",
        SAGUR_INTEGRATION_HMAC_MAX_SKEW_SECONDS=60,
    )
    path_qs = "/internal/integration/v1/sagur/recipients/snapshot?limit=1000"
    request_bad_signature = make_mocked_request(
        "GET",
        path_qs,
        headers={
            "X-Sagur-Timestamp": "1777777777",
            "X-Sagur-Signature": "deadbeef",
        },
    )
    bad_signature_error = _validate_hmac_auth(
        request=request_bad_signature,
        settings=settings,
        now_epoch=1_777_777_777,
    )
    assert bad_signature_error is not None
    assert bad_signature_error.status == 401

    valid_payload = _build_hmac_payload(
        method="GET",
        path_qs=path_qs,
        timestamp=1_777_777_000,
    )
    valid_signature = _build_hmac_signature(secret="test-secret", payload=valid_payload)
    request_stale = make_mocked_request(
        "GET",
        path_qs,
        headers={
            "X-Sagur-Timestamp": "1777777000",
            "X-Sagur-Signature": valid_signature,
        },
    )
    stale_error = _validate_hmac_auth(
        request=request_stale,
        settings=settings,
        now_epoch=1_777_777_777,
    )
    assert stale_error is not None
    assert stale_error.status == 401


def test_delta_statement_uses_sqlalchemy_builder_without_raw_cast_syntax() -> None:
    statement = _build_delta_statement(
        since=datetime(2026, 5, 5, 10, 0, 0, tzinfo=timezone.utc),
        page_size=10,
    )
    compiled = str(statement.compile(compile_kwargs={"literal_binds": False}))

    assert ":since::timestamptz" not in compiled
    assert "WITH ranked_accounts AS" in compiled


def test_delta_statement_uses_lifecycle_policy_for_external_id_resolution() -> None:
    strict_statement = _build_delta_statement(
        since=datetime(2026, 5, 5, 10, 0, 0, tzinfo=timezone.utc),
        page_size=10,
        include_vk_pending_verification=False,
    )
    strict_compiled = str(strict_statement.compile(compile_kwargs={"literal_binds": True}))
    assert "lifecycle_status" in strict_compiled
    assert "lifecycle_status IN ('active', 'pending_verification')" not in strict_compiled

    transitional_statement = _build_delta_statement(
        since=datetime(2026, 5, 5, 10, 0, 0, tzinfo=timezone.utc),
        page_size=10,
        include_vk_pending_verification=True,
    )
    transitional_compiled = str(
        transitional_statement.compile(compile_kwargs={"literal_binds": True})
    )
    assert "lifecycle_status" in transitional_compiled
    assert "lifecycle_status IN ('active', 'pending_verification')" in transitional_compiled


@pytest.mark.asyncio
async def test_delta_handler_returns_empty_payload_without_cursor_or_max_seen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AppSettings()
    app = build_web_app(settings=settings, session_factory=sessionmaker())

    def _fake_fetch_delta_page(**_: object) -> tuple[list[dict[str, object]], None, None]:
        return [], None, None

    monkeypatch.setattr(sagur_api, "_fetch_delta_page", _fake_fetch_delta_page)

    request = make_mocked_request(
        "GET",
        "/internal/integration/v1/sagur/recipients/delta?since=2026-05-05T10:00:00Z",
        app=app,
    )
    response = await _delta_handler(request)
    body = json.loads(response.text)

    assert response.status == 200
    assert body["items"] == []
    assert body["next_cursor"] is None
    assert body["max_seen_updated_at"] is None


@pytest.mark.asyncio
async def test_delta_handler_rejects_damaged_cursor_with_400() -> None:
    settings = AppSettings(SAGUR_INTEGRATION_HMAC_SECRET="test-secret")
    app = build_web_app(settings=settings, session_factory=sessionmaker())

    request = make_mocked_request(
        "GET",
        "/internal/integration/v1/sagur/recipients/delta?since=2026-05-05T10:00:00Z&cursor=broken",
        app=app,
    )
    response = await _delta_handler(request)
    body = json.loads(response.text)

    assert response.status == 400
    assert body["status"] == "error"


@pytest.mark.asyncio
async def test_delta_handler_rejects_since_mismatch_between_query_and_cursor() -> None:
    settings = AppSettings(SAGUR_INTEGRATION_HMAC_SECRET="test-secret")
    app = build_web_app(settings=settings, session_factory=sessionmaker())

    encoded_payload = _encode_delta_cursor(
        DeltaCursor(
            since=datetime(2026, 5, 5, 10, 0, 0, tzinfo=timezone.utc),
            effective_updated_at=datetime(2026, 5, 5, 10, 1, 0, tzinfo=timezone.utc),
            person_id="00000000-0000-0000-0000-000000000001",
            platform="telegram",
            limit=1000,
        )
    )
    encoded_cursor = _sign_cursor_payload(encoded_payload=encoded_payload, secret="test-secret")
    request = make_mocked_request(
        "GET",
        (
            "/internal/integration/v1/sagur/recipients/delta"
            f"?since=2026-05-05T11:00:00Z&limit=1000&cursor={encoded_cursor}"
        ),
        app=app,
    )
    response = await _delta_handler(request)
    body = json.loads(response.text)

    assert response.status == 400
    assert body["status"] == "error"
    assert "since" in body["message"]


@pytest.mark.asyncio
async def test_delta_handler_rejects_tampered_signed_cursor_with_400() -> None:
    settings = AppSettings(SAGUR_INTEGRATION_HMAC_SECRET="test-secret")
    app = build_web_app(settings=settings, session_factory=sessionmaker())

    encoded_payload = _encode_delta_cursor(
        DeltaCursor(
            since=datetime(2026, 5, 5, 10, 0, 0, tzinfo=timezone.utc),
            effective_updated_at=datetime(2026, 5, 5, 10, 1, 0, tzinfo=timezone.utc),
            person_id="00000000-0000-0000-0000-000000000002",
            platform="vk",
            limit=1000,
        )
    )
    signed_cursor = _sign_cursor_payload(encoded_payload=encoded_payload, secret="test-secret")
    tampered_cursor = signed_cursor[:-1] + ("0" if signed_cursor[-1] != "0" else "1")

    request = make_mocked_request(
        "GET",
        (
            "/internal/integration/v1/sagur/recipients/delta"
            f"?since=2026-05-05T10:00:00Z&limit=1000&cursor={tampered_cursor}"
        ),
        app=app,
    )
    response = await _delta_handler(request)
    body = json.loads(response.text)

    assert response.status == 400
    assert body["status"] == "error"
    assert "cursor" in body["message"].lower()


@pytest.mark.asyncio
async def test_delta_handler_rejects_limit_mismatch_between_query_and_cursor() -> None:
    settings = AppSettings(SAGUR_INTEGRATION_HMAC_SECRET="test-secret")
    app = build_web_app(settings=settings, session_factory=sessionmaker())

    encoded_payload = _encode_delta_cursor(
        DeltaCursor(
            since=datetime(2026, 5, 5, 10, 0, 0, tzinfo=timezone.utc),
            effective_updated_at=datetime(2026, 5, 5, 10, 1, 0, tzinfo=timezone.utc),
            person_id="00000000-0000-0000-0000-000000000003",
            platform="max",
            limit=1000,
        )
    )
    encoded_cursor = _sign_cursor_payload(encoded_payload=encoded_payload, secret="test-secret")

    request = make_mocked_request(
        "GET",
        (
            "/internal/integration/v1/sagur/recipients/delta"
            f"?since=2026-05-05T10:00:00Z&limit=999&cursor={encoded_cursor}"
        ),
        app=app,
    )
    response = await _delta_handler(request)
    body = json.loads(response.text)

    assert response.status == 400
    assert body["status"] == "error"
    assert "limit" in body["message"].lower()


def test_metrics_payload_contains_required_counters() -> None:
    payload = _build_metrics_payload(
        {
            "requests_total": 10.0,
            "request_latency_seconds_sum": 1.5,
            "request_latency_seconds_count": 3.0,
            "rows_returned_total": 25.0,
            "auth_failures_total": 2.0,
            "coupon_events_total": 8.0,
            "coupon_events_success_total": 7.0,
            "coupon_events_error_total": 1.0,
            "coupon_events_dedup_total": 3.0,
            "coupon_event_latency_seconds_sum": 0.5,
            "coupon_event_latency_seconds_count": 8.0,
        }
    )

    assert "sagur_integration_requests_total 10" in payload
    assert "sagur_integration_rows_returned_total 25" in payload
    assert "sagur_integration_auth_failures_total 2" in payload
    assert "sagur_coupon_events_total 8" in payload
    assert "sagur_coupon_events_success_total 7" in payload
    assert "sagur_coupon_events_error_total 1" in payload
    assert "sagur_coupon_events_dedup_total 3" in payload


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    def commit(self) -> None:
        self.committed = True


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> "_FakeSessionFactory":
        return self

    def __enter__(self) -> _FakeSession:
        return self._session

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> bool:
        return False


@pytest.mark.asyncio
async def test_coupons_events_handler_rejects_missing_event_id_header() -> None:
    settings = AppSettings()
    app = build_web_app(settings=settings, session_factory=sessionmaker())
    request = make_mocked_request(
        "POST",
        "/internal/integration/v1/sagur/coupons/events",
        app=app,
    )

    response = await sagur_api._coupons_events_handler(request)
    body = json.loads(response.text)

    assert response.status == 400
    assert body["status"] == "error"


@pytest.mark.asyncio
async def test_coupons_events_handler_accepts_event_and_returns_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AppSettings()
    app = build_web_app(settings=settings, session_factory=sessionmaker())
    fake_session = _FakeSession()
    app[sagur_api._SESSION_FACTORY_KEY] = _FakeSessionFactory(fake_session)

    event_id = uuid4()
    expected_event_id = str(event_id)

    async def _fake_read_json_object_body(_: object) -> dict[str, object]:
        return {
            "event_id": str(event_id),
            "direction": "assignments",
            "sent_at": "2026-05-15T08:00:00Z",
            "payload": {
                "person_id": "11111111-1111-1111-1111-111111111111",
                "coupon_series": "A",
                "coupon_code": "CPN-001",
                "status": "reserved",
            },
        }

    class _FakeCouponsRepository:
        def __init__(self, _: object) -> None:
            pass

        def apply_event(
            self,
            *,
            event_id: object,
            direction: str,
            sent_at: object,
            payload_raw: dict[str, object],
        ) -> ApplyCouponEventResult:
            assert str(event_id) == expected_event_id
            assert direction == "assignments"
            assert sent_at is not None
            assert payload_raw["coupon_code"] == "CPN-001"
            return ApplyCouponEventResult(deduplicated=False, coupon_id=uuid4())

    monkeypatch.setattr(sagur_api, "_read_json_object_body", _fake_read_json_object_body)
    monkeypatch.setattr(sagur_api, "SQLAlchemySagurCouponsRepository", _FakeCouponsRepository)

    request = make_mocked_request(
        "POST",
        "/internal/integration/v1/sagur/coupons/events",
        headers={"X-Sagur-Event-Id": str(event_id)},
        app=app,
    )
    request[sagur_api._REQUEST_ID_KEY] = "test-request-id"

    response = await sagur_api._coupons_events_handler(request)
    body = json.loads(response.text)

    assert response.status == 200
    assert body == {"ok": True}
    assert fake_session.committed is True


@pytest.mark.asyncio
async def test_coupons_events_handler_idempotent_duplicate_returns_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AppSettings()
    app = build_web_app(settings=settings, session_factory=sessionmaker())
    fake_session = _FakeSession()
    app[sagur_api._SESSION_FACTORY_KEY] = _FakeSessionFactory(fake_session)

    event_id = uuid4()

    async def _fake_read_json_object_body(_: object) -> dict[str, object]:
        return {
            "event_id": str(event_id),
            "direction": "status_update",
            "payload": {
                "person_id": "22222222-2222-2222-2222-222222222222",
                "coupon_series": "B",
                "coupon_code": "CPN-002",
                "status": "used",
            },
        }

    class _FakeCouponsRepository:
        def __init__(self, _: object) -> None:
            pass

        def apply_event(
            self,
            *,
            event_id: object,
            direction: str,
            sent_at: object,
            payload_raw: dict[str, object],
        ) -> ApplyCouponEventResult:
            assert direction == "status_update"
            assert sent_at is None
            assert payload_raw["status"] == "used"
            return ApplyCouponEventResult(deduplicated=True, coupon_id=None)

    monkeypatch.setattr(sagur_api, "_read_json_object_body", _fake_read_json_object_body)
    monkeypatch.setattr(sagur_api, "SQLAlchemySagurCouponsRepository", _FakeCouponsRepository)

    request = make_mocked_request(
        "POST",
        "/internal/integration/v1/sagur/coupons/events",
        headers={"X-Sagur-Event-Id": str(event_id)},
        app=app,
    )
    request[sagur_api._REQUEST_ID_KEY] = "test-request-id-2"

    response = await sagur_api._coupons_events_handler(request)
    body = json.loads(response.text)

    assert response.status == 200
    assert body == {"ok": True}
    assert fake_session.committed is True


@pytest.mark.asyncio
async def test_coupons_events_handler_accepts_batch_and_returns_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_person_id = uuid4()
    second_person_id = uuid4()
    app, session_factory = _build_coupon_batch_test_app(first_person_id, second_person_id)
    request_id = str(uuid4())
    first_event_id = str(uuid4())
    second_event_id = str(uuid4())

    response = await _call_coupons_batch_handler(
        monkeypatch=monkeypatch,
        app=app,
        body={
            "request_id": request_id,
            "direction": "assignments",
            "sent_at": "2026-05-15T10:00:00Z",
            "items": [
                _coupon_batch_item(
                    event_id=first_event_id,
                    person_id=first_person_id,
                    coupon_code="BATCH-0001",
                ),
                _coupon_batch_item(
                    event_id=second_event_id,
                    person_id=second_person_id,
                    coupon_code="BATCH-0002",
                ),
            ],
        },
    )
    body = json.loads(response.text)

    assert response.status == 200
    assert body["request_id"] == request_id
    assert body["status"] == "acked"
    assert body["results"] == [
        {"event_id": first_event_id, "status": "acked"},
        {"event_id": second_event_id, "status": "acked"},
    ]

    with session_factory() as session:
        repository = SQLAlchemySagurCouponsRepository(session)
        first_coupons = repository.list_visible_coupons(
            person_id=first_person_id,
            venue_code="nani",
        )
        second_coupons = repository.list_visible_coupons(
            person_id=second_person_id,
            venue_code="nani",
        )

    assert [coupon.coupon_code for coupon in first_coupons] == ["BATCH-0001"]
    assert [coupon.coupon_code for coupon in second_coupons] == ["BATCH-0002"]
    assert _as_aware_utc(first_coupons[0].valid_until) == datetime(
        2026,
        5,
        18,
        18,
        59,
        59,
        tzinfo=timezone.utc,
    )


@pytest.mark.asyncio
async def test_coupons_events_handler_returns_partial_batch_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    known_person_id = uuid4()
    missing_person_id = uuid4()
    app, session_factory = _build_coupon_batch_test_app(known_person_id)
    request_id = str(uuid4())
    known_event_id = str(uuid4())
    missing_event_id = str(uuid4())

    response = await _call_coupons_batch_handler(
        monkeypatch=monkeypatch,
        app=app,
        body={
            "request_id": request_id,
            "direction": "assignments",
            "sent_at": "2026-05-15T10:00:00Z",
            "items": [
                _coupon_batch_item(
                    event_id=known_event_id,
                    person_id=known_person_id,
                    coupon_code="BATCH-OK",
                ),
                _coupon_batch_item(
                    event_id=missing_event_id,
                    person_id=missing_person_id,
                    coupon_code="BATCH-MISSING",
                ),
            ],
        },
    )
    body = json.loads(response.text)

    assert response.status == 200
    assert body["status"] == "partial"
    assert body["results"][0] == {"event_id": known_event_id, "status": "acked"}
    assert body["results"][1]["event_id"] == missing_event_id
    assert body["results"][1]["status"] == "rejected"
    assert body["results"][1]["code"] == "recipient_not_found"

    with session_factory() as session:
        repository = SQLAlchemySagurCouponsRepository(session)
        coupons = repository.list_visible_coupons(person_id=known_person_id, venue_code="nani")

    assert [coupon.coupon_code for coupon in coupons] == ["BATCH-OK"]


@pytest.mark.asyncio
async def test_coupons_events_handler_keeps_item_level_idempotency_for_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    person_id = uuid4()
    app, session_factory = _build_coupon_batch_test_app(person_id)
    item_event_id = str(uuid4())
    batch_body = {
        "request_id": str(uuid4()),
        "direction": "assignments",
        "sent_at": "2026-05-15T10:00:00Z",
        "items": [
            _coupon_batch_item(
                event_id=item_event_id,
                person_id=person_id,
                coupon_code="BATCH-RETRY",
            )
        ],
    }

    first_response = await _call_coupons_batch_handler(
        monkeypatch=monkeypatch,
        app=app,
        body=batch_body,
    )
    retry_response = await _call_coupons_batch_handler(
        monkeypatch=monkeypatch,
        app=app,
        body={**batch_body, "request_id": str(uuid4())},
    )
    first_body = json.loads(first_response.text)
    retry_body = json.loads(retry_response.text)

    assert first_body["results"] == [{"event_id": item_event_id, "status": "acked"}]
    assert retry_body["results"] == [
        {"event_id": item_event_id, "status": "acked", "deduplicated": True}
    ]

    with session_factory() as session:
        repository = SQLAlchemySagurCouponsRepository(session)
        coupons = repository.list_visible_coupons(person_id=person_id, venue_code="nani")

    assert [coupon.coupon_code for coupon in coupons] == ["BATCH-RETRY"]


@pytest.mark.asyncio
async def test_coupons_events_handler_rejects_reassign_of_used_coupon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_person_id = uuid4()
    second_person_id = uuid4()
    app, _ = _build_coupon_batch_test_app(first_person_id, second_person_id)
    coupon_code = "BATCH-USED"

    await _call_coupons_batch_handler(
        monkeypatch=monkeypatch,
        app=app,
        body={
            "request_id": str(uuid4()),
            "direction": "assignments",
            "sent_at": "2026-05-15T10:00:00Z",
            "items": [
                _coupon_batch_item(
                    event_id=str(uuid4()),
                    person_id=first_person_id,
                    coupon_code=coupon_code,
                )
            ],
        },
    )
    await _call_coupons_batch_handler(
        monkeypatch=monkeypatch,
        app=app,
        body={
            "request_id": str(uuid4()),
            "direction": "status_update",
            "sent_at": "2026-05-15T10:05:00Z",
            "items": [
                _coupon_batch_item(
                    event_id=str(uuid4()),
                    person_id=first_person_id,
                    coupon_code=coupon_code,
                    status="used",
                    venue_code=None,
                )
            ],
        },
    )
    reassign_response = await _call_coupons_batch_handler(
        monkeypatch=monkeypatch,
        app=app,
        body={
            "request_id": str(uuid4()),
            "direction": "assignments",
            "sent_at": "2026-05-15T10:06:00Z",
            "items": [
                _coupon_batch_item(
                    event_id=str(uuid4()),
                    person_id=second_person_id,
                    coupon_code=coupon_code,
                )
            ],
        },
    )
    body = json.loads(reassign_response.text)

    assert reassign_response.status == 200
    assert body["status"] == "partial"
    assert body["results"][0]["status"] == "rejected"
    assert body["results"][0]["code"] == "coupon_already_assigned"


@pytest.mark.asyncio
async def test_coupons_events_handler_accepts_used_after_campaign_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_person_id = uuid4()
    second_person_id = uuid4()
    app, session_factory = _build_coupon_batch_test_app(first_person_id, second_person_id)
    coupon_code = "BATCH-LATE-USED"
    late_event_id = str(uuid4())

    await _call_coupons_batch_handler(
        monkeypatch=monkeypatch,
        app=app,
        body={
            "request_id": str(uuid4()),
            "direction": "assignments",
            "sent_at": "2026-05-15T10:00:00Z",
            "items": [
                _coupon_batch_item(
                    event_id=str(uuid4()),
                    person_id=first_person_id,
                    coupon_code=coupon_code,
                )
            ],
        },
    )
    await _call_coupons_batch_handler(
        monkeypatch=monkeypatch,
        app=app,
        body={
            "request_id": str(uuid4()),
            "direction": "status_update",
            "sent_at": "2026-05-15T10:05:00Z",
            "items": [
                _coupon_batch_item(
                    event_id=str(uuid4()),
                    person_id=first_person_id,
                    coupon_code=coupon_code,
                    status="expired",
                    venue_code=None,
                )
            ],
        },
    )
    late_response = await _call_coupons_batch_handler(
        monkeypatch=monkeypatch,
        app=app,
        body={
            "request_id": str(uuid4()),
            "direction": "status_update",
            "sent_at": "2026-05-15T10:10:00Z",
            "items": [
                _coupon_batch_item(
                    event_id=late_event_id,
                    person_id=first_person_id,
                    coupon_code=coupon_code,
                    status="used_after_campaign",
                    venue_code=None,
                    meta={
                        "remove_from_guest": True,
                        "release_to_pool": False,
                        "used_after_campaign": True,
                    },
                )
            ],
        },
    )
    reassign_response = await _call_coupons_batch_handler(
        monkeypatch=monkeypatch,
        app=app,
        body={
            "request_id": str(uuid4()),
            "direction": "assignments",
            "sent_at": "2026-05-15T10:11:00Z",
            "items": [
                _coupon_batch_item(
                    event_id=str(uuid4()),
                    person_id=second_person_id,
                    coupon_code=coupon_code,
                )
            ],
        },
    )
    late_body = json.loads(late_response.text)
    reassign_body = json.loads(reassign_response.text)

    assert late_response.status == 200
    assert late_body["status"] == "acked"
    assert late_body["results"] == [{"event_id": late_event_id, "status": "acked"}]
    assert reassign_body["status"] == "partial"
    assert reassign_body["results"][0]["code"] == "coupon_already_assigned"

    with session_factory() as session:
        repository = SQLAlchemySagurCouponsRepository(session)
        first_coupons = repository.list_visible_coupons(person_id=first_person_id, venue_code="nani")

    assert first_coupons == ()


@pytest.mark.asyncio
async def test_coupons_events_handler_supports_canceled_release_reassign_batch_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_person_id = uuid4()
    second_person_id = uuid4()
    app, session_factory = _build_coupon_batch_test_app(first_person_id, second_person_id)
    coupon_code = "BATCH-REUSE"

    assign_response = await _call_coupons_batch_handler(
        monkeypatch=monkeypatch,
        app=app,
        body={
            "request_id": str(uuid4()),
            "direction": "assignments",
            "sent_at": "2026-05-15T10:00:00Z",
            "items": [
                _coupon_batch_item(
                    event_id=str(uuid4()),
                    person_id=first_person_id,
                    coupon_code=coupon_code,
                )
            ],
        },
    )
    cancel_response = await _call_coupons_batch_handler(
        monkeypatch=monkeypatch,
        app=app,
        body={
            "request_id": str(uuid4()),
            "direction": "status_update",
            "sent_at": "2026-05-15T10:05:00Z",
            "items": [
                _coupon_batch_item(
                    event_id=str(uuid4()),
                    person_id=first_person_id,
                    coupon_code=coupon_code,
                    status="canceled",
                    venue_code=None,
                    meta={"release_to_pool": True, "remove_from_guest": True},
                )
            ],
        },
    )
    reassign_response = await _call_coupons_batch_handler(
        monkeypatch=monkeypatch,
        app=app,
        body={
            "request_id": str(uuid4()),
            "direction": "assignments",
            "sent_at": "2026-05-15T10:06:00Z",
            "items": [
                _coupon_batch_item(
                    event_id=str(uuid4()),
                    person_id=second_person_id,
                    coupon_code=coupon_code,
                )
            ],
        },
    )

    assert json.loads(assign_response.text)["status"] == "acked"
    assert json.loads(cancel_response.text)["status"] == "acked"
    assert json.loads(reassign_response.text)["status"] == "acked"

    with session_factory() as session:
        repository = SQLAlchemySagurCouponsRepository(session)
        first_coupons = repository.list_visible_coupons(person_id=first_person_id, venue_code="nani")
        second_coupons = repository.list_visible_coupons(
            person_id=second_person_id,
            venue_code="nani",
        )

    assert first_coupons == ()
    assert [coupon.coupon_code for coupon in second_coupons] == [coupon_code]


def _build_coupon_batch_test_app(*person_ids: object) -> tuple[object, sessionmaker]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    with session_factory() as session:
        session.add_all(PersonRow(person_id=person_id) for person_id in person_ids)
        session.commit()
    app = build_web_app(settings=AppSettings(), session_factory=session_factory)
    return app, session_factory


async def _call_coupons_batch_handler(
    *,
    monkeypatch: pytest.MonkeyPatch,
    app: object,
    body: dict[str, object],
) -> object:
    async def _fake_read_json_object_body(_: object) -> dict[str, object]:
        return body

    monkeypatch.setattr(sagur_api, "_read_json_object_body", _fake_read_json_object_body)
    request = make_mocked_request(
        "POST",
        "/internal/integration/v1/sagur/coupons/events",
        headers={"X-Sagur-Request-Id": str(body["request_id"])},
        app=app,
    )
    request[sagur_api._REQUEST_ID_KEY] = str(body["request_id"])
    return await sagur_api._coupons_events_handler(request)


def _coupon_batch_item(
    *,
    event_id: str,
    person_id: object,
    coupon_code: str,
    status: str = "reserved",
    venue_code: str | None = "nani",
    valid_until: str | None = "2026-05-18T23:59:59+05:00",
    meta: dict[str, object] | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {
        "event_id": event_id,
        "campaign_id": "CMP-BATCH",
        "assignment_id": f"ASN-{coupon_code}",
        "person_id": str(person_id),
        "phone_e164": "+79990000001",
        "coupon_series": "SER-BATCH",
        "coupon_code": coupon_code,
        "venue_name": "Nani",
        "promo_text": "Batch coupon",
        "status": status,
    }
    if venue_code is not None:
        item["venue_code"] = venue_code
    if valid_until is not None and status in {"reserved", "sent"}:
        item["valid_until"] = valid_until
    if meta is not None:
        item["meta"] = meta
    return item


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
