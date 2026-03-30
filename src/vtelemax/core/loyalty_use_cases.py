"""Use-case сценарии разделов «Мой баланс» и «Виртуальная карта».

Модуль изолирует бизнес-логику работы с бонусной системой от конкретных
мессенджерных адаптеров.
"""

from __future__ import annotations

from dataclasses import dataclass

from .guest_content import build_balance_screen
from .loyalty_ports import LoyaltyCard, LoyaltyGateway, LoyaltyGatewayError

_BALANCE_UNAVAILABLE_TEXT = (
    "❌ Информация о бонусах временно недоступна.\n"
    "Пожалуйста, попробуйте позже или обратитесь к администратору."
)

_VIRTUAL_CARD_UNAVAILABLE_TEXT = (
    "❌ Не удалось получить данные виртуальной карты.\n"
    "Пожалуйста, попробуйте позже или обратитесь к администратору."
)


@dataclass(frozen=True, slots=True)
class LoyaltyMenuResult:
    """Результат формирования экранов лояльности для адаптеров."""

    status: str
    message: str
    parse_mode: str | None = None
    card_numbers: tuple[str, ...] = ()


class GetLoyaltyBalanceUseCase:
    """Формирует ответ раздела «Мой баланс» на основе данных бонусной системы."""

    def __init__(self, loyalty_gateway: LoyaltyGateway) -> None:
        self._loyalty_gateway = loyalty_gateway

    def execute(self, *, phone_e164: str) -> LoyaltyMenuResult:
        """Возвращает сообщение с балансом или fallback при недоступности данных."""

        normalized_phone = str(phone_e164).strip()
        if not normalized_phone:
            raise ValueError("Телефон пользователя не может быть пустым.")

        try:
            customer = self._loyalty_gateway.get_customer_info(normalized_phone)
        except LoyaltyGatewayError:
            return LoyaltyMenuResult(status="balance_unavailable", message=_BALANCE_UNAVAILABLE_TEXT)

        if customer is None:
            return LoyaltyMenuResult(status="balance_unavailable", message=_BALANCE_UNAVAILABLE_TEXT)

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

    def execute(self, *, phone_e164: str) -> LoyaltyMenuResult:
        """Возвращает список карт, при необходимости регистрирует клиента и выпускает карту."""

        normalized_phone = str(phone_e164).strip()
        if not normalized_phone:
            raise ValueError("Телефон пользователя не может быть пустым.")

        try:
            customer = self._loyalty_gateway.get_customer_info(normalized_phone)
        except LoyaltyGatewayError:
            return LoyaltyMenuResult(status="virtual_card_error", message=_VIRTUAL_CARD_UNAVAILABLE_TEXT)

        if customer is None:
            try:
                registered = self._loyalty_gateway.register_customer(normalized_phone)
            except LoyaltyGatewayError as error:
                return LoyaltyMenuResult(
                    status="virtual_card_error",
                    message=(
                        "❌ Не удалось зарегистрировать вас в бонусной системе.\n"
                        f"Причина: {error}\n\n"
                        "Попробуйте позже."
                    ),
                )
            customer_id = registered.customer_id
            cards: tuple[LoyaltyCard, ...] = ()
        else:
            customer_id = customer.customer_id
            cards = customer.cards

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
                        f"Причина: {error}\n\n"
                        "Попробуйте позже."
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
