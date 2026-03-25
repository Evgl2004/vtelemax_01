"""Порты (контракты) доменного слоя лояльности.

Контракты описывают, как core-логика работает с внешней бонусной системой
(например, iiko), не зная деталей HTTP/API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LoyaltyCard:
    """Карточка бонусной карты пользователя."""

    number: str
    valid_to: str | None = None


@dataclass(frozen=True, slots=True)
class LoyaltyCustomer:
    """Снимок данных клиента бонусной системы."""

    customer_id: str
    balance: float
    cards: tuple[LoyaltyCard, ...]
    program_name: str = ""


@dataclass(frozen=True, slots=True)
class LoyaltyRegisterCustomerResult:
    """Результат регистрации клиента в бонусной системе."""

    customer_id: str
    message: str


@dataclass(frozen=True, slots=True)
class LoyaltyIssueCardResult:
    """Результат выпуска виртуальной карты."""

    card_number: str
    message: str


class LoyaltyGatewayError(RuntimeError):
    """Ошибки обращения к внешней бонусной системе."""


class LoyaltyGateway(Protocol):
    """Контракт внешнего шлюза бонусной системы."""

    def get_customer_info(self, phone_e164: str) -> LoyaltyCustomer | None:
        """Возвращает клиента по телефону или `None`, если клиент не найден."""

    def register_customer(self, phone_e164: str) -> LoyaltyRegisterCustomerResult:
        """Регистрирует клиента в бонусной системе."""

    def issue_card_for_customer(self, phone_e164: str, customer_id: str) -> LoyaltyIssueCardResult:
        """Выпускает карту для клиента с указанным `customer_id`."""
