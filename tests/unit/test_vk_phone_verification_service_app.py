"""Unit-тесты VK Mini App verification service."""

from __future__ import annotations

import json

import pytest
from aiohttp.test_utils import make_mocked_request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vtelemax.apps.vk_phone_verification_service_app import (
    _H_REQUEST_ID,
    _health_handler,
    _readiness_handler,
    _request_audit_middleware,
    _session_status_handler,
    build_web_app,
)
from vtelemax.settings import AppSettings


def _build_ready_settings() -> AppSettings:
    """Возвращает безопасные тестовые настройки для readiness-проверок."""

    return AppSettings(
        VK_PHONE_VERIFICATION_SERVICE_ENABLED=True,
        VK_PHONE_VERIFICATION_LINK_SECRET="test-link-secret",
        VK_PHONE_VERIFICATION_API_TOKEN="test-api-token",
    )


def _build_sqlite_session_factory() -> sessionmaker:
    """Создает легкую session factory с SQLite для проверки `SELECT 1`."""

    engine = create_engine("sqlite:///:memory:")
    return sessionmaker(bind=engine)


def test_vk_phone_verification_service_module_is_importable() -> None:
    """Проверяет, что модуль сервиса загружается без синтаксических ошибок."""

    assert callable(build_web_app)


def test_vk_phone_verification_app_registers_diagnostic_routes() -> None:
    """Проверяет наличие служебных endpoint'ов диагностики."""

    app = build_web_app(settings=_build_ready_settings(), session_factory=_build_sqlite_session_factory())

    route_paths = {route.resource.canonical for route in app.router.routes()}

    assert "/health" in route_paths
    assert "/ready" in route_paths
    assert "/vk/miniapp" in route_paths
    assert "/api/v1/vk/miniapp/session/status" in route_paths


@pytest.mark.asyncio
async def test_health_handler_returns_process_health() -> None:
    """Проверяет легкий healthcheck без обращения к БД."""

    app = build_web_app(settings=AppSettings(), session_factory=_build_sqlite_session_factory())
    request = make_mocked_request("GET", "/health", app=app)

    response = await _health_handler(request)
    body = json.loads(response.text)

    assert response.status == 200
    assert body == {"status": "ok", "service": "vk-phone-verification"}


@pytest.mark.asyncio
async def test_request_audit_middleware_propagates_request_id() -> None:
    """Проверяет, что request_id из заголовка возвращается в ответе."""

    app = build_web_app(settings=AppSettings(), session_factory=_build_sqlite_session_factory())
    request = make_mocked_request(
        "GET",
        "/health",
        headers={_H_REQUEST_ID: "test-request-id"},
        app=app,
    )

    response = await _request_audit_middleware(request, _health_handler)

    assert response.status == 200
    assert response.headers[_H_REQUEST_ID] == "test-request-id"


@pytest.mark.asyncio
async def test_readiness_handler_checks_config_and_database() -> None:
    """Проверяет successful readiness при включенном сервисе, секретах и доступной БД."""

    app = build_web_app(settings=_build_ready_settings(), session_factory=_build_sqlite_session_factory())
    request = make_mocked_request("GET", "/ready", app=app)

    response = await _readiness_handler(request)
    body = json.loads(response.text)

    assert response.status == 200
    assert body["status"] == "ok"
    assert body["checks"] == {
        "service_enabled": "ok",
        "link_secret": "ok",
        "api_token": "ok",
        "database": "ok",
    }


@pytest.mark.asyncio
async def test_readiness_handler_reports_not_ready_for_missing_config() -> None:
    """Проверяет, что readiness не маскирует выключенный сервис и пустые секреты."""

    app = build_web_app(settings=AppSettings(), session_factory=_build_sqlite_session_factory())
    request = make_mocked_request("GET", "/ready", app=app)

    response = await _readiness_handler(request)
    body = json.loads(response.text)

    assert response.status == 503
    assert body["status"] == "not_ready"
    assert body["checks"]["service_enabled"] == "disabled"
    assert body["checks"]["link_secret"] == "missing"
    assert body["checks"]["api_token"] == "missing"
    assert body["checks"]["database"] == "ok"


@pytest.mark.asyncio
async def test_status_handler_requires_bearer_token_and_request_id_header() -> None:
    """Проверяет, что status endpoint без Bearer-токена отклоняется и трассируется."""

    app = build_web_app(settings=_build_ready_settings(), session_factory=_build_sqlite_session_factory())
    request = make_mocked_request(
        "GET",
        "/api/v1/vk/miniapp/session/status?vk_user_id=1001",
        headers={_H_REQUEST_ID: "status-check-1"},
        app=app,
    )

    response = await _request_audit_middleware(request, _session_status_handler)
    body = json.loads(response.text)

    assert response.status == 401
    assert response.headers[_H_REQUEST_ID] == "status-check-1"
    assert body == {"status": "error", "message": "unauthorized"}
