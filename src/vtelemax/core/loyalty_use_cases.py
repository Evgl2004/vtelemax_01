"""Use-case сценарии разделов «Мой баланс» и «Виртуальная карта».

Модуль изолирует бизнес-логику работы с бонусной системой от конкретных
мессенджерных адаптеров.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from loguru import logger

from .guest_content import build_balance_screen
from .loyalty_ports import (
    LoyaltyCard,
    LoyaltyCustomerUpsertData,
    LoyaltyGateway,
    LoyaltyGatewayError,
)

_BALANCE_UNAVAILABLE_TEXT = (
    "❌ Не удалось получить данные по бонусам.\n"
    "Код ошибки: IIKO-BAL-001.\n"
    "Покажите это сообщение сотруднику и попробуйте позже."
)

_VIRTUAL_CARD_UNAVAILABLE_TEXT = (
    "❌ Не удалось получить данные виртуальной карты.\n"
    "Код ошибки: IIKO-CARD-001.\n"
    "Покажите это сообщение сотруднику и попробуйте позже."
)


@dataclass(frozen=True, slots=True)
class LoyaltyMenuResult:
    """Результат формирования экранов лояльности для адаптеров."""

    status: str
    message: str
    parse_mode: str | None = None
    card_numbers: tuple[str, ...] = ()
    diagnostic_context: str | None = None
    customer_id: str | None = None
    created_new_customer: bool = False
    existing_customer_found: bool = False


class LoyaltyRegistrationObserver(Protocol):
    """Наблюдатель финальной регистрации для фиксации фактов iikoCard в outbox."""

    def mark_lookup_failed(self, error: LoyaltyGatewayError) -> None:
        """Фиксирует ошибку поиска гостя iikoCard до попытки создания."""

    def mark_existing_customer(self, customer_id: str) -> None:
        """Фиксирует найденного существующего гостя iikoCard."""

    def mark_create_started(self) -> None:
        """Фиксирует начало создания гостя iikoCard."""

    def mark_created_customer(self, customer_id: str) -> None:
        """Фиксирует успешное создание гостя iikoCard."""

    def mark_create_result_unknown(self, error: LoyaltyGatewayError) -> None:
        """Фиксирует неизвестный результат создания гостя iikoCard."""

    def mark_create_failed_terminal(self, error: LoyaltyGatewayError) -> None:
        """Фиксирует финальную ошибку создания гостя iikoCard."""


def _notify_registration_observer(
    observer: LoyaltyRegistrationObserver | None,
    method_name: str,
    *args: object,
) -> None:
    """Вызывает наблюдатель, не ломая пользовательский сценарий ошибкой учета."""

    if observer is None:
        return
    try:
        method = getattr(observer, method_name)
        method(*args)
    except Exception as error:  # noqa: BLE001
        logger.bind(component="loyalty_use_case", stage="registration_observer").warning(
            "Не удалось зафиксировать факт iikoCard для SAGUR-регистра. method={method}, error={error}.",
            method=method_name,
            error=error,
        )


def _phone_hash(phone_e164: str) -> str:
    """Возвращает короткий хеш телефона для логов без раскрытия PII."""

    return hashlib.sha256(str(phone_e164).encode("utf-8")).hexdigest()[:12]


def _format_gateway_diagnostic(error: LoyaltyGatewayError) -> str:
    """Формирует безопасный diagnostic context для внутренних тикетов и логов."""

    parts = [
        "code=IIKO-BAL-001",
        f"reason={getattr(error, 'reason_code', 'unknown')}",
    ]
    endpoint = getattr(error, "endpoint", None)
    if endpoint:
        parts.append(f"endpoint={endpoint}")
    status_code = getattr(error, "status_code", None)
    if status_code is not None:
        parts.append(f"status_code={status_code}")
    is_transient = getattr(error, "is_transient", None)
    if is_transient is not None:
        parts.append(f"transient={str(bool(is_transient)).lower()}")
    return "; ".join(parts)


class GetLoyaltyBalanceUseCase:
    """Формирует ответ раздела «Мой баланс» на основе данных бонусной системы."""

    def __init__(self, loyalty_gateway: LoyaltyGateway) -> None:
        self._loyalty_gateway = loyalty_gateway

    def execute(self, *, phone_e164: str) -> LoyaltyMenuResult:
        """Возвращает сообщение с балансом или fallback при недоступности данных."""

        normalized_phone = str(phone_e164).strip()
        if not normalized_phone:
            raise ValueError("Телефон пользователя не может быть пустым.")

        balance_logger = logger.bind(component="loyalty_use_case", stage="balance")
        safe_phone_hash = _phone_hash(normalized_phone)

        try:
            customer = self._loyalty_gateway.get_customer_info(normalized_phone)
        except LoyaltyGatewayError as error:
            diagnostic_context = _format_gateway_diagnostic(error)
            balance_logger.warning(
                "Баланс недоступен: ошибка шлюза iiko. diagnostic={diagnostic}, phone_hash={phone_hash}.",
                diagnostic=diagnostic_context,
                phone_hash=safe_phone_hash,
            )
            return LoyaltyMenuResult(
                status="balance_unavailable",
                message=_BALANCE_UNAVAILABLE_TEXT,
                diagnostic_context=diagnostic_context,
            )

        if customer is None:
            diagnostic_context = "code=IIKO-BAL-001; reason=customer_not_found; transient=false"
            balance_logger.warning(
                "Баланс недоступен: клиент не найден в iiko. diagnostic={diagnostic}, phone_hash={phone_hash}.",
                diagnostic=diagnostic_context,
                phone_hash=safe_phone_hash,
            )
            return LoyaltyMenuResult(
                status="balance_unavailable",
                message=_BALANCE_UNAVAILABLE_TEXT,
                diagnostic_context=diagnostic_context,
            )

        screen = build_balance_screen(balance=float(customer.balance))
        return LoyaltyMenuResult(
            status="balance",
            message=screen.text,
            parse_mode=screen.parse_mode,
        )


class GetVirtualCardUseCase:
    """Формирует ответ раздела «Виртуальная карта» с автосозданием карты."""

    def __init__(self, loyalty_gateway: LoyaltyGateway) -> None:
        self._loyalty_gateway = loyalty_gateway

    def execute(
        self,
        *,
        phone_e164: str,
        profile: LoyaltyCustomerUpsertData | None = None,
        registration_observer: LoyaltyRegistrationObserver | None = None,
    ) -> LoyaltyMenuResult:
        """Возвращает список карт, при необходимости создает/обновляет клиента и выпускает карту."""

        normalized_phone = str(phone_e164).strip()
        if not normalized_phone:
            raise ValueError("Телефон пользователя не может быть пустым.")

        try:
            customer = self._loyalty_gateway.get_customer_info(normalized_phone)
        except LoyaltyGatewayError as error:
            _notify_registration_observer(registration_observer, "mark_lookup_failed", error)
            return LoyaltyMenuResult(status="virtual_card_error", message=_VIRTUAL_CARD_UNAVAILABLE_TEXT)

        created_new_customer = False
        existing_customer_found = False
        if customer is None:
            try:
                _notify_registration_observer(registration_observer, "mark_create_started")
                registered = self._loyalty_gateway.register_customer(
                    normalized_phone,
                    profile=profile,
                )
            except LoyaltyGatewayError as error:
                if getattr(error, "is_transient", None) is False:
                    _notify_registration_observer(
                        registration_observer,
                        "mark_create_failed_terminal",
                        error,
                    )
                else:
                    _notify_registration_observer(
                        registration_observer,
                        "mark_create_result_unknown",
                        error,
                    )
                return LoyaltyMenuResult(
                    status="virtual_card_error",
                    message=(
                        "❌ Не удалось зарегистрировать вас в бонусной системе.\n"
                        "Код ошибки: IIKO-CARD-002.\n"
                        f"Причина: {error}\n\n"
                        "Покажите это сообщение сотруднику и попробуйте позже."
                    ),
                )
            customer_id = registered.customer_id
            created_new_customer = True
            _notify_registration_observer(
                registration_observer,
                "mark_created_customer",
                customer_id,
            )
            cards: tuple[LoyaltyCard, ...] = ()
        else:
            customer_id = customer.customer_id
            existing_customer_found = True
            _notify_registration_observer(
                registration_observer,
                "mark_existing_customer",
                customer_id,
            )
            cards = customer.cards
            if profile is not None:
                try:
                    self._loyalty_gateway.register_customer(
                        normalized_phone,
                        profile=profile,
                        customer_id=customer_id,
                    )
                except LoyaltyGatewayError as error:
                    return LoyaltyMenuResult(
                        status="virtual_card_error",
                        message=(
                            "❌ Не удалось обновить данные профиля в бонусной системе.\n"
                            "Код ошибки: IIKO-CARD-004.\n"
                            f"Причина: {error}\n\n"
                            "Покажите это сообщение сотруднику и попробуйте позже."
                        ),
                    )

        if not cards:
            try:
                issued = self._loyalty_gateway.issue_card_for_customer(
                    normalized_phone,
                    customer_id=customer_id,
                )
            except LoyaltyGatewayError as error:
                return LoyaltyMenuResult(
                    status="virtual_card_error",
                    message=(
                        "❌ Не удалось выпустить карту.\n"
                        "Код ошибки: IIKO-CARD-003.\n"
                        f"Причина: {error}\n\n"
                        "Покажите это сообщение сотруднику и попробуйте позже."
                    ),
                )

            # После выпуска пытаемся получить актуальный список карт.
            try:
                refreshed = self._loyalty_gateway.get_customer_info(normalized_phone)
            except LoyaltyGatewayError:
                refreshed = None

            if refreshed is not None and refreshed.cards:
                cards = refreshed.cards
            else:
                cards = (LoyaltyCard(number=issued.card_number),)

        return LoyaltyMenuResult(
            status="virtual_card",
            message=self._format_virtual_cards_message(cards),
            parse_mode="markdown",
            card_numbers=tuple(card.number for card in cards if card.number),
            customer_id=customer_id,
            created_new_customer=created_new_customer,
            existing_customer_found=existing_customer_found,
        )

    @staticmethod
    def _format_virtual_cards_message(cards: tuple[LoyaltyCard, ...]) -> str:
        """Форматирует ответ раздела «Виртуальная карта» в едином стиле для всех платформ."""

        lines = ["🪪 *Виртуальная карта*", ""]
        if len(cards) == 1:
            lines.append("Ваша бонусная карта:")
        else:
            lines.append("Ваши бонусные карты:")

        for index, card in enumerate(cards, start=1):
            valid_to_suffix = f" (до {card.valid_to})" if card.valid_to else ""
            lines.append(f"{index}. `{card.number}`{valid_to_suffix}")

        card_count = len(cards)
        if card_count == 1:
            ending = "карта"
        elif 1 < card_count < 5:
            ending = "карты"
        else:
            ending = "карт"

        lines.extend(
            [
                "",
                f"✅ Это все ваши бонусные {ending} ({card_count} шт.).",
                "Покажите номер или QR-код карты официанту для начисления бонусов.",
                "",
                (
                    "*Данная программа лояльности не распространяется на услуги доставки, "
                    "столовые «Ассорти» и мастерскую сыра «Страчателли»*"
                ),
            ]
        )
        return "\n".join(lines)
