"""Общие правила обработки кнопок интерактивных сообщений SAGUR.

Модуль не зависит от библиотек Telegram, VK и MAX. Платформенные адаптеры
передают сюда исходную полезную нагрузку кнопки и получают единое строго
проверенное представление. Такой подход не позволяет трём обработчикам
незаметно разойтись в понимании утверждённого контракта.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar
from uuid import UUID


SAGUR_INTERACTION_PAYLOAD_KEYS = frozenset({"t", "v", "i", "a"})
SAGUR_INTERACTION_TYPE = "si"
SAGUR_INTERACTION_ID_MAX = 9_223_372_036_854_775_807
SAGUR_INTERACTION_ACTIONS = frozenset({"l", "d", "m", "c"})

_VERSION_2_ACTION_SETS: dict[str, tuple[str, str, str]] = {
    "ldm": ("l", "d", "m"),
    "dlm": ("l", "d", "m"),
    "mld": ("l", "d", "m"),
    "ldc": ("l", "d", "c"),
    "dlc": ("l", "d", "c"),
    "cld": ("l", "d", "c"),
}
_ButtonT = TypeVar("_ButtonT")


class SagurButtonPayloadError(ValueError):
    """Полезная нагрузка заявляет тип SAGUR, но нарушает его контракт."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SagurMessageKeyboardError(ValueError):
    """Фактическая клавиатура не позволяет безопасно удалить только оценки."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SagurMessageInteractionDeliveryStatus(str, Enum):
    """Состояние доставки локального события в SAGUR."""

    PENDING = "pending"
    PROCESSING = "processing"
    RETRY_SCHEDULED = "retry_scheduled"
    DELIVERED = "delivered"
    BLOCKED = "blocked"


class SagurMessageInteractionUserActionStatus(str, Enum):
    """Состояние пользовательского действия после долговечной фиксации."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SagurButtonPayload:
    """Проверенные данные одной кнопки интерактивного сообщения SAGUR.

    ``action`` содержит фактически нажатое действие. ``button_actions``
    описывает семантический набор кнопок сообщения. Для версии 1 полный набор
    неизвестен и поэтому содержит только действие текущей кнопки.
    """

    version: int
    interaction_id: int
    action: str
    button_actions: tuple[str, ...]

    @property
    def navigation_action(self) -> str | None:
        """Возвращает навигационное действие версии 2 либо ``None``."""

        for action in self.button_actions:
            if action in {"m", "c"}:
                return action
        return None


@dataclass(frozen=True, slots=True)
class SagurMessageInteractionIngress:
    """Неизменяемые данные нового обратного вызова платформы."""

    platform: str
    bot_scope: str
    platform_callback_id: str
    interaction_id: int
    action: str
    provider_message_id: str | None = None


@dataclass(frozen=True, slots=True)
class SagurMessageInteractionEvent:
    """Локально сохранённый факт нажатия, готовый к доставке в SAGUR."""

    event_id: UUID
    platform: str
    bot_scope: str
    platform_callback_id: str
    interaction_id: int
    action: str
    occurred_at: datetime
    provider_message_id: str | None


@dataclass(frozen=True, slots=True)
class SagurMessageInteractionInsertResult:
    """Результат атомарной вставки по составному платформенному ключу."""

    event: SagurMessageInteractionEvent
    created: bool
    immutable_fields_match: bool


@dataclass(frozen=True, slots=True)
class SagurMessageInteractionDeliveryTask:
    """Событие, выбранное активной очередью для одной HTTP-попытки."""

    event_id: UUID
    interaction_id: int
    action: str
    occurred_at: datetime
    provider_message_id: str | None
    delivery_attempts: int


def _json_object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Собирает объект JSON и отклоняет неоднозначные повторяющиеся ключи."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SagurButtonPayloadError("duplicate_json_key")
        result[key] = value
    return result


def _decode_payload(
    raw_payload: str | Mapping[str, Any] | None,
    *,
    max_bytes: int | None,
) -> Mapping[str, Any] | None:
    """Декодирует строку или отображение без потери строгих проверок типов."""

    if raw_payload is None:
        return None
    if isinstance(raw_payload, str):
        try:
            encoded = raw_payload.encode("utf-8")
        except UnicodeEncodeError:
            return None
        if max_bytes is not None and len(encoded) > max_bytes:
            raise SagurButtonPayloadError("payload_too_large")
        try:
            decoded = json.loads(
                raw_payload,
                object_pairs_hook=_json_object_without_duplicate_keys,
            )
        except SagurButtonPayloadError:
            raise
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        return decoded if isinstance(decoded, Mapping) else None
    if isinstance(raw_payload, Mapping):
        return raw_payload
    return None


def parse_sagur_button_payload(
    raw_payload: str | Mapping[str, Any] | None,
    *,
    max_bytes: int | None = None,
) -> SagurButtonPayload | None:
    """Строго разбирает служебные данные кнопки SAGUR версий 1 и 2.

    ``None`` означает, что данные не заявляют тип ``si`` и должны быть
    переданы другим платформенным обработчикам. Если тип ``si`` заявлен, но
    данные нарушают контракт, возбуждается :class:`SagurButtonPayloadError`.

    Для строк проверяются повторяющиеся ключи JSON. Параметр ``max_bytes``
    позволяет адаптеру Telegram дополнительно применить платформенный предел
    в 64 байта к фактически полученной строке.
    """

    decoded = _decode_payload(raw_payload, max_bytes=max_bytes)
    if decoded is None or decoded.get("t") != SAGUR_INTERACTION_TYPE:
        return None

    if frozenset(decoded.keys()) != SAGUR_INTERACTION_PAYLOAD_KEYS:
        raise SagurButtonPayloadError("payload_fields_invalid")

    version = decoded["v"]
    interaction_id = decoded["i"]
    action_value = decoded["a"]

    if type(version) is not int or version not in {1, 2}:
        raise SagurButtonPayloadError("payload_version_invalid")
    if type(interaction_id) is not int or not (
        1 <= interaction_id <= SAGUR_INTERACTION_ID_MAX
    ):
        raise SagurButtonPayloadError("interaction_id_invalid")
    if not isinstance(action_value, str):
        raise SagurButtonPayloadError("payload_action_invalid")

    if version == 1:
        if action_value not in SAGUR_INTERACTION_ACTIONS:
            raise SagurButtonPayloadError("payload_action_invalid")
        button_actions = (action_value,)
    else:
        button_actions = _VERSION_2_ACTION_SETS.get(action_value)
        if button_actions is None:
            raise SagurButtonPayloadError("payload_action_invalid")

    return SagurButtonPayload(
        version=version,
        interaction_id=interaction_id,
        action=action_value[0],
        button_actions=button_actions,
    )


def remove_sagur_rating_buttons_from_rows(
    rows: Sequence[Sequence[_ButtonT]],
    *,
    clicked_payload: SagurButtonPayload,
    payload_getter: Callable[[_ButtonT], str | Mapping[str, Any] | None],
) -> tuple[tuple[_ButtonT, ...], ...]:
    """Удаляет ``l/d`` одного сообщения, сохраняя все остальные кнопки.

    Функция работает только с фактически прочитанными рядами платформы и
    возвращает прежние объекты кнопок. Текст, стиль, ссылка и иные неизвестные
    поля поэтому не реконструируются. Изменение разрешается лишь когда найден
    полный и непротиворечивый набор ``l+d+m`` либо ``l+d+c`` одного
    ``interaction_id``.
    """

    if clicked_payload.action not in {"l", "d"}:
        raise SagurMessageKeyboardError("rating_action_required")

    matching_buttons: list[tuple[int, int, SagurButtonPayload]] = []
    for row_index, row in enumerate(rows):
        for button_index, button in enumerate(row):
            payload = parse_sagur_button_payload(payload_getter(button))
            if payload is not None and payload.interaction_id == clicked_payload.interaction_id:
                matching_buttons.append((row_index, button_index, payload))

    if len(matching_buttons) != 3:
        raise SagurMessageKeyboardError("interaction_button_count_invalid")

    matched_payloads = tuple(item[2] for item in matching_buttons)
    observed_actions = tuple(payload.action for payload in matched_payloads)
    observed_action_set = frozenset(observed_actions)
    if len(observed_action_set) != 3 or observed_action_set not in {
        frozenset({"l", "d", "m"}),
        frozenset({"l", "d", "c"}),
    }:
        raise SagurMessageKeyboardError("interaction_button_set_invalid")

    if clicked_payload.version == 2:
        expected_actions = frozenset(clicked_payload.button_actions)
        if observed_action_set != expected_actions or any(
            payload.version != 2
            or frozenset(payload.button_actions) != expected_actions
            for payload in matched_payloads
        ):
            raise SagurMessageKeyboardError("interaction_button_contract_mismatch")
    elif any(payload.version != 1 for payload in matched_payloads):
        raise SagurMessageKeyboardError("interaction_button_contract_mismatch")

    rating_positions = {
        (row_index, button_index)
        for row_index, button_index, payload in matching_buttons
        if payload.action in {"l", "d"}
    }
    updated_rows: list[tuple[_ButtonT, ...]] = []
    for row_index, row in enumerate(rows):
        updated_row = tuple(
            button
            for button_index, button in enumerate(row)
            if (row_index, button_index) not in rating_positions
        )
        if updated_row:
            updated_rows.append(updated_row)
    return tuple(updated_rows)
