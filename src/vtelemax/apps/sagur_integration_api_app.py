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
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from vtelemax.infrastructure import configure_logging
from vtelemax.infrastructure.postgres import build_engine, build_session_factory
from vtelemax.settings import AppSettings

_COMPONENT = "sagur_integration_api_app"
_MAX_JSON_BODY_BYTES = 8 * 1024
_SETTINGS_KEY = web.AppKey("settings", AppSettings)
_SESSION_FACTORY_KEY = web.AppKey("session_factory", sessionmaker[Session])
_REQUEST_ID_KEY = web.AppKey("request_id", str)
_AUDIT_ROWS_KEY = web.AppKey("audit_rows", int)
_AUDIT_SINCE_KEY = web.AppKey("audit_since", str | None)
_AUDIT_CURSOR_HASH_KEY = web.AppKey("audit_cursor_hash", str | None)
_SAGUR_PATH_PREFIX = "/internal/integration/v1/sagur/"
_H_TIMESTAMP = "X-Sagur-Timestamp"
_H_SIGNATURE = "X-Sagur-Signature"
_H_REQUEST_ID = "X-Request-Id"


@dataclass(frozen=True, slots=True)
class SnapshotCursor:
    """Позиция пагинации snapshot выдачи."""

    account_created_at: datetime
    person_id: str
    platform: str


@dataclass(frozen=True, slots=True)
class DeltaCursor:
    """Позиция пагинации delta выдачи."""

    since: datetime
    effective_updated_at: datetime
    person_id: str
    platform: str


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
        "v": 1,
        "t": "snapshot",
        "account_created_at": _to_rfc3339_utc(cursor.account_created_at),
        "person_id": cursor.person_id,
        "platform": cursor.platform,
    }
    json_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(json_bytes).decode("ascii")
    return encoded.rstrip("=")


def _decode_snapshot_cursor(raw_cursor: str) -> SnapshotCursor:
    """Декодирует opaque cursor и валидирует структуру."""

    try:
        padded = raw_cursor + "=" * (-len(raw_cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("cursor payload must be object")

        version = int(payload.get("v"))
        if version != 1:
            raise ValueError("unsupported cursor version")
        if str(payload.get("t") or "") != "snapshot":
            raise ValueError("unsupported cursor type")

        account_created_at = _parse_rfc3339_utc(str(payload.get("account_created_at") or "").strip())
        person_id = str(payload.get("person_id") or "").strip()
        platform = str(payload.get("platform") or "").strip()

        if not person_id:
            raise ValueError("person_id is empty")
        if platform not in {"telegram", "vk", "max"}:
            raise ValueError("platform is invalid")

        return SnapshotCursor(
            account_created_at=account_created_at,
            person_id=person_id,
            platform=platform,
        )
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Некорректный cursor.") from exc


def _encode_delta_cursor(cursor: DeltaCursor) -> str:
    """Кодирует delta cursor в opaque строку."""

    payload = {
        "v": 1,
        "t": "delta",
        "since": _to_rfc3339_utc(cursor.since),
        "effective_updated_at": _to_rfc3339_utc(cursor.effective_updated_at),
        "person_id": cursor.person_id,
        "platform": cursor.platform,
    }
    json_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(json_bytes).decode("ascii")
    return encoded.rstrip("=")


def _decode_delta_cursor(raw_cursor: str) -> DeltaCursor:
    """Декодирует opaque delta cursor и валидирует структуру."""

    try:
        padded = raw_cursor + "=" * (-len(raw_cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("cursor payload must be object")

        version = int(payload.get("v"))
        if version != 1:
            raise ValueError("unsupported cursor version")
        if str(payload.get("t") or "") != "delta":
            raise ValueError("unsupported cursor type")

        since = _parse_rfc3339_utc(str(payload.get("since") or "").strip())
        effective_updated_at = _parse_rfc3339_utc(
            str(payload.get("effective_updated_at") or "").strip()
        )
        person_id = str(payload.get("person_id") or "").strip()
        platform = str(payload.get("platform") or "").strip()

        if not person_id:
            raise ValueError("person_id is empty")
        if platform not in {"telegram", "vk", "max"}:
            raise ValueError("platform is invalid")

        return DeltaCursor(
            since=since,
            effective_updated_at=effective_updated_at,
            person_id=person_id,
            platform=platform,
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


def _parse_cursor_from_query(request: web.Request) -> SnapshotCursor | None:
    """Читает и декодирует snapshot cursor из query."""

    raw_cursor = str(request.query.get("cursor") or "").strip()
    if not raw_cursor:
        return None
    return _decode_snapshot_cursor(raw_cursor)


def _parse_since_from_query(request: web.Request) -> datetime:
    """Парсит обязательный параметр since для delta endpoint."""

    raw_since = str(request.query.get("since") or "").strip()
    if not raw_since:
        raise ValueError("Параметр since обязателен и должен быть в формате RFC3339 UTC.")
    try:
        return _parse_rfc3339_utc(raw_since)
    except ValueError as exc:
        raise ValueError("Параметр since должен быть в формате RFC3339 UTC.") from exc


def _parse_delta_cursor_from_query(request: web.Request) -> DeltaCursor | None:
    """Читает и декодирует delta cursor из query."""

    raw_cursor = str(request.query.get("cursor") or "").strip()
    if not raw_cursor:
        return None
    return _decode_delta_cursor(raw_cursor)


def _extract_snapshot_cursor_from_row(row: dict[str, Any]) -> SnapshotCursor:
    """Формирует cursor из последней возвращенной строки."""

    account_created_at = row["account_created_at"]
    if not isinstance(account_created_at, datetime):
        raise ValueError("account_created_at missing in snapshot row")
    return SnapshotCursor(
        account_created_at=account_created_at,
        person_id=str(row["person_id"]),
        platform=str(row["platform"]),
    )


def _extract_delta_cursor_from_row(*, row: dict[str, Any], since: datetime) -> DeltaCursor:
    """Формирует delta cursor из последней строки страницы."""

    effective_updated_at = row["effective_updated_at"]
    if not isinstance(effective_updated_at, datetime):
        raise ValueError("effective_updated_at missing in delta row")
    return DeltaCursor(
        since=since,
        effective_updated_at=effective_updated_at,
        person_id=str(row["person_id"]),
        platform=str(row["platform"]),
    )


def _build_snapshot_sql(*, has_cursor: bool) -> str:
    cursor_clause = ""
    if has_cursor:
        cursor_clause = """
WHERE
    (ra.account_created_at, ra.person_id, ra.platform)
    > (
        :cursor_account_created_at::timestamptz,
        :cursor_person_id::uuid,
        :cursor_platform::text
    )
"""

    return f"""
WITH ranked_accounts AS (
    SELECT
        pa.person_id,
        pa.platform,
        pa.external_id,
        pa.created_at AS account_created_at,
        ROW_NUMBER() OVER (
            PARTITION BY pa.person_id, pa.platform
            ORDER BY pa.created_at DESC, pa.account_id DESC
        ) AS row_rank
    FROM platform_accounts pa
),
resolved_accounts AS (
    SELECT
        person_id,
        platform,
        external_id,
        account_created_at
    FROM ranked_accounts
    WHERE row_rank = 1
)
SELECT
    ra.person_id::text AS person_id,
    ph.phone_e164 AS phone_e164,
    ra.platform AS platform,
    ra.external_id AS external_id,
    COALESCE(pps.rules_accepted, false) AS rules_accepted,
    COALESCE(pps.notifications_allowed, false) AS notifications_allowed,
    COALESCE(pps.is_registered, false) AS is_registered,
    pps.updated_at AS state_updated_at,
    ra.account_created_at AS account_created_at
FROM resolved_accounts ra
JOIN phones ph
    ON ph.person_id = ra.person_id
LEFT JOIN person_platform_states pps
    ON pps.person_id = ra.person_id
   AND pps.platform = ra.platform
{cursor_clause}
ORDER BY
    ra.account_created_at ASC,
    ra.person_id ASC,
    ra.platform ASC
LIMIT :page_size
"""


def _build_delta_sql(*, has_cursor: bool) -> str:
    cursor_clause = ""
    if has_cursor:
        cursor_clause = """
  AND
    (e.effective_updated_at, e.person_id, e.platform)
    > (
        :cursor_effective_updated_at::timestamptz,
        :cursor_person_id::uuid,
        :cursor_platform::text
    )
"""

    return f"""
WITH ranked_accounts AS (
    SELECT
        pa.person_id,
        pa.platform,
        pa.external_id,
        pa.created_at AS account_created_at,
        ROW_NUMBER() OVER (
            PARTITION BY pa.person_id, pa.platform
            ORDER BY pa.created_at DESC, pa.account_id DESC
        ) AS row_rank
    FROM platform_accounts pa
),
resolved_accounts AS (
    SELECT
        person_id,
        platform,
        external_id,
        account_created_at
    FROM ranked_accounts
    WHERE row_rank = 1
),
enriched AS (
    SELECT
        ra.person_id::text AS person_id,
        ph.phone_e164 AS phone_e164,
        ra.platform AS platform,
        ra.external_id AS external_id,
        COALESCE(pps.rules_accepted, false) AS rules_accepted,
        COALESCE(pps.notifications_allowed, false) AS notifications_allowed,
        COALESCE(pps.is_registered, false) AS is_registered,
        pps.updated_at AS state_updated_at,
        ra.account_created_at AS account_created_at,
        GREATEST(COALESCE(pps.updated_at, ra.account_created_at), ra.account_created_at) AS effective_updated_at
    FROM resolved_accounts ra
    JOIN phones ph
        ON ph.person_id = ra.person_id
    LEFT JOIN person_platform_states pps
        ON pps.person_id = ra.person_id
       AND pps.platform = ra.platform
)
SELECT
    e.person_id,
    e.phone_e164,
    e.platform,
    e.external_id,
    e.rules_accepted,
    e.notifications_allowed,
    e.is_registered,
    e.state_updated_at,
    e.account_created_at,
    e.effective_updated_at
FROM enriched e
WHERE
    (
        (e.state_updated_at IS NOT NULL AND e.state_updated_at > :since::timestamptz)
        OR e.account_created_at > :since::timestamptz
    )
{cursor_clause}
ORDER BY
    e.effective_updated_at ASC,
    e.person_id ASC,
    e.platform ASC
LIMIT :page_size
"""


def _fetch_snapshot_page(
    *,
    session_factory: sessionmaker[Session],
    limit: int,
    cursor: SnapshotCursor | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Вычитывает snapshot-страницу и возвращает next_cursor."""

    query = _build_snapshot_sql(has_cursor=cursor is not None)
    params: dict[str, Any] = {"page_size": limit + 1}
    if cursor is not None:
        params.update(
            {
                "cursor_account_created_at": cursor.account_created_at,
                "cursor_person_id": cursor.person_id,
                "cursor_platform": cursor.platform,
            }
        )

    with session_factory() as db_session:
        rows = db_session.execute(text(query), params).mappings().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]

    items: list[dict[str, Any]] = []
    for row in page_rows:
        items.append(
            {
                "person_id": str(row["person_id"]),
                "phone_e164": str(row["phone_e164"]),
                "platform": str(row["platform"]),
                "external_id": str(row["external_id"]),
                "rules_accepted": bool(row["rules_accepted"]),
                "notifications_allowed": bool(row["notifications_allowed"]),
                "is_registered": bool(row["is_registered"]),
                "state_updated_at": _to_rfc3339_utc(row["state_updated_at"]),
                "account_created_at": _to_rfc3339_utc(row["account_created_at"]),
            }
        )

    if not has_more or not page_rows:
        return items, None

    next_cursor = _encode_snapshot_cursor(_extract_snapshot_cursor_from_row(dict(page_rows[-1])))
    return items, next_cursor


def _fetch_delta_page(
    *,
    session_factory: sessionmaker[Session],
    since: datetime,
    limit: int,
    cursor: DeltaCursor | None,
) -> tuple[list[dict[str, Any]], str | None, datetime | None]:
    """Вычитывает delta-страницу и возвращает next_cursor и max_seen_updated_at."""

    query = _build_delta_sql(has_cursor=cursor is not None)
    params: dict[str, Any] = {
        "since": since,
        "page_size": limit + 1,
    }
    if cursor is not None:
        params.update(
            {
                "cursor_effective_updated_at": cursor.effective_updated_at,
                "cursor_person_id": cursor.person_id,
                "cursor_platform": cursor.platform,
            }
        )

    with session_factory() as db_session:
        rows = db_session.execute(text(query), params).mappings().all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]

    items: list[dict[str, Any]] = []
    max_seen_updated_at: datetime | None = None

    for row in page_rows:
        effective_updated_at = row["effective_updated_at"]
        if isinstance(effective_updated_at, datetime):
            if max_seen_updated_at is None or effective_updated_at > max_seen_updated_at:
                max_seen_updated_at = effective_updated_at

        items.append(
            {
                "person_id": str(row["person_id"]),
                "phone_e164": str(row["phone_e164"]),
                "platform": str(row["platform"]),
                "external_id": str(row["external_id"]),
                "rules_accepted": bool(row["rules_accepted"]),
                "notifications_allowed": bool(row["notifications_allowed"]),
                "is_registered": bool(row["is_registered"]),
                "state_updated_at": _to_rfc3339_utc(row["state_updated_at"]),
                "account_created_at": _to_rfc3339_utc(row["account_created_at"]),
            }
        )

    if not has_more or not page_rows:
        return items, None, max_seen_updated_at

    next_cursor = _encode_delta_cursor(
        _extract_delta_cursor_from_row(row=dict(page_rows[-1]), since=since)
    )
    return items, next_cursor, max_seen_updated_at


async def _health_handler(request: web.Request) -> web.Response:
    """Health endpoint сервиса."""

    return _json_response_ok({"status": "ok", "service": "sagur-integration-api"})


async def _snapshot_handler(request: web.Request) -> web.Response:
    """Endpoint полной snapshot-выгрузки получателей."""

    settings = request.app[_SETTINGS_KEY]
    session_factory = request.app[_SESSION_FACTORY_KEY]

    raw_cursor = str(request.query.get("cursor") or "").strip()
    request[_AUDIT_SINCE_KEY] = None
    request[_AUDIT_CURSOR_HASH_KEY] = _hash_for_log(raw_cursor)

    try:
        limit = _parse_limit_from_query(request=request, settings=settings)
        cursor = _parse_cursor_from_query(request)
    except ValueError as exc:
        return _json_response_error(status=400, message=str(exc))

    items, next_cursor = _fetch_snapshot_page(
        session_factory=session_factory,
        limit=limit,
        cursor=cursor,
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
        cursor = _parse_delta_cursor_from_query(request)
    except ValueError as exc:
        return _json_response_error(status=400, message=str(exc))

    if cursor is not None and cursor.since != since:
        return _json_response_error(
            status=400,
            message="Параметр since должен совпадать с since внутри cursor.",
        )

    request[_AUDIT_SINCE_KEY] = _to_rfc3339_utc(since)
    items, next_cursor, max_seen_updated_at = _fetch_delta_page(
        session_factory=session_factory,
        since=since,
        limit=limit,
        cursor=cursor,
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
    app.router.add_get("/health", _health_handler)
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
