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
from sqlalchemy.orm import Session, sessionmaker

from vtelemax.infrastructure import configure_logging
from vtelemax.infrastructure.postgres import (
    SQLAlchemySagurRecipientsRepository,
    build_engine,
    build_session_factory,
)
from vtelemax.settings import AppSettings

_COMPONENT = "sagur_integration_api_app"
_MAX_JSON_BODY_BYTES = 8 * 1024
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
_CURSOR_SIG_PREFIX = "cursor\n"


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


def _build_hmac_payload(*, method: str, path_qs: str, timestamp: int) -> str:
    """Собирает canonical payload для проверки HMAC подписи."""

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
    }


def _metrics_record_request(*, app: web.Application, latency_seconds: float, rows: int = 0) -> None:
    """Обновляет счетчики запросов/латентности/строк в ответе."""

    metrics = app[_METRICS_KEY]
    metrics["requests_total"] += 1
    metrics["request_latency_seconds_sum"] += max(latency_seconds, 0.0)
    metrics["request_latency_seconds_count"] += 1
    metrics["rows_returned_total"] += max(rows, 0)


def _resolve_request_id(request: web.Request) -> str:
    """Возвращает request id из заголовка или генерирует новый."""

    raw_request_id = str(request.headers.get(_H_REQUEST_ID) or "").strip()
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

    payload = _build_hmac_payload(
        method=request.method,
        path_qs=request.path_qs,
        timestamp=timestamp,
    )
    expected_signature = _build_hmac_signature(secret=secret, payload=payload)
    if not hmac.compare_digest(expected_signature, signature_raw):
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
    auth_error = _validate_hmac_auth(request=request, settings=settings)
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

    lines = [
        "# HELP sagur_integration_requests_total Total integration API requests.",
        "# TYPE sagur_integration_requests_total counter",
        f"sagur_integration_requests_total {int(metrics['requests_total'])}",
        "# HELP sagur_integration_request_latency_seconds_sum Accumulated request latency in seconds.",
        "# TYPE sagur_integration_request_latency_seconds_sum counter",
        f"sagur_integration_request_latency_seconds_sum {metrics['request_latency_seconds_sum']:.6f}",
        "# HELP sagur_integration_request_latency_seconds_count Count of latency observations.",
        "# TYPE sagur_integration_request_latency_seconds_count counter",
        f"sagur_integration_request_latency_seconds_count {int(metrics['request_latency_seconds_count'])}",
        "# HELP sagur_integration_rows_returned_total Total rows returned by snapshot/delta endpoints.",
        "# TYPE sagur_integration_rows_returned_total counter",
        f"sagur_integration_rows_returned_total {int(metrics['rows_returned_total'])}",
        "# HELP sagur_integration_auth_failures_total Total failed auth checks.",
        "# TYPE sagur_integration_auth_failures_total counter",
        f"sagur_integration_auth_failures_total {int(metrics['auth_failures_total'])}",
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
