"""Тесты переключаемой авторизации клиента iiko Cloud API."""

from __future__ import annotations

import pytest

from vtelemax.core.loyalty_ports import LoyaltyGatewayError
from vtelemax.infrastructure.iiko_client import IikoLoyaltyGateway


def test_iiko_v1_uses_legacy_request_and_existing_cache() -> None:
    """Проверяет неизменный запрос v1 и повторное использование маркера."""

    gateway = IikoLoyaltyGateway(api_key="legacy-login", organization_id="org-1")
    calls: list[dict[str, object]] = []

    def fake_post_json(
        *,
        path: str,
        payload: dict[str, object],
        token: str | None,
        request_url: str | None = None,
    ) -> tuple[int, dict[str, object], str]:
        calls.append(
            {
                "path": path,
                "payload": payload,
                "token": token,
                "request_url": request_url,
            }
        )
        return 200, {"token": "legacy-token"}, '{"token":"legacy-token"}'

    gateway._post_json = fake_post_json  # noqa: SLF001 - изолируем HTTP-транспорт

    assert gateway._get_access_token() == "legacy-token"  # noqa: SLF001
    assert gateway._get_access_token() == "legacy-token"  # noqa: SLF001
    assert calls == [
        {
            "path": "/access_token",
            "payload": {"apiLogin": "legacy-login"},
            "token": None,
            "request_url": None,
        }
    ]


def test_iiko_v2_uses_new_url_payload_and_existing_cache() -> None:
    """Проверяет адрес, тело запроса v2 и повторное использование маркера."""

    gateway = IikoLoyaltyGateway(
        organization_id="org-1",
        auth_version="v2",
        app_id="app-id",
        client_secret="client-secret",
        cloud_api_key="cloud-key",
        auth_url="https://example.test/api/v2/access_token",
    )
    calls: list[dict[str, object]] = []

    def fake_post_json(
        *,
        path: str,
        payload: dict[str, object],
        token: str | None,
        request_url: str | None = None,
    ) -> tuple[int, dict[str, object], str]:
        calls.append(
            {
                "path": path,
                "payload": payload,
                "token": token,
                "request_url": request_url,
            }
        )
        return 200, {"token": "v2-token"}, '{"token":"v2-token"}'

    gateway._post_json = fake_post_json  # noqa: SLF001 - изолируем HTTP-транспорт

    assert gateway._get_access_token() == "v2-token"  # noqa: SLF001
    assert gateway._get_access_token() == "v2-token"  # noqa: SLF001
    assert calls == [
        {
            "path": "/api/v2/access_token",
            "payload": {
                "appId": "app-id",
                "clientSecret": "client-secret",
                "apiKey": "cloud-key",
            },
            "token": None,
            "request_url": "https://example.test/api/v2/access_token",
        }
    ]


def test_iiko_v2_error_does_not_fall_back_to_v1() -> None:
    """Проверяет отсутствие автоматического возврата к старой авторизации."""

    gateway = IikoLoyaltyGateway(
        organization_id="org-1",
        api_key="legacy-login",
        auth_version="v2",
        app_id="app-id",
        client_secret="client-secret",
        cloud_api_key="cloud-key",
    )
    requested_paths: list[str] = []

    def fake_post_json(
        *,
        path: str,
        payload: dict[str, object],
        token: str | None,
        request_url: str | None = None,
    ) -> tuple[int, dict[str, object], str]:
        del payload, token, request_url
        requested_paths.append(path)
        return 401, {}, '{"error":"unauthorized"}'

    gateway._post_json = fake_post_json  # noqa: SLF001 - изолируем HTTP-транспорт

    with pytest.raises(LoyaltyGatewayError) as error_info:
        gateway._get_access_token()  # noqa: SLF001

    assert error_info.value.endpoint == "/api/v2/access_token"
    assert requested_paths == ["/api/v2/access_token"]


@pytest.mark.parametrize(
    ("missing_parameter", "expected_name"),
    [
        ("app_id", "IIKO_APP_ID"),
        ("client_secret", "IIKO_CLIENT_SECRET"),
        ("cloud_api_key", "IIKO_CLOUD_API_KEY"),
        ("auth_url", "IIKO_AUTH_URL"),
    ],
)
def test_iiko_v2_constructor_rejects_missing_selected_parameter(
    missing_parameter: str,
    expected_name: str,
) -> None:
    """Проверяет внутренний контракт клиента после успешной сборки настроек."""

    values = {
        "organization_id": "org-1",
        "auth_version": "v2",
        "app_id": "app-id",
        "client_secret": "client-secret",
        "cloud_api_key": "cloud-key",
        "auth_url": "https://example.test/api/v2/access_token",
    }
    values[missing_parameter] = " "

    with pytest.raises(ValueError, match=expected_name):
        IikoLoyaltyGateway(**values)
