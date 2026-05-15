"""Точка входа отдельного read-only API сервиса интеграции с SAGUR."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import signal
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from aiohttp import web
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from vtelemax.infrastructure import configure_logging
from vtelemax.infrastructure.postgres import (
    CouponAlreadyAssignedError,
    PersonRow,
    PhoneRow,
    SQLAlchemySagurCouponsRepository,
    SQLAlchemySagurRecipientsRepository,
    build_engine,
    build_session_factory,
)
from vtelemax.settings import AppSettings

_COMPONENT = "sagur_integration_api_app"
_MAX_JSON_BODY_BYTES = 512 * 1024
_SETTINGS_KEY = web.AppKey("settings", AppSettings)
_SESSION_FACTORY_KEY = web.AppKey("session_factory", sessionmaker[Session])
_REQUEST_ID_KEY = web.AppKey("request_id", str)
_AUDIT_ROWS_KEY = web.AppKey("audit_rows", int)
_AUDIT_SINCE_KEY = web.AppKey("audit_since", str | None)
_AUDIT_CURSOR_HASH_KEY = web.AppKey("audit_cursor_hash", str | None)
_METRICS_KEY = web.AppKey("metrics", dict[str, float])
_SAGUR_PATH_PREFIX = "/internal/integration/v1/sagur/"
_H_TIMESTAMP = "X-Sagur-Timestamp"
_H_SIGNATURE = "X-Sagur-Signature"
_H_REQUEST_ID = "X-Request-Id"
_H_SAGUR_REQUEST_ID = "X-Sagur-Request-Id"
_H_EVENT_ID = "X-Sagur-Event-Id"
_CURSOR_SIG_PREFIX = "cursor\n"
_COUPON_DIRECTIONS = {"assignments", "status_update"}
_COUPON_BATCH_ACK_STATUSES = {"acked"}


@dataclass(frozen=True, slots=True)
class SnapshotCursor:
    """Позиция пагинации snapshot выдачи."""

    account_created_at: datetime
    person_id: str
    platform: str
    limit: int


@dataclass(frozen=True, slots=True)
class DeltaCursor:
    """Позиция пагинации delta выдачи."""

    since: datetime
    effective_updated_at: datetime
    person_id: str
    platform: str
    limit: int


@dataclass(frozen=True, slots=True)
class AuthError:
    """Ошибка проверки подписи интеграционного запроса."""

    status: int
    message: str


def build_postgres_session_factory(settings: AppSettings) -> sessionmaker[Session]:
    """Создает PostgreSQL session factory для SAGUR integration API."""

    engine = build_engine(settings.postgres_sqlalchemy_dsn, echo=settings.postgres_echo)
    return build_session_factory(engine)


def _json_response_ok(payload: dict[str, Any]) -> web.Response:
    return web.json_response(payload, status=200)


def _json_response_error(*, status: int, message: str) -> web.Response:
    return web.json_response({"status": "error", "message": message}, status=status)


def _is_sagur_protected_path(path: str) -> bool:
    """Определяет, требует ли path обязательную S2S-аутентификацию."""

    return path.startswith(_SAGUR_PATH_PREFIX)


def _build_hmac_payload(
    *,
    method: str,
    path_qs: str,
    timestamp: int,
    body_sha256: str | None = None,
) -> str:
    """Собирает canonical payload для проверки HMAC подписи."""

    if body_sha256 is not None:
        return f"{method.upper()}\n{path_qs}\n{timestamp}\n{body_sha256}"
    return f"{method.upper()}\n{path_qs}\n{timestamp}"


def _build_hmac_signature(*, secret: str, payload: str) -> str:
    """Строит hex sha256 HMAC подпись."""

    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


def _hash_for_log(raw_value: str | None) -> str | None:
    """Возвращает короткий безопасный hash для логирования чувствительных параметров."""

    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _build_metrics_state() -> dict[str, float]:
    """Инициализирует in-memory метрики интеграционного API."""

    return {
        "requests_total": 0.0,
        "request_latency_seconds_sum": 0.0,
        "request_latency_seconds_count": 0.0,
        "rows_returned_total": 0.0,
        "auth_failures_total": 0.0,
        "coupon_events_total": 0.0,
        "coupon_events_success_total": 0.0,
        "coupon_events_error_total": 0.0,
        "coupon_events_dedup_total": 0.0,
        "coupon_event_latency_seconds_sum": 0.0,
        "coupon_event_latency_seconds_count": 0.0,
    }


def _metrics_record_request(*, app: web.Application, latency_seconds: float, rows: int = 0) -> None:
    """Обновляет счетчики запросов/латентности/строк в ответе."""

    metrics = app[_METRICS_KEY]
    metrics["requests_total"] += 1
    metrics["request_latency_seconds_sum"] += max(latency_seconds, 0.0)
    metrics["request_latency_seconds_count"] += 1
    metrics["rows_returned_total"] += max(rows, 0)


def _metrics_record_coupon_event(
    *,
    app: web.Application,
    latency_seconds: float,
    success: bool,
    deduplicated: bool,
) -> None:
    """Обновляет счетчики обработки входящих coupon-событий."""

    metrics = app[_METRICS_KEY]
    metrics["coupon_events_total"] += 1
    metrics["coupon_event_latency_seconds_sum"] += max(latency_seconds, 0.0)
    metrics["coupon_event_latency_seconds_count"] += 1
    if success:
        metrics["coupon_events_success_total"] += 1
    else:
        metrics["coupon_events_error_total"] += 1
    if deduplicated:
        metrics["coupon_events_dedup_total"] += 1


def _resolve_request_id(request: web.Request) -> str:
    """Возвращает request id из заголовка или генерирует новый."""

    raw_request_id = str(
        request.headers.get(_H_SAGUR_REQUEST_ID) or request.headers.get(_H_REQUEST_ID) or ""
    ).strip()
    if raw_request_id:
        return raw_request_id[:128]
    return uuid.uuid4().hex


def _resolve_caller_ip(request: web.Request) -> str:
    """Определяет IP вызывающей стороны для аудит-логов."""

    x_real_ip = str(request.headers.get("X-Real-IP") or "").strip()
    if x_real_ip:
        return x_real_ip
    return str(request.remote or "-")


def _validate_hmac_auth(
    *,
    request: web.Request,
    settings: AppSettings,
    now_epoch: int | None = None,
    raw_body: bytes | None = None,
) -> AuthError | None:
    """Проверяет S2S подпись интеграционного запроса."""

    secret = settings.sagur_integration_hmac_secret.strip()
    if not secret:
        return AuthError(
            status=503,
            message="Сервис интеграции временно недоступен: не настроен HMAC секрет.",
        )

    timestamp_raw = str(request.headers.get(_H_TIMESTAMP) or "").strip()
    signature_raw = str(request.headers.get(_H_SIGNATURE) or "").strip().lower()
    if not timestamp_raw or not signature_raw:
        return AuthError(
            status=401,
            message="Не переданы обязательные заголовки интеграционной авторизации.",
        )

    try:
        timestamp = int(timestamp_raw)
    except ValueError:
        return AuthError(status=401, message="Некорректный формат X-Sagur-Timestamp.")

    current_epoch = int(time.time()) if now_epoch is None else int(now_epoch)
    if abs(current_epoch - timestamp) > settings.sagur_integration_hmac_max_skew_seconds:
        return AuthError(status=401, message="Подпись просрочена или время запроса недопустимо.")

    payloads = [
        _build_hmac_payload(
            method=request.method,
            path_qs=request.path_qs,
            timestamp=timestamp,
        )
    ]
    if raw_body is not None:
        body_sha256 = hashlib.sha256(raw_body).hexdigest()
        payloads.append(
            _build_hmac_payload(
                method=request.method,
                path_qs=request.path,
                timestamp=timestamp,
                body_sha256=body_sha256,
            )
        )

    expected_signatures = (
        _build_hmac_signature(secret=secret, payload=payload).lower() for payload in payloads
    )
    if not any(
        hmac.compare_digest(expected_signature, signature_raw)
        for expected_signature in expected_signatures
    ):
        return AuthError(status=401, message="Неверная подпись интеграционного запроса.")
    return None


@web.middleware
async def _sagur_auth_middleware(
    request: web.Request,
    handler: Any,
) -> web.StreamResponse:
    """Middleware обязательной S2S авторизации для SAGUR endpoint."""

    request_id = _resolve_request_id(request)
    request[_REQUEST_ID_KEY] = request_id
    if not _is_sagur_protected_path(request.path):
        return await handler(request)

    started_at = time.perf_counter()

    settings = request.app[_SETTINGS_KEY]
    raw_body = await request.read() if request.can_read_body else b""
    auth_error = _validate_hmac_auth(request=request, settings=settings, raw_body=raw_body)
    if auth_error is not None:
        latency_seconds = time.perf_counter() - started_at
        _metrics_record_request(app=request.app, latency_seconds=latency_seconds)
        request.app[_METRICS_KEY]["auth_failures_total"] += 1
        logger.bind(component=_COMPONENT, stage="integration_audit").warning(
            "Запрос отклонен по авторизации. request_id={request_id}, caller_ip={caller_ip}, endpoint={endpoint}, status={status}.",
            request_id=request_id,
            caller_ip=_resolve_caller_ip(request),
            endpoint=request.path_qs,
            status=auth_error.status,
        )
        return _json_response_error(status=auth_error.status, message=auth_error.message)
    response = await handler(request)

    latency_ms = (time.perf_counter() - started_at) * 1000
    rows = request.get(_AUDIT_ROWS_KEY)
    _metrics_record_request(
        app=request.app,
        latency_seconds=latency_ms / 1000.0,
        rows=rows if isinstance(rows, int) else 0,
    )
    logger.bind(component=_COMPONENT, stage="integration_audit").info(
        "Интеграционный запрос обработан. request_id={request_id}, caller_ip={caller_ip}, endpoint={endpoint}, "
        "since={since}, cursor_hash={cursor_hash}, rows={rows}, status={status}, latency_ms={latency_ms:.2f}.",
        request_id=request_id,
        caller_ip=_resolve_caller_ip(request),
        endpoint=request.path_qs,
        since=request.get(_AUDIT_SINCE_KEY),
        cursor_hash=request.get(_AUDIT_CURSOR_HASH_KEY),
        rows=request.get(_AUDIT_ROWS_KEY),
        status=response.status,
        latency_ms=latency_ms,
    )
    return response


def _to_rfc3339_utc(value: datetime | None) -> str | None:
    """Сериализует datetime в RFC3339 UTC формат."""

    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_cursor_hmac_secret(settings: AppSettings) -> str:
    """Возвращает HMAC-секрет для подписи cursor.

    Примечание:
    если секрет пустой, внешний доступ к endpoint всё равно блокируется middleware
    с 503, а fallback нужен для unit-тестов прямого вызова handler.
    """

    secret = settings.sagur_integration_hmac_secret.strip()
    if secret:
        return secret
    return "__local-dev-cursor-secret__"


def _sign_cursor_payload(*, encoded_payload: str, secret: str) -> str:
    """Подписывает cursor-полезную нагрузку и возвращает opaque signed cursor."""

    signature = _build_hmac_signature(
        secret=secret,
        payload=f"{_CURSOR_SIG_PREFIX}{encoded_payload}",
    ).lower()
    return f"{encoded_payload}.{signature}"


def _extract_signed_cursor_payload(*, raw_cursor: str, secret: str) -> tuple[str, bool]:
    """Извлекает полезную нагрузку из signed cursor.

    Возвращает:
    - payload cursor;
    - флаг signed (True/False).

    Legacy-режим:
    - cursor без подписи (без '.'): допускаем как v1 cursor для обратной совместимости.
    """

    if "." not in raw_cursor:
        return raw_cursor, False

    payload, signature = raw_cursor.rsplit(".", 1)
    payload = payload.strip()
    signature = signature.strip().lower()
    if not payload or not signature:
        raise ValueError("Некорректный cursor.")

    expected_signature = _build_hmac_signature(
        secret=secret,
        payload=f"{_CURSOR_SIG_PREFIX}{payload}",
    ).lower()
    if not hmac.compare_digest(expected_signature, signature):
        raise ValueError("Некорректный cursor.")
    return payload, True


def _parse_rfc3339_utc(value: str) -> datetime:
    """Парсит RFC3339 строку в aware-datetime UTC."""

    raw_value = value.strip()
    if raw_value.endswith("Z"):
        raw_value = raw_value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw_value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must contain timezone")
    return parsed.astimezone(timezone.utc)


def _parse_uuid(value: str, *, field_name: str) -> uuid.UUID:
    """Парсит UUID и выбрасывает ValueError с унифицированным текстом."""

    raw_value = value.strip()
    if not raw_value:
        raise ValueError(f"{field_name} is required")
    try:
        return uuid.UUID(raw_value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be valid UUID") from exc


async def _read_json_object_body(request: web.Request) -> dict[str, Any]:
    """Читает JSON-тело запроса и возвращает объект верхнего уровня."""

    raw_body = await request.read()
    if not raw_body:
        raise ValueError("Пустое тело запроса.")
    if len(raw_body) > _MAX_JSON_BODY_BYTES:
        raise ValueError("Тело запроса слишком большое.")
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Некорректный JSON в теле запроса.") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON должен быть объектом.")
    return payload


def _encode_snapshot_cursor(cursor: SnapshotCursor) -> str:
    """Кодирует snapshot cursor в opaque строку."""

    payload = {
        "v": 2,
        "t": "snapshot",
        "account_created_at": _to_rfc3339_utc(cursor.account_created_at),
        "person_id": cursor.person_id,
        "platform": cursor.platform,
        "limit": cursor.limit,
    }
    json_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(json_bytes).decode("ascii")
    return encoded.rstrip("=")


def _decode_snapshot_cursor(raw_cursor: str, *, fallback_limit: int | None = None) -> SnapshotCursor:
    """Декодирует opaque cursor и валидирует структуру."""

    try:
        padded = raw_cursor + "=" * (-len(raw_cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("cursor payload must be object")

        version = int(payload.get("v"))
        if str(payload.get("t") or "") != "snapshot":
            raise ValueError("unsupported cursor type")

        account_created_at = _parse_rfc3339_utc(str(payload.get("account_created_at") or "").strip())
        person_id = str(payload.get("person_id") or "").strip()
        platform = str(payload.get("platform") or "").strip()
        if version == 1:
            if fallback_limit is None:
                raise ValueError("legacy cursor requires fallback_limit")
            limit = fallback_limit
        elif version == 2:
            limit = int(payload.get("limit"))
        else:
            raise ValueError("unsupported cursor version")

        if not person_id:
            raise ValueError("person_id is empty")
        if platform not in {"telegram", "vk", "max"}:
            raise ValueError("platform is invalid")
        if limit <= 0:
            raise ValueError("limit must be > 0")

        return SnapshotCursor(
            account_created_at=account_created_at,
            person_id=person_id,
            platform=platform,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Некорректный cursor.") from exc


def _encode_delta_cursor(cursor: DeltaCursor) -> str:
    """Кодирует delta cursor в opaque строку."""

    payload = {
        "v": 2,
        "t": "delta",
        "since": _to_rfc3339_utc(cursor.since),
        "effective_updated_at": _to_rfc3339_utc(cursor.effective_updated_at),
        "person_id": cursor.person_id,
        "platform": cursor.platform,
        "limit": cursor.limit,
    }
    json_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(json_bytes).decode("ascii")
    return encoded.rstrip("=")


def _decode_delta_cursor(raw_cursor: str, *, fallback_limit: int | None = None) -> DeltaCursor:
    """Декодирует opaque delta cursor и валидирует структуру."""

    try:
        padded = raw_cursor + "=" * (-len(raw_cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("cursor payload must be object")

        version = int(payload.get("v"))
        if str(payload.get("t") or "") != "delta":
            raise ValueError("unsupported cursor type")

        since = _parse_rfc3339_utc(str(payload.get("since") or "").strip())
        effective_updated_at = _parse_rfc3339_utc(
            str(payload.get("effective_updated_at") or "").strip()
        )
        person_id = str(payload.get("person_id") or "").strip()
        platform = str(payload.get("platform") or "").strip()
        if version == 1:
            if fallback_limit is None:
                raise ValueError("legacy cursor requires fallback_limit")
            limit = fallback_limit
        elif version == 2:
            limit = int(payload.get("limit"))
        else:
            raise ValueError("unsupported cursor version")

        if not person_id:
            raise ValueError("person_id is empty")
        if platform not in {"telegram", "vk", "max"}:
            raise ValueError("platform is invalid")
        if limit <= 0:
            raise ValueError("limit must be > 0")

        return DeltaCursor(
            since=since,
            effective_updated_at=effective_updated_at,
            person_id=person_id,
            platform=platform,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Некорректный cursor.") from exc


def _parse_limit_from_query(*, request: web.Request, settings: AppSettings) -> int:
    """Валидирует query limit в рамках default/max."""

    raw_limit = str(request.query.get("limit") or "").strip()
    if not raw_limit:
        return settings.sagur_integration_default_limit

    try:
        limit = int(raw_limit)
    except ValueError as exc:
        raise ValueError("Параметр limit должен быть целым числом.") from exc

    if limit <= 0:
        raise ValueError("Параметр limit должен быть больше 0.")
    if limit > settings.sagur_integration_max_limit:
        raise ValueError(
            f"Параметр limit превышает максимум {settings.sagur_integration_max_limit}."
        )
    return limit


def _parse_cursor_from_query(
    request: web.Request,
    *,
    settings: AppSettings,
    expected_limit: int,
) -> SnapshotCursor | None:
    """Читает и декодирует snapshot cursor из query."""

    raw_cursor = str(request.query.get("cursor") or "").strip()
    if not raw_cursor:
        return None

    secret = _resolve_cursor_hmac_secret(settings)
    payload, is_signed = _extract_signed_cursor_payload(raw_cursor=raw_cursor, secret=secret)
    cursor = _decode_snapshot_cursor(
        payload,
        fallback_limit=expected_limit if not is_signed else None,
    )
    if cursor.limit != expected_limit:
        raise ValueError("Параметр limit должен совпадать с limit внутри cursor.")
    return cursor


def _parse_since_from_query(request: web.Request) -> datetime:
    """Парсит обязательный параметр since для delta endpoint."""

    raw_since = str(request.query.get("since") or "").strip()
    if not raw_since:
        raise ValueError("Параметр since обязателен и должен быть в формате RFC3339 UTC.")
    try:
        return _parse_rfc3339_utc(raw_since)
    except ValueError as exc:
        raise ValueError("Параметр since должен быть в формате RFC3339 UTC.") from exc


def _parse_delta_cursor_from_query(
    request: web.Request,
    *,
    settings: AppSettings,
    expected_limit: int,
) -> DeltaCursor | None:
    """Читает и декодирует delta cursor из query."""

    raw_cursor = str(request.query.get("cursor") or "").strip()
    if not raw_cursor:
        return None

    secret = _resolve_cursor_hmac_secret(settings)
    payload, is_signed = _extract_signed_cursor_payload(raw_cursor=raw_cursor, secret=secret)
    cursor = _decode_delta_cursor(
        payload,
        fallback_limit=expected_limit if not is_signed else None,
    )
    if cursor.limit != expected_limit:
        raise ValueError("Параметр limit должен совпадать с limit внутри cursor.")
    return cursor


def _extract_snapshot_cursor_from_row(row: Any, *, limit: int) -> SnapshotCursor:
    """Формирует cursor из последней возвращенной строки."""

    account_created_at = row.account_created_at
    if not isinstance(account_created_at, datetime):
        raise ValueError("account_created_at missing in snapshot row")
    return SnapshotCursor(
        account_created_at=account_created_at,
        person_id=row.person_id,
        platform=row.platform,
        limit=limit,
    )


def _extract_delta_cursor_from_row(*, row: Any, since: datetime, limit: int) -> DeltaCursor:
    """Формирует delta cursor из последней строки страницы."""

    effective_updated_at = row.effective_updated_at
    if not isinstance(effective_updated_at, datetime):
        raise ValueError("effective_updated_at missing in delta row")
    return DeltaCursor(
        since=since,
        effective_updated_at=effective_updated_at,
        person_id=row.person_id,
        platform=row.platform,
        limit=limit,
    )


def _fetch_snapshot_page(
    *,
    session_factory: sessionmaker[Session],
    limit: int,
    cursor: SnapshotCursor | None,
    include_vk_pending_verification: bool = False,
) -> tuple[list[dict[str, Any]], str | None]:
    """Вычитывает snapshot-страницу и возвращает next_cursor."""

    with session_factory() as db_session:
        repository = SQLAlchemySagurRecipientsRepository(
            db_session,
            include_vk_pending_verification=include_vk_pending_verification,
        )
        rows = repository.fetch_snapshot_page(
            page_size=limit + 1,
            cursor_account_created_at=cursor.account_created_at if cursor is not None else None,
            cursor_person_id=cursor.person_id if cursor is not None else None,
            cursor_platform=cursor.platform if cursor is not None else None,
        )

    has_more = len(rows) > limit
    page_rows = rows[:limit]

    items: list[dict[str, Any]] = []
    for row in page_rows:
        items.append(
            {
                "person_id": row.person_id,
                "phone_e164": row.phone_e164,
                "platform": row.platform,
                "external_id": row.external_id,
                "rules_accepted": row.rules_accepted,
                "notifications_allowed": row.notifications_allowed,
                "is_registered": row.is_registered,
                "registered_at": _to_rfc3339_utc(row.registered_at),
                "state_updated_at": _to_rfc3339_utc(row.state_updated_at),
                "account_created_at": _to_rfc3339_utc(row.account_created_at),
                "effective_updated_at": _to_rfc3339_utc(row.effective_updated_at),
                "profile": {
                    "first_name": row.profile_first_name,
                    "last_name": row.profile_last_name,
                    "gender": row.profile_gender,
                    "email": row.profile_email,
                    "birthdate": (
                        row.profile_birthdate.isoformat()
                        if row.profile_birthdate is not None
                        else None
                    ),
                },
            }
        )

    if not has_more or not page_rows:
        return items, None

    next_cursor = _encode_snapshot_cursor(
        _extract_snapshot_cursor_from_row(page_rows[-1], limit=limit)
    )
    return items, next_cursor


def _fetch_delta_page(
    *,
    session_factory: sessionmaker[Session],
    since: datetime,
    limit: int,
    cursor: DeltaCursor | None,
    include_vk_pending_verification: bool = False,
) -> tuple[list[dict[str, Any]], str | None, datetime | None]:
    """Вычитывает delta-страницу и возвращает next_cursor и max_seen_updated_at."""

    with session_factory() as db_session:
        repository = SQLAlchemySagurRecipientsRepository(
            db_session,
            include_vk_pending_verification=include_vk_pending_verification,
        )
        rows = repository.fetch_delta_page(
            since=since,
            page_size=limit + 1,
            cursor_effective_updated_at=cursor.effective_updated_at if cursor is not None else None,
            cursor_person_id=cursor.person_id if cursor is not None else None,
            cursor_platform=cursor.platform if cursor is not None else None,
        )

    has_more = len(rows) > limit
    page_rows = rows[:limit]

    items: list[dict[str, Any]] = []
    max_seen_updated_at: datetime | None = None

    for row in page_rows:
        effective_updated_at = row.effective_updated_at
        if isinstance(effective_updated_at, datetime):
            if max_seen_updated_at is None or effective_updated_at > max_seen_updated_at:
                max_seen_updated_at = effective_updated_at

        items.append(
            {
                "person_id": row.person_id,
                "phone_e164": row.phone_e164,
                "platform": row.platform,
                "external_id": row.external_id,
                "rules_accepted": row.rules_accepted,
                "notifications_allowed": row.notifications_allowed,
                "is_registered": row.is_registered,
                "registered_at": _to_rfc3339_utc(row.registered_at),
                "state_updated_at": _to_rfc3339_utc(row.state_updated_at),
                "account_created_at": _to_rfc3339_utc(row.account_created_at),
                "effective_updated_at": _to_rfc3339_utc(
                    effective_updated_at if isinstance(effective_updated_at, datetime) else None
                ),
                "profile": {
                    "first_name": row.profile_first_name,
                    "last_name": row.profile_last_name,
                    "gender": row.profile_gender,
                    "email": row.profile_email,
                    "birthdate": (
                        row.profile_birthdate.isoformat()
                        if row.profile_birthdate is not None
                        else None
                    ),
                },
            }
        )

    if not has_more or not page_rows:
        return items, None, max_seen_updated_at

    next_cursor = _encode_delta_cursor(
        _extract_delta_cursor_from_row(row=page_rows[-1], since=since, limit=limit)
    )
    return items, next_cursor, max_seen_updated_at


def _build_metrics_payload(metrics: dict[str, float]) -> str:
    """Формирует ответ /metrics в формате Prometheus text exposition."""

    requests_total = int(metrics.get("requests_total", 0.0))
    request_latency_sum = float(metrics.get("request_latency_seconds_sum", 0.0))
    request_latency_count = int(metrics.get("request_latency_seconds_count", 0.0))
    rows_returned_total = int(metrics.get("rows_returned_total", 0.0))
    auth_failures_total = int(metrics.get("auth_failures_total", 0.0))
    coupon_events_total = int(metrics.get("coupon_events_total", 0.0))
    coupon_events_success_total = int(metrics.get("coupon_events_success_total", 0.0))
    coupon_events_error_total = int(metrics.get("coupon_events_error_total", 0.0))
    coupon_events_dedup_total = int(metrics.get("coupon_events_dedup_total", 0.0))
    coupon_event_latency_sum = float(metrics.get("coupon_event_latency_seconds_sum", 0.0))
    coupon_event_latency_count = int(metrics.get("coupon_event_latency_seconds_count", 0.0))

    lines = [
        "# HELP sagur_integration_requests_total Total integration API requests.",
        "# TYPE sagur_integration_requests_total counter",
        f"sagur_integration_requests_total {requests_total}",
        "# HELP sagur_integration_request_latency_seconds_sum Accumulated request latency in seconds.",
        "# TYPE sagur_integration_request_latency_seconds_sum counter",
        f"sagur_integration_request_latency_seconds_sum {request_latency_sum:.6f}",
        "# HELP sagur_integration_request_latency_seconds_count Count of latency observations.",
        "# TYPE sagur_integration_request_latency_seconds_count counter",
        f"sagur_integration_request_latency_seconds_count {request_latency_count}",
        "# HELP sagur_integration_rows_returned_total Total rows returned by snapshot/delta endpoints.",
        "# TYPE sagur_integration_rows_returned_total counter",
        f"sagur_integration_rows_returned_total {rows_returned_total}",
        "# HELP sagur_integration_auth_failures_total Total failed auth checks.",
        "# TYPE sagur_integration_auth_failures_total counter",
        f"sagur_integration_auth_failures_total {auth_failures_total}",
        "# HELP sagur_coupon_events_total Total incoming coupon events.",
        "# TYPE sagur_coupon_events_total counter",
        f"sagur_coupon_events_total {coupon_events_total}",
        "# HELP sagur_coupon_events_success_total Total successfully processed coupon events.",
        "# TYPE sagur_coupon_events_success_total counter",
        f"sagur_coupon_events_success_total {coupon_events_success_total}",
        "# HELP sagur_coupon_events_error_total Total failed coupon event processing attempts.",
        "# TYPE sagur_coupon_events_error_total counter",
        f"sagur_coupon_events_error_total {coupon_events_error_total}",
        "# HELP sagur_coupon_events_dedup_total Total deduplicated coupon events.",
        "# TYPE sagur_coupon_events_dedup_total counter",
        f"sagur_coupon_events_dedup_total {coupon_events_dedup_total}",
        "# HELP sagur_coupon_event_latency_seconds_sum Accumulated coupon event processing latency in seconds.",
        "# TYPE sagur_coupon_event_latency_seconds_sum counter",
        f"sagur_coupon_event_latency_seconds_sum {coupon_event_latency_sum:.6f}",
        "# HELP sagur_coupon_event_latency_seconds_count Count of coupon event latency observations.",
        "# TYPE sagur_coupon_event_latency_seconds_count counter",
        f"sagur_coupon_event_latency_seconds_count {coupon_event_latency_count}",
    ]
    return "\n".join(lines) + "\n"


async def _health_handler(request: web.Request) -> web.Response:
    """Health endpoint сервиса."""

    return _json_response_ok({"status": "ok", "service": "sagur-integration-api"})


async def _metrics_handler(request: web.Request) -> web.Response:
    """Prometheus-совместимый endpoint служебных метрик API."""

    payload = _build_metrics_payload(request.app[_METRICS_KEY])
    return web.Response(
        status=200,
        text=payload,
        content_type="text/plain",
    )


async def _snapshot_handler(request: web.Request) -> web.Response:
    """Endpoint полной snapshot-выгрузки получателей."""

    settings = request.app[_SETTINGS_KEY]
    session_factory = request.app[_SESSION_FACTORY_KEY]

    raw_cursor = str(request.query.get("cursor") or "").strip()
    request[_AUDIT_SINCE_KEY] = None
    request[_AUDIT_CURSOR_HASH_KEY] = _hash_for_log(raw_cursor)

    try:
        limit = _parse_limit_from_query(request=request, settings=settings)
        cursor = _parse_cursor_from_query(
            request,
            settings=settings,
            expected_limit=limit,
        )
    except ValueError as exc:
        return _json_response_error(status=400, message=str(exc))

    items, internal_next_cursor = _fetch_snapshot_page(
        session_factory=session_factory,
        limit=limit,
        cursor=cursor,
        include_vk_pending_verification=settings.sagur_include_vk_pending_verification,
    )
    next_cursor: str | None = None
    if internal_next_cursor:
        next_cursor = _sign_cursor_payload(
            encoded_payload=internal_next_cursor,
            secret=_resolve_cursor_hmac_secret(settings),
        )
    request[_AUDIT_ROWS_KEY] = len(items)
    return _json_response_ok(
        {
            "items": items,
            "next_cursor": next_cursor,
            "generated_at": _to_rfc3339_utc(datetime.now(timezone.utc)),
        }
    )


async def _delta_handler(request: web.Request) -> web.Response:
    """Endpoint инкрементальной delta-выгрузки получателей."""

    settings = request.app[_SETTINGS_KEY]
    session_factory = request.app[_SESSION_FACTORY_KEY]

    raw_cursor = str(request.query.get("cursor") or "").strip()
    request[_AUDIT_CURSOR_HASH_KEY] = _hash_for_log(raw_cursor)

    try:
        since = _parse_since_from_query(request)
        limit = _parse_limit_from_query(request=request, settings=settings)
        cursor = _parse_delta_cursor_from_query(
            request,
            settings=settings,
            expected_limit=limit,
        )
    except ValueError as exc:
        return _json_response_error(status=400, message=str(exc))

    if cursor is not None and cursor.since != since:
        return _json_response_error(
            status=400,
            message="Параметр since должен совпадать с since внутри cursor.",
        )

    request[_AUDIT_SINCE_KEY] = _to_rfc3339_utc(since)
    items, internal_next_cursor, max_seen_updated_at = _fetch_delta_page(
        session_factory=session_factory,
        since=since,
        limit=limit,
        cursor=cursor,
        include_vk_pending_verification=settings.sagur_include_vk_pending_verification,
    )
    next_cursor: str | None = None
    if internal_next_cursor:
        next_cursor = _sign_cursor_payload(
            encoded_payload=internal_next_cursor,
            secret=_resolve_cursor_hmac_secret(settings),
        )
    request[_AUDIT_ROWS_KEY] = len(items)
    return _json_response_ok(
        {
            "items": items,
            "next_cursor": next_cursor,
            "max_seen_updated_at": _to_rfc3339_utc(max_seen_updated_at),
            "generated_at": _to_rfc3339_utc(datetime.now(timezone.utc)),
        }
    )


class CouponRecipientNotFoundError(ValueError):
    """Raised when a coupon item cannot be matched to a local recipient."""


def _coupon_item_result_acked(
    *,
    event_id: str,
    deduplicated: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {"event_id": event_id, "status": "acked"}
    if deduplicated:
        result["deduplicated"] = True
    return result


def _coupon_item_result_rejected(
    *,
    event_id: str,
    code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "status": "rejected",
        "code": code,
        "message": message,
    }


def _build_coupon_batch_response_payload(
    *,
    request_id: str,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    batch_status = (
        "acked"
        if all(str(result.get("status") or "") in _COUPON_BATCH_ACK_STATUSES for result in results)
        else "partial"
    )
    return {
        "request_id": request_id,
        "status": batch_status,
        "results": results,
    }


def _resolve_coupon_item_person_id(
    *,
    db_session: Session,
    payload_raw: dict[str, object],
) -> uuid.UUID:
    raw_person_id = str(payload_raw.get("person_id") or "").strip()
    raw_phone = str(payload_raw.get("phone_e164") or "").strip()
    parsed_person_id: uuid.UUID | None = None

    if raw_person_id:
        parsed_person_id = _parse_uuid(raw_person_id, field_name="payload.person_id")
        if db_session.get(PersonRow, parsed_person_id) is not None:
            return parsed_person_id

    if raw_phone:
        phone_row = db_session.execute(
            select(PhoneRow).where(PhoneRow.phone_e164 == raw_phone)
        ).scalar_one_or_none()
        if phone_row is not None:
            return phone_row.person_id

    if parsed_person_id is not None:
        raise CouponRecipientNotFoundError("recipient not found by person_id or phone_e164")
    raise CouponRecipientNotFoundError("recipient not found: person_id or phone_e164 is required")


def _apply_coupon_batch_item(
    *,
    db_session: Session,
    direction: str,
    sent_at: datetime | None,
    item_raw: object,
    request_id: str,
) -> tuple[dict[str, Any], bool, bool]:
    if not isinstance(item_raw, dict):
        return (
            _coupon_item_result_rejected(
                event_id="",
                code="invalid_payload",
                message="item must be a JSON object",
            ),
            False,
            False,
        )

    event_id_raw = str(item_raw.get("event_id") or "").strip()
    if not event_id_raw:
        return (
            _coupon_item_result_rejected(
                event_id="",
                code="invalid_payload",
                message="item.event_id is required",
            ),
            False,
            False,
        )

    try:
        event_id = _parse_uuid(event_id_raw, field_name="item.event_id")
    except ValueError as exc:
        return (
            _coupon_item_result_rejected(
                event_id=event_id_raw,
                code="invalid_payload",
                message=str(exc),
            ),
            False,
            False,
        )

    payload_raw: dict[str, object] = dict(item_raw)
    payload_raw.pop("event_id", None)
    person_id_for_log = str(payload_raw.get("person_id") or "-").strip() or "-"
    coupon_code_for_log = str(payload_raw.get("coupon_code") or "-").strip() or "-"

    try:
        person_id = _resolve_coupon_item_person_id(db_session=db_session, payload_raw=payload_raw)
        payload_raw["person_id"] = str(person_id)
        repository = SQLAlchemySagurCouponsRepository(db_session)
        result = repository.apply_event(
            event_id=event_id,
            direction=direction,
            sent_at=sent_at,
            payload_raw=payload_raw,
        )
        db_session.commit()
    except CouponRecipientNotFoundError as exc:
        db_session.rollback()
        logger.bind(component=_COMPONENT, stage="coupon_events").warning(
            "Coupon batch item rejected / Элемент batch купонов отклонен. request_id={request_id}, event_id={event_id}, person_id={person_id}, coupon_code={coupon_code}, direction={direction}, code=recipient_not_found, reason={reason}.",
            request_id=request_id,
            event_id=event_id_raw,
            person_id=person_id_for_log,
            coupon_code=coupon_code_for_log,
            direction=direction,
            reason=str(exc),
        )
        return (
            _coupon_item_result_rejected(
                event_id=event_id_raw,
                code="recipient_not_found",
                message="Получатель не найден",
            ),
            False,
            False,
        )
    except CouponAlreadyAssignedError as exc:
        db_session.rollback()
        logger.bind(component=_COMPONENT, stage="coupon_events").warning(
            "Coupon batch item rejected / Элемент batch купонов отклонен. request_id={request_id}, event_id={event_id}, person_id={person_id}, coupon_code={coupon_code}, direction={direction}, code=coupon_already_assigned, reason={reason}.",
            request_id=request_id,
            event_id=event_id_raw,
            person_id=person_id_for_log,
            coupon_code=coupon_code_for_log,
            direction=direction,
            reason=str(exc),
        )
        return (
            _coupon_item_result_rejected(
                event_id=event_id_raw,
                code="coupon_already_assigned",
                message="Купон уже привязан и не был освобожден",
            ),
            False,
            False,
        )
    except ValueError as exc:
        db_session.rollback()
        logger.bind(component=_COMPONENT, stage="coupon_events").warning(
            "Coupon batch item rejected / Элемент batch купонов отклонен. request_id={request_id}, event_id={event_id}, person_id={person_id}, coupon_code={coupon_code}, direction={direction}, code=invalid_payload, reason={reason}.",
            request_id=request_id,
            event_id=event_id_raw,
            person_id=person_id_for_log,
            coupon_code=coupon_code_for_log,
            direction=direction,
            reason=str(exc),
        )
        return (
            _coupon_item_result_rejected(
                event_id=event_id_raw,
                code="invalid_payload",
                message=str(exc),
            ),
            False,
            False,
        )
    except Exception as exc:  # noqa: BLE001
        db_session.rollback()
        logger.bind(component=_COMPONENT, stage="coupon_events").exception(
            "Coupon batch item failed / Ошибка элемента batch купонов. request_id={request_id}, event_id={event_id}, person_id={person_id}, coupon_code={coupon_code}, direction={direction}.",
            request_id=request_id,
            event_id=event_id_raw,
            person_id=person_id_for_log,
            coupon_code=coupon_code_for_log,
            direction=direction,
        )
        return (
            _coupon_item_result_rejected(
                event_id=event_id_raw,
                code="internal_error",
                message="Внутренняя ошибка обработки события купона",
            ),
            False,
            False,
        )

    logger.bind(component=_COMPONENT, stage="coupon_events").info(
        "Coupon batch item processed / Элемент batch купонов обработан. request_id={request_id}, event_id={event_id}, person_id={person_id}, coupon_code={coupon_code}, direction={direction}, deduplicated={deduplicated}.",
        request_id=request_id,
        event_id=event_id_raw,
        person_id=str(payload_raw.get("person_id") or person_id_for_log),
        coupon_code=coupon_code_for_log,
        direction=direction,
        deduplicated=result.deduplicated,
    )
    return _coupon_item_result_acked(
        event_id=event_id_raw,
        deduplicated=result.deduplicated,
    ), True, result.deduplicated


def _parse_coupon_batch_body(
    *,
    body: dict[str, Any],
    header_request_id: str,
) -> tuple[str, str, datetime | None, list[object]]:
    request_id = str(body.get("request_id") or "").strip()
    if not request_id:
        raise ValueError("request_id is required.")
    _parse_uuid(request_id, field_name="request_id")

    header_value = str(header_request_id or "").strip()
    if header_value and header_value != request_id:
        raise ValueError("request_id in body must match X-Sagur-Request-Id.")

    direction = str(body.get("direction") or "").strip().lower()
    if direction not in _COUPON_DIRECTIONS:
        raise ValueError("direction должен быть assignments или status_update.")

    raw_sent_at = str(body.get("sent_at") or "").strip()
    sent_at: datetime | None = None
    if raw_sent_at:
        sent_at = _parse_rfc3339_utc(raw_sent_at)

    items_raw = body.get("items")
    if not isinstance(items_raw, list):
        raise ValueError("items должен быть JSON-массивом.")
    return request_id, direction, sent_at, list(items_raw)


def _handle_coupon_batch_request(
    *,
    request: web.Request,
    body: dict[str, Any],
    started_at: float,
) -> web.Response:
    header_request_id = str(request.headers.get(_H_SAGUR_REQUEST_ID) or "").strip()
    try:
        request_id, direction, sent_at, items = _parse_coupon_batch_body(
            body=body,
            header_request_id=header_request_id,
        )
    except ValueError as exc:
        _metrics_record_coupon_event(
            app=request.app,
            latency_seconds=time.perf_counter() - started_at,
            success=False,
            deduplicated=False,
        )
        return _json_response_error(status=400, message=str(exc))

    request[_REQUEST_ID_KEY] = request_id
    session_factory = request.app[_SESSION_FACTORY_KEY]
    results: list[dict[str, Any]] = []

    try:
        with session_factory() as db_session:
            for item in items:
                result, success, deduplicated = _apply_coupon_batch_item(
                    db_session=db_session,
                    direction=direction,
                    sent_at=sent_at,
                    item_raw=item,
                    request_id=request_id,
                )
                results.append(result)
                _metrics_record_coupon_event(
                    app=request.app,
                    latency_seconds=time.perf_counter() - started_at,
                    success=success,
                    deduplicated=deduplicated,
                )
    except Exception:
        _metrics_record_coupon_event(
            app=request.app,
            latency_seconds=time.perf_counter() - started_at,
            success=False,
            deduplicated=False,
        )
        logger.bind(component=_COMPONENT, stage="coupon_events").exception(
            "Coupon batch failed before item processing / Batch купонов упал до обработки items. request_id={request_id}, direction={direction}.",
            request_id=request_id,
            direction=direction,
        )
        return _json_response_error(status=500, message="Внутренняя ошибка обработки batch купонов.")

    acked_count = sum(
        1 for result in results if str(result.get("status") or "") in _COUPON_BATCH_ACK_STATUSES
    )
    rejected = [
        {"event_id": result.get("event_id"), "code": result.get("code")}
        for result in results
        if str(result.get("status") or "") not in _COUPON_BATCH_ACK_STATUSES
    ]
    request[_AUDIT_ROWS_KEY] = len(results)
    response_payload = _build_coupon_batch_response_payload(request_id=request_id, results=results)
    logger.bind(component=_COMPONENT, stage="coupon_events").info(
        "Coupon batch processed / Batch купонов обработан. request_id={request_id}, direction={direction}, items={items_count}, acked={acked_count}, rejected={rejected_count}, problems={problems}.",
        request_id=request_id,
        direction=direction,
        items_count=len(items),
        acked_count=acked_count,
        rejected_count=len(results) - acked_count,
        problems=rejected,
    )
    return _json_response_ok(response_payload)


async def _coupons_events_handler(request: web.Request) -> web.Response:
    """Endpoint приема событий купонов от SAGUR."""

    started_at = time.perf_counter()
    request_id = request.get(_REQUEST_ID_KEY, "-")
    session_factory = request.app[_SESSION_FACTORY_KEY]

    try:
        body = await _read_json_object_body(request)
    except ValueError as exc:
        _metrics_record_coupon_event(
            app=request.app,
            latency_seconds=time.perf_counter() - started_at,
            success=False,
            deduplicated=False,
        )
        return _json_response_error(status=400, message=str(exc))

    if "items" in body:
        return _handle_coupon_batch_request(request=request, body=body, started_at=started_at)

    event_id_header = str(request.headers.get(_H_EVENT_ID) or "").strip()
    if not event_id_header:
        _metrics_record_coupon_event(
            app=request.app,
            latency_seconds=time.perf_counter() - started_at,
            success=False,
            deduplicated=False,
        )
        return _json_response_error(status=400, message="Отсутствует заголовок X-Sagur-Event-Id.")

    try:
        header_event_id = _parse_uuid(event_id_header, field_name="X-Sagur-Event-Id")
    except ValueError as exc:
        _metrics_record_coupon_event(
            app=request.app,
            latency_seconds=time.perf_counter() - started_at,
            success=False,
            deduplicated=False,
        )
        return _json_response_error(status=400, message=str(exc))

    body_event_id_raw = str(body.get("event_id") or "").strip()
    if not body_event_id_raw:
        _metrics_record_coupon_event(
            app=request.app,
            latency_seconds=time.perf_counter() - started_at,
            success=False,
            deduplicated=False,
        )
        return _json_response_error(status=400, message="event_id is required.")

    try:
        body_event_id = _parse_uuid(body_event_id_raw, field_name="event_id")
    except ValueError as exc:
        _metrics_record_coupon_event(
            app=request.app,
            latency_seconds=time.perf_counter() - started_at,
            success=False,
            deduplicated=False,
        )
        return _json_response_error(status=400, message=str(exc))

    if body_event_id != header_event_id:
        _metrics_record_coupon_event(
            app=request.app,
            latency_seconds=time.perf_counter() - started_at,
            success=False,
            deduplicated=False,
        )
        return _json_response_error(
            status=400,
            message="event_id в body должен совпадать с X-Sagur-Event-Id.",
        )

    direction = str(body.get("direction") or "").strip().lower()
    if direction not in _COUPON_DIRECTIONS:
        _metrics_record_coupon_event(
            app=request.app,
            latency_seconds=time.perf_counter() - started_at,
            success=False,
            deduplicated=False,
        )
        return _json_response_error(
            status=400,
            message="direction должен быть assignments или status_update.",
        )

    payload_raw = body.get("payload")
    if not isinstance(payload_raw, dict):
        _metrics_record_coupon_event(
            app=request.app,
            latency_seconds=time.perf_counter() - started_at,
            success=False,
            deduplicated=False,
        )
        return _json_response_error(status=400, message="payload должен быть JSON-объектом.")

    raw_sent_at = str(body.get("sent_at") or "").strip()
    sent_at: datetime | None = None
    if raw_sent_at:
        try:
            sent_at = _parse_rfc3339_utc(raw_sent_at)
        except ValueError:
            _metrics_record_coupon_event(
                app=request.app,
                latency_seconds=time.perf_counter() - started_at,
                success=False,
                deduplicated=False,
            )
            return _json_response_error(status=400, message="sent_at должен быть в формате RFC3339 UTC.")

    person_id_for_log = str(payload_raw.get("person_id") or "-").strip() or "-"
    coupon_code_for_log = str(payload_raw.get("coupon_code") or "-").strip() or "-"

    try:
        with session_factory() as db_session:
            repository = SQLAlchemySagurCouponsRepository(db_session)
            result = repository.apply_event(
                event_id=header_event_id,
                direction=direction,
                sent_at=sent_at,
                payload_raw=payload_raw,
            )
            db_session.commit()
    except ValueError as exc:
        _metrics_record_coupon_event(
            app=request.app,
            latency_seconds=time.perf_counter() - started_at,
            success=False,
            deduplicated=False,
        )
        logger.bind(component=_COMPONENT, stage="coupon_events").warning(
            "Coupon event rejected. request_id={request_id}, event_id={event_id}, person_id={person_id}, coupon_code={coupon_code}, direction={direction}, reason={reason}.",
            request_id=request_id,
            event_id=str(header_event_id),
            person_id=person_id_for_log,
            coupon_code=coupon_code_for_log,
            direction=direction,
            reason=str(exc),
        )
        return _json_response_error(status=400, message=str(exc))
    except Exception:
        _metrics_record_coupon_event(
            app=request.app,
            latency_seconds=time.perf_counter() - started_at,
            success=False,
            deduplicated=False,
        )
        logger.bind(component=_COMPONENT, stage="coupon_events").exception(
            "Coupon event failed. request_id={request_id}, event_id={event_id}, person_id={person_id}, coupon_code={coupon_code}, direction={direction}.",
            request_id=request_id,
            event_id=str(header_event_id),
            person_id=person_id_for_log,
            coupon_code=coupon_code_for_log,
            direction=direction,
        )
        return _json_response_error(status=500, message="Внутренняя ошибка обработки события купона.")

    _metrics_record_coupon_event(
        app=request.app,
        latency_seconds=time.perf_counter() - started_at,
        success=True,
        deduplicated=result.deduplicated,
    )
    request[_AUDIT_ROWS_KEY] = 1
    logger.bind(component=_COMPONENT, stage="coupon_events").info(
        "Coupon event processed. request_id={request_id}, event_id={event_id}, person_id={person_id}, coupon_code={coupon_code}, direction={direction}, deduplicated={deduplicated}.",
        request_id=request_id,
        event_id=str(header_event_id),
        person_id=person_id_for_log,
        coupon_code=coupon_code_for_log,
        direction=direction,
        deduplicated=result.deduplicated,
    )
    return _json_response_ok({"ok": True})


def build_web_app(
    *,
    settings: AppSettings,
    session_factory: sessionmaker[Session],
) -> web.Application:
    """Собирает aiohttp приложение SAGUR integration API."""

    app = web.Application(
        client_max_size=_MAX_JSON_BODY_BYTES,
        middlewares=[_sagur_auth_middleware],
    )
    app[_SETTINGS_KEY] = settings
    app[_SESSION_FACTORY_KEY] = session_factory
    app[_METRICS_KEY] = _build_metrics_state()
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/metrics", _metrics_handler)
    app.router.add_get("/internal/integration/v1/sagur/recipients/snapshot", _snapshot_handler)
    app.router.add_get("/internal/integration/v1/sagur/recipients/delta", _delta_handler)
    app.router.add_post("/internal/integration/v1/sagur/coupons/events", _coupons_events_handler)
    return app


async def _wait_for_shutdown_signal(component: str) -> None:
    """Ожидает SIGTERM/SIGINT для no-op режима выключенного сервиса."""

    stop_event = asyncio.Event()

    def _request_shutdown(source: str) -> None:
        if stop_event.is_set():
            return
        logger.bind(component=component, stage="shutdown").info(
            "Получен сигнал остановки сервиса: {source}.",
            source=source,
        )
        stop_event.set()

    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(stop_signal, _request_shutdown, stop_signal.name)

    await stop_event.wait()


def _validate_service_settings(settings: AppSettings) -> None:
    """Проверяет корректность критичных параметров запуска сервиса."""

    if settings.sagur_integration_default_limit > settings.sagur_integration_max_limit:
        raise ValueError(
            "SAGUR_INTEGRATION_DEFAULT_LIMIT должен быть меньше или равен "
            "SAGUR_INTEGRATION_MAX_LIMIT."
        )


async def run_sagur_integration_api(settings: AppSettings | None = None) -> None:
    """Запускает отдельный SAGUR integration API сервис."""

    app_settings = settings or AppSettings()
    configure_logging(service_name="sagur-integration-api", log_level=app_settings.log_level)
    app_logger = logger.bind(component=_COMPONENT, stage="startup")
    app_logger.info("Инициализация SAGUR integration API. ENV={env}.", env=app_settings.env)

    if not app_settings.sagur_integration_api_enabled:
        app_logger.info("Сервис выключен (SAGUR_INTEGRATION_API_ENABLED=false).")
        await _wait_for_shutdown_signal(component=_COMPONENT)
        return

    _validate_service_settings(app_settings)

    session_factory = build_postgres_session_factory(app_settings)
    web_app = build_web_app(settings=app_settings, session_factory=session_factory)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(
        runner,
        host=app_settings.sagur_integration_service_host,
        port=app_settings.sagur_integration_service_port,
    )
    await site.start()
    app_logger.info(
        "SAGUR integration API запущен на {host}:{port}.",
        host=app_settings.sagur_integration_service_host,
        port=app_settings.sagur_integration_service_port,
    )

    stop_event = asyncio.Event()

    def _request_shutdown(source: str) -> None:
        if stop_event.is_set():
            return
        logger.bind(component=_COMPONENT, stage="shutdown").info(
            "Получен сигнал остановки сервиса: {source}.",
            source=source,
        )
        stop_event.set()

    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(stop_signal, _request_shutdown, stop_signal.name)

    try:
        await stop_event.wait()
    finally:
        await runner.cleanup()
        app_logger.info("SAGUR integration API завершен.")


def main() -> None:
    """Синхронная точка входа запуска сервиса из CLI/docker."""

    asyncio.run(run_sagur_integration_api())


if __name__ == "__main__":
    main()
