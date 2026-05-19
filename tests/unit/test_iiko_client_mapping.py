"""Тесты маппинга полей iiko в доменную модель LoyaltyCustomer."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from vtelemax.core.loyalty_ports import LoyaltyCustomerUpsertData, LoyaltyGatewayError
from vtelemax.infrastructure.iiko_client import IikoLoyaltyGateway


def test_extract_customer_maps_extended_profile_fields() -> None:
    """Проверяет маппинг имени/фамилии/пола/даты рождения/email из ответа iiko."""

    gateway = IikoLoyaltyGateway(api_key="test-key", organization_id="test-org")
    customer = gateway._extract_customer(  # noqa: SLF001 - тестируем внутренний маппинг
        {
            "id": "cust-1",
            "name": "Андрей",
            "surname": "Иванов",
            "sex": 1,
            "birthday": "1990-05-17 00:00:00.000",
            "email": "andrey@example.com",
            "walletBalances": [
                {
                    "name": "программа лояльности",
                    "balance": 120.5,
                }
            ],
            "cards": [
                {
                    "number": "79123456789_20260330",
                    "validToDate": "2030-12-31 00:00:00.000",
                }
            ],
        }
    )

    assert customer.customer_id == "cust-1"
    assert customer.balance == 120.5
    assert customer.first_name == "Андрей"
    assert customer.last_name == "Иванов"
    assert customer.gender == "male"
    assert customer.birth_date == date(1990, 5, 17)
    assert customer.email == "andrey@example.com"
    assert customer.cards[0].number == "79123456789_20260330"


def test_extract_customer_supports_alternative_iiko_keys() -> None:
    """Проверяет fallback по ключам surName/birthDate/gender/eMail."""

    gateway = IikoLoyaltyGateway(api_key="test-key", organization_id="test-org")
    customer = gateway._extract_customer(  # noqa: SLF001 - тестируем внутренний маппинг
        {
            "id": "cust-2",
            "firstName": "Мария",
            "surName": "Петрова",
            "gender": "female",
            "birthDate": "1988-03-12",
            "eMail": "maria@example.com",
            "walletBalances": [],
            "cards": [],
        }
    )

    assert customer.customer_id == "cust-2"
    assert customer.first_name == "Мария"
    assert customer.last_name == "Петрова"
    assert customer.gender == "female"
    assert customer.birth_date == date(1988, 3, 12)
    assert customer.email == "maria@example.com"


def test_register_customer_maps_profile_to_create_or_update_payload() -> None:
    """Проверяет, что create_or_update получает поля профиля и признаки согласий."""

    gateway = IikoLoyaltyGateway(api_key="test-key", organization_id="test-org")
    gateway._get_access_token = lambda: "test-token"  # noqa: SLF001 - стаб для unit-теста
    captured: dict[str, object] = {}

    def _fake_post_json(*, path: str, payload: dict[str, object], token: str | None):
        captured["path"] = path
        captured["payload"] = payload
        captured["token"] = token
        return 200, {"id": "cust-42"}, '{"id":"cust-42"}'

    gateway._post_json = _fake_post_json  # noqa: SLF001 - стаб для unit-теста
    profile = LoyaltyCustomerUpsertData(
        first_name="Андрей",
        last_name="Соболев",
        gender="male",
        birth_date=date(1990, 5, 17),
        email="andrey@example.com",
        rules_accepted=True,
        notifications_allowed=False,
        rules_accepted_at=datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc),
        notifications_allowed_at=datetime(2026, 3, 31, 12, 1, tzinfo=timezone.utc),
    )

    result = gateway.register_customer(
        "+79129923438",
        profile=profile,
        customer_id="legacy-customer-id",
    )

    assert result.customer_id == "cust-42"
    assert captured["path"] == "/loyalty/iiko/customer/create_or_update"
    assert captured["token"] == "test-token"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["phone"] == "+79129923438"
    assert payload["name"] == "Андрей"
    assert payload["surName"] == "Соболев"
    assert payload["birthday"] == "1990-05-17 00:00:00.000"
    assert payload["sex"] == 1
    assert payload["email"] == "andrey@example.com"
    assert payload["consentStatus"] == 1
    assert payload["shouldReceivePromoActionsInfo"] is False
    assert payload["shouldReceiveLoyaltyInfo"] is False
    assert payload["id"] == "legacy-customer-id"


def test_get_customer_info_returns_none_for_not_found_status() -> None:
    """Проверяет штатный сценарий: 400/404 от customer/info означает, что клиент не найден."""

    gateway = IikoLoyaltyGateway(api_key="test-key", organization_id="test-org")
    gateway._get_access_token = lambda: "test-token"  # noqa: SLF001 - стаб для unit-теста

    def _fake_post_json(*, path: str, payload: dict[str, object], token: str | None):
        return 404, {}, '{"error":"not found"}'

    gateway._post_json = _fake_post_json  # noqa: SLF001 - стаб для unit-теста

    assert gateway.get_customer_info("+79129923438") is None


def test_get_customer_info_maps_http_error_to_diagnostic_metadata() -> None:
    """Проверяет диагностический маппинг HTTP-ошибок iiko в LoyaltyGatewayError."""

    gateway = IikoLoyaltyGateway(api_key="test-key", organization_id="test-org")
    gateway._get_access_token = lambda: "test-token"  # noqa: SLF001 - стаб для unit-теста

    def _fake_post_json(*, path: str, payload: dict[str, object], token: str | None):
        return 503, {}, '{"error":"temporarily unavailable"}'

    gateway._post_json = _fake_post_json  # noqa: SLF001 - стаб для unit-теста

    with pytest.raises(LoyaltyGatewayError) as error_info:
        gateway.get_customer_info("+79129923438")

    error = error_info.value
    assert error.reason_code == "customer_info_http_error"
    assert error.endpoint == "/loyalty/iiko/customer/info"
    assert error.status_code == 503
    assert error.is_transient is True


def test_get_customer_info_maps_invalid_payload_to_diagnostic_metadata() -> None:
    """Проверяет диагностический маппинг невалидного успешного ответа iiko."""

    gateway = IikoLoyaltyGateway(api_key="test-key", organization_id="test-org")
    gateway._get_access_token = lambda: "test-token"  # noqa: SLF001 - стаб для unit-теста

    def _fake_post_json(*, path: str, payload: dict[str, object], token: str | None):
        return 200, {}, "{}"

    gateway._post_json = _fake_post_json  # noqa: SLF001 - стаб для unit-теста

    with pytest.raises(LoyaltyGatewayError) as error_info:
        gateway.get_customer_info("+79129923438")

    error = error_info.value
    assert error.reason_code == "customer_info_payload_invalid"
    assert error.endpoint == "/loyalty/iiko/customer/info"
    assert error.status_code == 200
    assert error.is_transient is False
