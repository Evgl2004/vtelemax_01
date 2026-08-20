"""Тесты общего контракта кнопок интерактивных сообщений SAGUR."""

from __future__ import annotations

import json
from typing import Any

import pytest

from vtelemax.core.sagur_message_interactions import (
    SAGUR_INTERACTION_ID_MAX,
    SagurButtonPayload,
    SagurButtonPayloadError,
    parse_sagur_button_payload,
)


def _payload(*, version: int = 1, interaction_id: int = 123456, action: str = "l") -> str:
    return json.dumps(
        {"t": "si", "v": version, "i": interaction_id, "a": action},
        ensure_ascii=False,
        separators=(",", ":"),
    )


@pytest.mark.parametrize("action", ["l", "d", "m", "c"])
def test_version_1_accepts_every_supported_action(action: str) -> None:
    result = parse_sagur_button_payload(_payload(action=action))

    assert result == SagurButtonPayload(
        version=1,
        interaction_id=123456,
        action=action,
        button_actions=(action,),
    )
    assert result.navigation_action == (action if action in {"m", "c"} else None)


@pytest.mark.parametrize(
    ("value", "pressed_action", "button_actions", "navigation_action"),
    [
        ("ldm", "l", ("l", "d", "m"), "m"),
        ("dlm", "d", ("l", "d", "m"), "m"),
        ("mld", "m", ("l", "d", "m"), "m"),
        ("ldc", "l", ("l", "d", "c"), "c"),
        ("dlc", "d", ("l", "d", "c"), "c"),
        ("cld", "c", ("l", "d", "c"), "c"),
    ],
)
def test_version_2_accepts_only_approved_closed_values(
    value: str,
    pressed_action: str,
    button_actions: tuple[str, str, str],
    navigation_action: str,
) -> None:
    result = parse_sagur_button_payload(_payload(version=2, action=value))

    assert result == SagurButtonPayload(
        version=2,
        interaction_id=123456,
        action=pressed_action,
        button_actions=button_actions,
    )
    assert result.navigation_action == navigation_action


def test_mapping_from_vk_or_max_is_supported_without_platform_dependencies() -> None:
    result = parse_sagur_button_payload({"t": "si", "v": 2, "i": 42, "a": "cld"})

    assert result == SagurButtonPayload(
        version=2,
        interaction_id=42,
        action="c",
        button_actions=("l", "d", "c"),
    )


@pytest.mark.parametrize(
    "raw_payload",
    [
        None,
        "",
        "не JSON",
        "[]",
        "null",
        {"t": "другой", "v": 1, "i": 1, "a": "l"},
        ["si", 1, 1, "l"],
        123,
        "\ud800",
    ],
)
def test_payloads_of_other_handlers_are_not_intercepted(raw_payload: Any) -> None:
    assert parse_sagur_button_payload(raw_payload) is None


@pytest.mark.parametrize(
    ("raw_payload", "error_code"),
    [
        ({"t": "si", "v": 1, "i": 1}, "payload_fields_invalid"),
        ({"t": "si", "v": 1, "i": 1, "a": "l", "x": 1}, "payload_fields_invalid"),
        ({"t": "si", "v": True, "i": 1, "a": "l"}, "payload_version_invalid"),
        ({"t": "si", "v": 3, "i": 1, "a": "l"}, "payload_version_invalid"),
        ({"t": "si", "v": 1, "i": True, "a": "l"}, "interaction_id_invalid"),
        ({"t": "si", "v": 1, "i": 0, "a": "l"}, "interaction_id_invalid"),
        ({"t": "si", "v": 1, "i": -1, "a": "l"}, "interaction_id_invalid"),
        (
            {"t": "si", "v": 1, "i": SAGUR_INTERACTION_ID_MAX + 1, "a": "l"},
            "interaction_id_invalid",
        ),
        ({"t": "si", "v": 1, "i": 1, "a": True}, "payload_action_invalid"),
        ({"t": "si", "v": 1, "i": 1, "a": "x"}, "payload_action_invalid"),
        ({"t": "si", "v": 2, "i": 1, "a": "l"}, "payload_action_invalid"),
        ({"t": "si", "v": 2, "i": 1, "a": "lmd"}, "payload_action_invalid"),
        ({"t": "si", "v": 2, "i": 1, "a": "ldmldm"}, "payload_action_invalid"),
    ],
)
def test_declared_sagur_payload_rejects_contract_violations(
    raw_payload: Any,
    error_code: str,
) -> None:
    with pytest.raises(SagurButtonPayloadError) as error:
        parse_sagur_button_payload(raw_payload)

    assert error.value.code == error_code


def test_duplicate_json_key_is_rejected() -> None:
    raw_payload = '{"t":"si","v":1,"i":1,"a":"l","a":"d"}'

    with pytest.raises(SagurButtonPayloadError) as error:
        parse_sagur_button_payload(raw_payload)

    assert error.value.code == "duplicate_json_key"


def test_platform_byte_limit_is_applied_to_actual_utf8_body() -> None:
    raw_payload = _payload(interaction_id=SAGUR_INTERACTION_ID_MAX, action="l")

    with pytest.raises(SagurButtonPayloadError) as error:
        parse_sagur_button_payload(raw_payload, max_bytes=len(raw_payload.encode("utf-8")) - 1)

    assert error.value.code == "payload_too_large"


@pytest.mark.parametrize("action", ["ldm", "dlm", "mld", "ldc", "dlc", "cld"])
def test_maximum_version_2_payload_fits_telegram_limit(action: str) -> None:
    raw_payload = _payload(
        version=2,
        interaction_id=SAGUR_INTERACTION_ID_MAX,
        action=action,
    )

    assert len(raw_payload.encode("utf-8")) <= 64
    assert parse_sagur_button_payload(raw_payload, max_bytes=64) is not None
