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
)


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
