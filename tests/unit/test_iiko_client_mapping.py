"""Тесты маппинга полей iiko в доменную модель LoyaltyCustomer."""

from __future__ import annotations

from datetime import date

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
