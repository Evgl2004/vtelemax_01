"""Общие правила обработки кнопок интерактивных сообщений SAGUR.

Модуль не зависит от библиотек Telegram, VK и MAX. Платформенные адаптеры
передают сюда исходную полезную нагрузку кнопки и получают единое строго
проверенное представление. Такой подход не позволяет трём обработчикам
незаметно разойтись в понимании утверждённого контракта.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


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


class SagurButtonPayloadError(ValueError):
    """Полезная нагрузка заявляет тип SAGUR, но нарушает его контракт."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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
