"""Тесты вспомогательных функций MAX-роутера."""

from __future__ import annotations

from types import SimpleNamespace

from vtelemax.adapters.max.router import (
    _extract_callback_message_id,
    _extract_max_upload_token,
    _extract_contact_attachment,
    _extract_phone_from_vcf,
    _is_message_not_modified_error,
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
