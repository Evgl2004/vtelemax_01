"""Подпись и проверка ссылок VK Mini App для подтверждения телефона."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from urllib import parse


def build_vk_phone_verification_signature(
    *,
    vk_user_id: int,
    issued_at: int,
    secret: str,
) -> str:
    """Строит HMAC-подпись ссылки подтверждения телефона."""

    payload = f"{int(vk_user_id)}:{int(issued_at)}"
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def verify_vk_phone_verification_signature(
    *,
    vk_user_id: int,
    issued_at: int,
    signature: str,
    secret: str,
    max_age_seconds: int,
    now_ts: int | None = None,
    max_clock_skew_seconds: int = 60,
) -> bool:
    """Проверяет подпись и временное окно валидности ссылки."""

    safe_now = int(now_ts if now_ts is not None else time.time())
    safe_issued_at = int(issued_at)
    if safe_issued_at > safe_now + max_clock_skew_seconds:
        return False
    if safe_now - safe_issued_at > int(max_age_seconds):
        return False

    expected = build_vk_phone_verification_signature(
        vk_user_id=int(vk_user_id),
        issued_at=safe_issued_at,
        secret=secret,
    )
    return hmac.compare_digest(expected, str(signature))


def build_vk_phone_verification_link(
    *,
    base_url: str,
    vk_user_id: int,
    secret: str,
    issued_at: int | None = None,
) -> str:
    """Формирует ссылку Mini App с подписью для конкретного VK пользователя."""

    safe_issued_at = int(issued_at if issued_at is not None else time.time())
    safe_uid = int(vk_user_id)
    signature = build_vk_phone_verification_signature(
        vk_user_id=safe_uid,
        issued_at=safe_issued_at,
        secret=secret,
    )

    parsed = parse.urlsplit(base_url.strip())
    query = dict(parse.parse_qsl(parsed.query, keep_blank_values=True))
    query["uid"] = str(safe_uid)
    query["ts"] = str(safe_issued_at)
    query["sig"] = signature

    return parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parse.urlencode(query),
            parsed.fragment,
        )
    )

