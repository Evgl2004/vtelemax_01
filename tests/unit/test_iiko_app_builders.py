"""Регрессионные тесты сборки шлюза iiko во всех процессах."""

from __future__ import annotations

from importlib import import_module

import pytest

from vtelemax.settings import AppSettings


IIKO_APP_MODULES = (
    "vtelemax.apps.telegram_app",
    "vtelemax.apps.vk_app",
    "vtelemax.apps.max_app",
    "vtelemax.apps.profile_sync_worker_app",
    "vtelemax.apps.sagur_registration_events_worker_app",
)


@pytest.mark.parametrize("module_name", IIKO_APP_MODULES)
def test_iiko_builder_passes_v2_configuration(
    module_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Проверяет передачу нового набора во все точки сборки."""

    app_module = import_module(module_name)
    captured: dict[str, object] = {}
    gateway_marker = object()

    def fake_gateway(**kwargs: object) -> object:
        captured.update(kwargs)
        return gateway_marker

    monkeypatch.setattr(app_module, "IikoLoyaltyGateway", fake_gateway)
    settings = AppSettings(
        IIKO_AUTH_VERSION="v2",
        IIKO_APP_ID="app-id",
        IIKO_CLIENT_SECRET="client-secret",
        IIKO_CLOUD_API_KEY="cloud-key",
        IIKO_ORG_ID="org-1",
        IIKO_AUTH_URL="https://example.test/api/v2/access_token",
        IIKO_BASE_URL="https://example.test/api/1",
    )

    result = app_module.build_iiko_gateway(settings)

    assert result is gateway_marker
    assert captured == {
        "organization_id": "org-1",
        "api_key": "",
        "auth_version": "v2",
        "app_id": "app-id",
        "client_secret": "client-secret",
        "cloud_api_key": "cloud-key",
        "auth_url": "https://example.test/api/v2/access_token",
        "base_url": "https://example.test/api/1",
    }


@pytest.mark.parametrize("module_name", IIKO_APP_MODULES)
def test_iiko_builder_returns_none_for_incomplete_v2_configuration(module_name: str) -> None:
    """Проверяет запуск процессов без шлюза при неполном наборе v2."""

    app_module = import_module(module_name)
    settings = AppSettings(
        IIKO_AUTH_VERSION="v2",
        IIKO_APP_ID="app-id",
        IIKO_CLIENT_SECRET="client-secret",
        IIKO_CLOUD_API_KEY="",
        IIKO_ORG_ID="org-1",
    )

    assert app_module.build_iiko_gateway(settings) is None
