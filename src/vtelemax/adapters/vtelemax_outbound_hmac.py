"""Общие правила подписи исходящих запросов vtelemax в SAGUR."""

from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlsplit


def build_vtelemax_outbound_canonical_string(
    *,
    method: str,
    path: str,
    timestamp: str,
    payload_body: bytes,
) -> str:
    """Собирает каноническую строку из фактических байтов тела запроса."""

    body_hash = hashlib.sha256(payload_body).hexdigest()
    return "\n".join((method.upper(), path, timestamp, body_hash))


def build_vtelemax_outbound_signature(
    *,
    secret: str,
    method: str,
    path: str,
    timestamp: str,
    payload_body: bytes,
) -> str:
    """Возвращает шестнадцатеричную подпись HMAC-SHA256 запроса."""

    canonical = build_vtelemax_outbound_canonical_string(
        method=method,
        path=path,
        timestamp=timestamp,
        payload_body=payload_body,
    )
    return hmac.new(
        secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def canonical_request_path(endpoint: str, *, default_path: str) -> str:
    """Извлекает путь и строку запроса для канонической подписи."""

    parsed = urlsplit(endpoint)
    path = parsed.path or default_path
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path
