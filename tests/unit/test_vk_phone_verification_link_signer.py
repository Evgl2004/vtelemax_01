"""Тесты подписи ссылок VK Mini App подтверждения телефона."""

from __future__ import annotations

from urllib import parse

from vtelemax.infrastructure import (
    build_vk_phone_verification_link,
    verify_vk_phone_verification_signature,
)


def test_vk_phone_verification_link_contains_signed_params() -> None:
    """Проверяет, что ссылка содержит uid/ts/sig и сохраняет исходные query-параметры."""

    link = build_vk_phone_verification_link(
        base_url="https://example.org/vk-miniapp?foo=bar",
        vk_user_id=1069961024,
        secret="secret",
        issued_at=1700000000,
    )
    parsed = parse.urlsplit(link)
    query = dict(parse.parse_qsl(parsed.query, keep_blank_values=True))

    assert parsed.scheme == "https"
    assert parsed.netloc == "example.org"
    assert parsed.path == "/vk-miniapp"
    assert query["foo"] == "bar"
    assert query["uid"] == "1069961024"
    assert query["ts"] == "1700000000"
    assert query["sig"]


def test_verify_vk_phone_verification_signature_accepts_valid_signature() -> None:
    """Проверяет, что корректная подпись проходит валидацию по времени и payload."""

    link = build_vk_phone_verification_link(
        base_url="https://example.org/vk-miniapp",
        vk_user_id=12345,
        secret="secret",
        issued_at=1700000000,
    )
    query = dict(parse.parse_qsl(parse.urlsplit(link).query, keep_blank_values=True))
    is_valid = verify_vk_phone_verification_signature(
        vk_user_id=12345,
        issued_at=int(query["ts"]),
        signature=query["sig"],
        secret="secret",
        max_age_seconds=900,
        now_ts=1700000100,
    )

    assert is_valid is True


def test_verify_vk_phone_verification_signature_rejects_expired_or_invalid() -> None:
    """Проверяет отбрасывание просроченных и подмененных подписей."""

    link = build_vk_phone_verification_link(
        base_url="https://example.org/vk-miniapp",
        vk_user_id=12345,
        secret="secret",
        issued_at=1700000000,
    )
    query = dict(parse.parse_qsl(parse.urlsplit(link).query, keep_blank_values=True))

    assert (
        verify_vk_phone_verification_signature(
            vk_user_id=12345,
            issued_at=int(query["ts"]),
            signature="tampered",
            secret="secret",
            max_age_seconds=900,
            now_ts=1700000100,
        )
        is False
    )
    assert (
        verify_vk_phone_verification_signature(
            vk_user_id=12345,
            issued_at=int(query["ts"]),
            signature=query["sig"],
            secret="secret",
            max_age_seconds=900,
            now_ts=1700002000,
        )
        is False
    )

