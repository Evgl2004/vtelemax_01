"""Тесты вспомогательных функций MAX-роутера."""

from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace

import pytest

from vtelemax.adapters.max.identity_adapter import MaxAdapterResponse
from vtelemax.adapters.max.router import (
    _extract_callback_message_id,
    _extract_max_upload_token,
    _extract_contact_attachment,
    _extract_contact_attachment_details,
    _extract_phone_from_vcf,
    _is_message_not_modified_error,
    _send_response,
    _verify_max_contact_hash,
    register_max_guest_handlers,
)


class _RouterStub:
    """Минимальный router для проверки зарегистрированного MAX handler."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def _register(self, name: str):
        def decorator(func):
            self.handlers[name] = func
            return func

        return decorator

    def message_created(self):
        return self._register("message_created")

    def bot_started(self):
        return self._register("bot_started")

    def message_callback(self):
        return self._register("message_callback")


class _AdapterStub:
    """Минимальный adapter, фиксирующий входящие контакты без core-сценария."""

    def __init__(self) -> None:
        self.incoming_calls: list[dict[str, object]] = []

    def handle_start(self, max_user_id: int) -> MaxAdapterResponse:
        return MaxAdapterResponse(text=f"start:{max_user_id}")

    def handle_incoming(
        self,
        max_user_id: int,
        text: str,
        payload: object | None,
        contact_phone: str | None = None,
    ) -> MaxAdapterResponse:
        self.incoming_calls.append(
            {
                "max_user_id": max_user_id,
                "text": text,
                "payload": payload,
                "contact_phone": contact_phone,
            }
        )
        return MaxAdapterResponse(text="ok")


def test_extract_contact_attachment_reads_body_contact_phone() -> None:
    """Проверяет извлечение номера из event.message.body.contact.phone_number."""

    event = SimpleNamespace(
        message=SimpleNamespace(
            body=SimpleNamespace(
                contact=SimpleNamespace(phone_number="+79123456789"),
                attachments=[],
            )
        )
    )

    result = _extract_contact_attachment(event)

    assert result == "+79123456789"


def test_extract_contact_attachment_reads_vcf_phone_from_attachment() -> None:
    """Проверяет fallback-извлечение номера из contact-вложения с vcf_info."""

    event = SimpleNamespace(
        message=SimpleNamespace(
            body=SimpleNamespace(
                attachments=[
                    SimpleNamespace(
                        type="contact",
                        payload=SimpleNamespace(
                            vcf_info="BEGIN:VCARD\nVERSION:3.0\nTEL;TYPE=CELL:+7 (912) 345-67-89\nEND:VCARD"
                        ),
                    )
                ]
            )
        )
    )

    result = _extract_contact_attachment(event)

    assert result == "+79123456789"


def test_extract_contact_attachment_data_reads_hash_and_owner() -> None:
    """Проверяет извлечение hash/max_info.user_id из contact-вложения MAX."""

    event = SimpleNamespace(
        message=SimpleNamespace(
            body=SimpleNamespace(
                attachments=[
                    SimpleNamespace(
                        type="contact",
                        payload=SimpleNamespace(
                            vcf_info="BEGIN:VCARD\r\nVERSION:3.0\r\nTEL;TYPE=CELL:+7 (912) 345-67-89\r\nEND:VCARD\r\n",
                            hash="abc123",
                            max_info=SimpleNamespace(user_id=555001),
                        ),
                    )
                ]
            )
        )
    )

    result = _extract_contact_attachment_details(event)

    assert result is not None
    assert result.phone_number == "+79123456789"
    assert result.contact_hash == "abc123"
    assert result.max_user_id == 555001


def test_extract_contact_attachment_data_prefers_attachment_meta_when_body_contact_exists() -> None:
    """Проверяет, что при body.contact + attachment берутся hash/max_info из attachment."""

    event = SimpleNamespace(
        message=SimpleNamespace(
            body=SimpleNamespace(
                contact=SimpleNamespace(phone_number="+79123456789"),
                attachments=[
                    SimpleNamespace(
                        type="contact",
                        payload=SimpleNamespace(
                            vcf_info="BEGIN:VCARD\r\nVERSION:3.0\r\nTEL;TYPE=CELL:+7 (912) 345-67-89\r\nEND:VCARD\r\n",
                            hash="hash-from-attachment",
                            max_info=SimpleNamespace(user_id=777001),
                        ),
                    )
                ],
            )
        )
    )

    result = _extract_contact_attachment_details(event)

    assert result is not None
    assert result.phone_number == "+79123456789"
    assert result.contact_hash == "hash-from-attachment"
    assert result.max_user_id == 777001
    assert result.phone_source == "payload.vcf_info"


def test_extract_contact_attachment_data_uses_body_phone_with_attachment_meta_without_vcf() -> None:
    """Проверяет fallback: phone из body.contact, а hash/max_info из payload без vcf_info."""

    event = SimpleNamespace(
        message=SimpleNamespace(
            body=SimpleNamespace(
                contact=SimpleNamespace(phone_number="+79001234567"),
                attachments=[
                    SimpleNamespace(
                        type="contact",
                        payload=SimpleNamespace(
                            hash="hash-without-vcf",
                            max_info=SimpleNamespace(user_id=900100),
                        ),
                    )
                ],
            )
        )
    )

    result = _extract_contact_attachment_details(event)

    assert result is not None
    assert result.phone_number == "+79001234567"
    assert result.contact_hash == "hash-without-vcf"
    assert result.vcf_info is None
    assert result.max_user_id == 900100
    assert result.phone_source == "body.contact+payload.meta"


def test_extract_contact_attachment_data_reads_hash_from_legacy_alias() -> None:
    """Проверяет извлечение hash из альтернативного имени поля contactHash."""

    event = SimpleNamespace(
        message=SimpleNamespace(
            body=SimpleNamespace(
                attachments=[
                    {
                        "type": "contact",
                        "payload": {
                            "vcf_info": "BEGIN:VCARD\nTEL:+79123456789\nEND:VCARD\n",
                            "contactHash": "hash-from-alias",
                            "max_info": {"user_id": "555001"},
                        },
                    }
                ]
            )
        )
    )

    result = _extract_contact_attachment_details(event)

    assert result is not None
    assert result.contact_hash == "hash-from-alias"
    assert result.contact_hash_source == "payload.contactHash"
    assert result.contact_hash_present_paths == ("payload.contactHash",)
    assert result.max_user_id == 555001


def test_extract_contact_attachment_data_reads_hash_from_raw_update() -> None:
    """Проверяет fallback на raw update, если SDK-модель потеряла payload.hash."""

    event = SimpleNamespace(
        message=SimpleNamespace(
            body=SimpleNamespace(
                mid="mid.1",
                attachments=[
                    SimpleNamespace(
                        type="contact",
                        payload=SimpleNamespace(
                            vcf_info="BEGIN:VCARD\nTEL:+79123456789\nEND:VCARD\n",
                            max_info=SimpleNamespace(user_id=555001),
                        ),
                    )
                ],
            )
        )
    )
    setattr(
        event,
        "_vtelemax_raw_update",
        {
            "update_type": "message_created",
            "message": {
                "body": {
                    "mid": "mid.1",
                    "attachments": [
                        {
                            "type": "contact",
                            "payload": {
                                "vcf_info": "BEGIN:VCARD\nTEL:+79123456789\nEND:VCARD\n",
                                "hash": "hash-from-raw",
                                "max_info": {"user_id": 555001},
                            },
                        }
                    ],
                }
            },
        },
    )

    result = _extract_contact_attachment_details(event)

    assert result is not None
    assert result.contact_hash == "hash-from-raw"
    assert result.contact_hash_source == "raw.payload.hash"
    assert result.contact_hash_present_paths == ("raw.payload.hash",)
    assert result.max_user_id == 555001


def test_verify_max_contact_hash_accepts_crlf_and_lf_variants() -> None:
    """Проверяет устойчивую верификацию hash при отличиях переносов строк в vcf_info."""

    token = "test-token"
    vcf_crlf = "BEGIN:VCARD\r\nVERSION:3.0\r\nTEL;TYPE=CELL:+79123456789\r\nEND:VCARD\r\n"
    expected_hash = hmac.new(
        token.encode("utf-8"),
        vcf_crlf.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    vcf_lf = vcf_crlf.replace("\r\n", "\n")

    assert _verify_max_contact_hash(
        access_token=token,
        vcf_info=vcf_crlf,
        provided_hash=expected_hash,
    )
    assert _verify_max_contact_hash(
        access_token=token,
        vcf_info=vcf_lf,
        provided_hash=expected_hash,
    )


def test_verify_max_contact_hash_rejects_invalid_signature() -> None:
    """Проверяет отклонение невалидного hash."""

    assert not _verify_max_contact_hash(
        access_token="test-token",
        vcf_info="BEGIN:VCARD\r\nTEL:+79123456789\r\nEND:VCARD\r\n",
        provided_hash="deadbeef",
    )


def test_extract_contact_attachment_returns_none_for_invalid_payload() -> None:
    """Проверяет грязный сценарий: невалидное contact-вложение без телефона."""

    event = SimpleNamespace(
        message=SimpleNamespace(
            body=SimpleNamespace(
                attachments=[SimpleNamespace(type="contact", payload=SimpleNamespace(vcf_info="BEGIN:VCARD\nEND:VCARD"))]
            )
        )
    )

    result = _extract_contact_attachment(event)

    assert result is None


def test_extract_phone_from_vcf_returns_none_when_tel_absent() -> None:
    """Проверяет, что helper корректно возвращает None без TEL-поля."""

    result = _extract_phone_from_vcf("BEGIN:VCARD\nVERSION:3.0\nEND:VCARD")

    assert result is None


def test_is_message_not_modified_error_detects_known_patterns() -> None:
    """Проверяет распознавание служебной ошибки «сообщение не изменилось»."""

    assert _is_message_not_modified_error(RuntimeError("Message is not modified"))
    assert _is_message_not_modified_error(RuntimeError("message is same as before"))


def test_is_message_not_modified_error_returns_false_for_other_errors() -> None:
    """Проверяет, что посторонние ошибки не считаются «not modified»."""

    assert not _is_message_not_modified_error(RuntimeError("forbidden"))


def test_extract_max_upload_token_reads_token_from_photos_payload() -> None:
    """Проверяет извлечение токена из формата `photos` ответа upload API."""

    token = _extract_max_upload_token({"photos": {"photo_1": {"token": "token-1"}}})

    assert token == "token-1"


def test_extract_max_upload_token_returns_none_for_dirty_payload() -> None:
    """Проверяет dirty-сценарий: без токена функция возвращает None."""

    token = _extract_max_upload_token({"photos": {"photo_1": {}}})

    assert token is None


def test_extract_callback_message_id_returns_string_mid_as_is() -> None:
    """Проверяет поддержку строкового `mid` из callback-события MAX."""

    event = SimpleNamespace(
        callback=SimpleNamespace(payload="support"),
        message=SimpleNamespace(body=SimpleNamespace(mid="mid.000000000b3fa41d019d3c5701b319ae")),
    )

    callback_mid = _extract_callback_message_id(event)

    assert callback_mid == "mid.000000000b3fa41d019d3c5701b319ae"


def test_extract_callback_message_id_returns_int_mid_without_conversion_errors() -> None:
    """Проверяет, что числовой `mid` также корректно возвращается helper-ом."""

    event = SimpleNamespace(
        callback=SimpleNamespace(payload="support"),
        message=SimpleNamespace(body=SimpleNamespace(mid=12345)),
    )

    callback_mid = _extract_callback_message_id(event)

    assert callback_mid == 12345


@pytest.mark.asyncio
async def test_message_handler_keeps_contact_when_hash_missing_in_shadow_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Проверяет, что shadow-режим не блокирует контакт без hash."""

    monkeypatch.setattr(
        "vtelemax.adapters.max.router._patch_maxapi_raw_update_preservation",
        lambda: False,
    )
    router = _RouterStub()
    adapter = _AdapterStub()
    register_max_guest_handlers(
        router,
        adapter,  # type: ignore[arg-type]
        max_contact_strict_hash_enabled=False,
        max_contact_hash_shadow_mode_enabled=True,
    )
    event = SimpleNamespace(
        from_user=SimpleNamespace(user_id=555001),
        message=SimpleNamespace(
            body=SimpleNamespace(
                text="",
                attachments=[
                    SimpleNamespace(
                        type="contact",
                        payload=SimpleNamespace(
                            vcf_info="BEGIN:VCARD\nTEL:+79123456789\nEND:VCARD\n",
                            max_info=SimpleNamespace(user_id=555001),
                        ),
                    )
                ],
            )
        ),
    )

    await router.handlers["message_created"](event)  # type: ignore[operator]

    assert adapter.incoming_calls == [
        {
            "max_user_id": 555001,
            "text": "",
            "payload": None,
            "contact_phone": "+79123456789",
        }
    ]


@pytest.mark.asyncio
async def test_message_handler_uses_raw_hash_when_strict_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Проверяет, что strict пропускает контакт, если hash найден в raw update."""

    verified_calls: list[dict[str, str]] = []

    def _verify_stub(*, access_token: str, vcf_info: str, provided_hash: str) -> bool:
        verified_calls.append(
            {
                "access_token": access_token,
                "vcf_info": vcf_info,
                "provided_hash": provided_hash,
            }
        )
        return True

    monkeypatch.setattr(
        "vtelemax.adapters.max.router._patch_maxapi_raw_update_preservation",
        lambda: False,
    )
    monkeypatch.setattr("vtelemax.adapters.max.router._verify_max_contact_hash", _verify_stub)
    router = _RouterStub()
    adapter = _AdapterStub()
    register_max_guest_handlers(
        router,
        adapter,  # type: ignore[arg-type]
        max_bot_token="token",
        max_contact_strict_hash_enabled=True,
        max_contact_hash_shadow_mode_enabled=True,
    )
    event = SimpleNamespace(
        from_user=SimpleNamespace(user_id=555001),
        message=SimpleNamespace(
            body=SimpleNamespace(
                text="",
                mid="mid.1",
                attachments=[
                    SimpleNamespace(
                        type="contact",
                        payload=SimpleNamespace(
                            vcf_info="BEGIN:VCARD\nTEL:+79123456789\nEND:VCARD\n",
                            max_info=SimpleNamespace(user_id=555001),
                        ),
                    )
                ],
            )
        ),
    )
    setattr(
        event,
        "_vtelemax_raw_update",
        {
            "update_type": "message_created",
            "message": {
                "body": {
                    "mid": "mid.1",
                    "attachments": [
                        {
                            "type": "contact",
                            "payload": {
                                "vcf_info": "BEGIN:VCARD\nTEL:+79123456789\nEND:VCARD\n",
                                "hash": "raw-good-hash",
                                "max_info": {"user_id": 555001},
                            },
                        }
                    ],
                }
            },
        },
    )

    await router.handlers["message_created"](event)  # type: ignore[operator]

    assert verified_calls == [
        {
            "access_token": "token",
            "vcf_info": "BEGIN:VCARD\nTEL:+79123456789\nEND:VCARD\n",
            "provided_hash": "raw-good-hash",
        }
    ]
    assert adapter.incoming_calls[-1]["contact_phone"] == "+79123456789"


@pytest.mark.asyncio
async def test_send_response_supports_html_parse_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверяет, что MAX-роутер пробрасывает html parse mode в send_message."""

    sent_calls: list[dict[str, object]] = []

    class _BotStub:
        async def send_message(self, **kwargs: object) -> None:
            sent_calls.append(kwargs)

    monkeypatch.setattr("vtelemax.adapters.max.router._resolve_html_parse_mode", lambda: "HTML_MODE")

    event = SimpleNamespace(bot=_BotStub(), chat_id=188720157)
    response = MaxAdapterResponse(text="<b>Тест</b>", parse_mode="html")

    await _send_response(event, response)

    assert len(sent_calls) == 1
    assert sent_calls[0]["parse_mode"] == "HTML_MODE"
