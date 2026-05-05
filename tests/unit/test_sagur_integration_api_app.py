"""Unit tests for SAGUR integration API app bootstrap."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from aiohttp.test_utils import make_mocked_request
from sqlalchemy.orm import sessionmaker

from vtelemax.apps.sagur_integration_api_app import (
    DeltaCursor,
    SnapshotCursor,
    _decode_delta_cursor,
    _decode_snapshot_cursor,
    _encode_delta_cursor,
    _encode_snapshot_cursor,
    _parse_since_from_query,
    _parse_limit_from_query,
    _validate_service_settings,
    build_web_app,
)
from vtelemax.settings import AppSettings


def test_sagur_integration_api_module_is_importable() -> None:
    assert callable(build_web_app)


def test_sagur_integration_app_registers_required_routes() -> None:
    settings = AppSettings()
    app = build_web_app(settings=settings, session_factory=sessionmaker())

    route_paths = {route.resource.canonical for route in app.router.routes()}

    assert "/health" in route_paths
    assert "/internal/integration/v1/sagur/recipients/snapshot" in route_paths
    assert "/internal/integration/v1/sagur/recipients/delta" in route_paths


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
