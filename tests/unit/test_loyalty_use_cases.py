"""Тесты use-case сценариев разделов «Мой баланс» и «Виртуальная карта»."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from vtelemax.core import (
    GetLoyaltyBalanceUseCase,
    GetVirtualCardUseCase,
    LoyaltyCard,
    LoyaltyCustomer,
    LoyaltyCustomerUpsertData,
    LoyaltyGateway,
    LoyaltyGatewayError,
    LoyaltyIssueCardResult,
    LoyaltyRegisterCustomerResult,
)


@dataclass(slots=True)
class _GatewayBehavior:
    customer_sequence: list[LoyaltyCustomer | None]
    register_result: LoyaltyRegisterCustomerResult | None = None
    issue_result: LoyaltyIssueCardResult | None = None
    register_error: LoyaltyGatewayError | None = None
    issue_error: LoyaltyGatewayError | None = None
    info_error: LoyaltyGatewayError | None = None


class FakeLoyaltyGateway(LoyaltyGateway):
    """Тестовый шлюз лояльности с управляемым поведением."""

    def __init__(self, behavior: _GatewayBehavior) -> None:
        self._behavior = behavior
        self.info_calls = 0
        self.register_calls = 0
        self.issue_calls = 0
        self.last_register_profile: LoyaltyCustomerUpsertData | None = None
        self.last_register_customer_id: str | None = None

    def get_customer_info(self, phone_e164: str) -> LoyaltyCustomer | None:
        self.info_calls += 1
        if self._behavior.info_error is not None:
            raise self._behavior.info_error
        if self._behavior.customer_sequence:
            return self._behavior.customer_sequence.pop(0)
        return None

    def register_customer(
        self,
        phone_e164: str,
        *,
        profile: LoyaltyCustomerUpsertData | None = None,
        customer_id: str | None = None,
    ) -> LoyaltyRegisterCustomerResult:
        self.register_calls += 1
        self.last_register_profile = profile
        self.last_register_customer_id = customer_id
        if self._behavior.register_error is not None:
            raise self._behavior.register_error
        if self._behavior.register_result is None:
            raise LoyaltyGatewayError("register_result is not configured")
        return self._behavior.register_result

    def issue_card_for_customer(self, phone_e164: str, customer_id: str) -> LoyaltyIssueCardResult:
        self.issue_calls += 1
        if self._behavior.issue_error is not None:
            raise self._behavior.issue_error
        if self._behavior.issue_result is None:
            raise LoyaltyGatewayError("issue_result is not configured")
        return self._behavior.issue_result


def test_balance_use_case_returns_balance_screen_when_customer_found() -> None:
    """Проверяет успешный сценарий получения бонусного баланса."""

    gateway = FakeLoyaltyGateway(
        _GatewayBehavior(
            customer_sequence=[
                LoyaltyCustomer(
                    customer_id="cust-1",
                    balance=125.5,
                    cards=(),
                )
            ]
        )
    )
    use_case = GetLoyaltyBalanceUseCase(gateway)

    result = use_case.execute(phone_e164="+79123456789")

    assert result.status == "balance"
    assert result.parse_mode == "markdown"
    assert "125.50" in result.message


def test_balance_use_case_returns_unavailable_when_customer_missing() -> None:
    """Проверяет fallback-сценарий, когда клиент в системе лояльности не найден."""

    gateway = FakeLoyaltyGateway(_GatewayBehavior(customer_sequence=[None]))
    use_case = GetLoyaltyBalanceUseCase(gateway)

    result = use_case.execute(phone_e164="+79123456789")

    assert result.status == "balance_unavailable"
    assert "не удалось" in result.message.lower()


def test_balance_use_case_returns_unavailable_when_gateway_failed() -> None:
    """Проверяет обработку сетевой/внешней ошибки шлюза лояльности."""

    gateway = FakeLoyaltyGateway(
        _GatewayBehavior(
            customer_sequence=[],
            info_error=LoyaltyGatewayError("gateway failed"),
        )
    )
    use_case = GetLoyaltyBalanceUseCase(gateway)

    result = use_case.execute(phone_e164="+79123456789")

    assert result.status == "balance_unavailable"


def test_virtual_card_use_case_returns_existing_cards_without_issue() -> None:
    """Проверяет сценарий, когда у клиента уже есть выпущенные карты."""

    gateway = FakeLoyaltyGateway(
        _GatewayBehavior(
            customer_sequence=[
                LoyaltyCustomer(
                    customer_id="cust-1",
                    balance=0.0,
                    cards=(LoyaltyCard(number="79123456789_20260325"),),
                )
            ],
        )
    )
    use_case = GetVirtualCardUseCase(gateway)

    result = use_case.execute(phone_e164="+79123456789")

    assert result.status == "virtual_card"
    assert "79123456789_20260325" in result.message
    assert result.card_numbers == ("79123456789_20260325",)
    assert gateway.register_calls == 0
    assert gateway.issue_calls == 0


def test_virtual_card_use_case_registers_and_issues_card_for_new_customer() -> None:
    """Проверяет полный happy-path: нет клиента -> регистрация -> выпуск карты."""

    gateway = FakeLoyaltyGateway(
        _GatewayBehavior(
            customer_sequence=[
                None,
                LoyaltyCustomer(
                    customer_id="cust-2",
                    balance=0.0,
                    cards=(LoyaltyCard(number="79123456789_20260325"),),
                ),
            ],
            register_result=LoyaltyRegisterCustomerResult(
                customer_id="cust-2",
                message="registered",
            ),
            issue_result=LoyaltyIssueCardResult(
                card_number="79123456789_20260325",
                message="issued",
            ),
        )
    )
    use_case = GetVirtualCardUseCase(gateway)

    result = use_case.execute(phone_e164="+79123456789")

    assert result.status == "virtual_card"
    assert "79123456789_20260325" in result.message
    assert result.card_numbers == ("79123456789_20260325",)
    assert gateway.register_calls == 1
    assert gateway.issue_calls == 1


def test_virtual_card_use_case_passes_profile_to_register_on_create() -> None:
    """Проверяет, что при создании клиента use-case передает профиль в create_or_update."""

    gateway = FakeLoyaltyGateway(
        _GatewayBehavior(
            customer_sequence=[
                None,
                LoyaltyCustomer(customer_id="cust-2", balance=0.0, cards=()),
            ],
            register_result=LoyaltyRegisterCustomerResult(
                customer_id="cust-2",
                message="registered",
            ),
            issue_result=LoyaltyIssueCardResult(
                card_number="79123456789_20260325",
                message="issued",
            ),
        )
    )
    use_case = GetVirtualCardUseCase(gateway)
    profile = LoyaltyCustomerUpsertData(
        first_name="Андрей",
        rules_accepted=True,
        notifications_allowed=False,
    )

    use_case.execute(phone_e164="+79123456789", profile=profile)

    assert gateway.register_calls == 1
    assert gateway.last_register_profile is profile
    assert gateway.last_register_customer_id is None


def test_virtual_card_use_case_updates_existing_customer_when_profile_passed() -> None:
    """Проверяет, что для существующего клиента use-case вызывает update в iiko с customer_id."""

    gateway = FakeLoyaltyGateway(
        _GatewayBehavior(
            customer_sequence=[
                LoyaltyCustomer(
                    customer_id="cust-existing",
                    balance=0.0,
                    cards=(LoyaltyCard(number="79123456789_20260325"),),
                )
            ],
            register_result=LoyaltyRegisterCustomerResult(
                customer_id="cust-existing",
                message="updated",
            ),
        )
    )
    use_case = GetVirtualCardUseCase(gateway)
    profile = LoyaltyCustomerUpsertData(first_name="Андрей", rules_accepted=True)

    result = use_case.execute(phone_e164="+79123456789", profile=profile)

    assert result.status == "virtual_card"
    assert gateway.register_calls == 1
    assert gateway.last_register_profile is profile
    assert gateway.last_register_customer_id == "cust-existing"
    assert gateway.issue_calls == 0


def test_virtual_card_use_case_returns_error_when_registration_failed() -> None:
    """Проверяет ошибочный сценарий: не удалось зарегистрировать клиента в iiko."""

    gateway = FakeLoyaltyGateway(
        _GatewayBehavior(
            customer_sequence=[None],
            register_error=LoyaltyGatewayError("register failed"),
        )
    )
    use_case = GetVirtualCardUseCase(gateway)

    result = use_case.execute(phone_e164="+79123456789")

    assert result.status == "virtual_card_error"
    assert "зарегистрировать" in result.message.lower()
    assert result.card_numbers == ()


def test_virtual_card_use_case_returns_error_when_issue_failed() -> None:
    """Проверяет ошибочный сценарий: выпуск карты завершился ошибкой."""

    gateway = FakeLoyaltyGateway(
        _GatewayBehavior(
            customer_sequence=[
                LoyaltyCustomer(
                    customer_id="cust-3",
                    balance=0.0,
                    cards=(),
                )
            ],
            issue_error=LoyaltyGatewayError("issue failed"),
        )
    )
    use_case = GetVirtualCardUseCase(gateway)

    result = use_case.execute(phone_e164="+79123456789")

    assert result.status == "virtual_card_error"
    assert "выпустить карту" in result.message.lower()
    assert result.card_numbers == ()


def test_loyalty_use_cases_raise_for_empty_phone_dirty_input() -> None:
    """Проверяет dirty-сценарий: пустой телефон не допускается в use-case."""

    gateway = FakeLoyaltyGateway(_GatewayBehavior(customer_sequence=[]))
    balance_use_case = GetLoyaltyBalanceUseCase(gateway)
    virtual_card_use_case = GetVirtualCardUseCase(gateway)

    with pytest.raises(ValueError):
        balance_use_case.execute(phone_e164="  ")

    with pytest.raises(ValueError):
        virtual_card_use_case.execute(phone_e164="")
