"""Entrypoint отдельного сервиса верификации телефона через VK Mini App."""

from __future__ import annotations

import asyncio
import contextlib
import signal
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from aiohttp import web
from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from vtelemax.core import normalize_phone
from vtelemax.infrastructure import (
    SQLAlchemyVkPhoneVerificationSessionRepository,
    configure_logging,
    verify_vk_phone_verification_signature,
)
from vtelemax.infrastructure.postgres import build_engine, build_session_factory
from vtelemax.settings import AppSettings

_COMPONENT = "vk_phone_verification_service_app"
_MAX_JSON_BODY_BYTES = 32 * 1024
_H_REQUEST_ID = "X-Request-Id"
_SETTINGS_KEY = web.AppKey("settings", AppSettings)
_SESSION_FACTORY_KEY = web.AppKey("session_factory", sessionmaker[Session])
_REQUEST_ID_KEY = web.AppKey("request_id", str)

_MINIAPP_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Подтверждение телефона</title>
  <style>
    :root { color-scheme: light; }
    body { margin: 0; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f7fb; color: #12263a; }
    .card { max-width: 520px; margin: 0 auto; background: #fff; border-radius: 16px; padding: 20px; box-shadow: 0 8px 24px rgba(18,38,58,.08); }
    h1 { margin: 0 0 12px; font-size: 22px; }
    p { margin: 8px 0; line-height: 1.45; }
    .hint { color: #5c6f82; font-size: 14px; }
    button { width: 100%; border: 0; border-radius: 10px; padding: 14px 16px; font-size: 16px; font-weight: 600; cursor: pointer; margin-top: 10px; }
    button.primary { background: #2787f5; color: #fff; }
    button.secondary { background: #ebf3ff; color: #1d5eb8; }
    button:disabled { opacity: .5; cursor: default; }
    .status { margin-top: 14px; padding: 12px; border-radius: 10px; background: #f4f8ff; white-space: pre-line; }
    .status.error { background: #fff0f0; color: #8a1f1f; }
    .status.success { background: #ecfff0; color: #176b2c; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Подтверждение номера</h1>
    <p>Нажмите кнопку ниже и разрешите доступ к номеру телефона в VK.</p>
    <p class="hint">После успешной проверки вернитесь в чат-бот и нажмите «✅ Я подтвердил номер».</p>
    <button id="verifyBtn" class="primary">🛡️ Подтвердить номер</button>
    <button id="closeBtn" class="secondary" style="display:none;">↩️ Вернуться в бот</button>
    <div id="status" class="status">Подготовка сессии...</div>
  </div>

  <script src="https://unpkg.com/@vkontakte/vk-bridge/dist/browser.min.js"></script>
  <script>
    const statusEl = document.getElementById("status");
    const verifyBtn = document.getElementById("verifyBtn");
    const closeBtn = document.getElementById("closeBtn");

    const params = new URLSearchParams(window.location.search);
    const signedUid = Number(params.get("uid") || "0");
    const signedTs = Number(params.get("ts") || "0");
    const signedSig = String(params.get("sig") || "");
    let sessionId = "";
    let vkUserId = 0;

    function setStatus(text, mode = "info") {
      statusEl.textContent = text;
      statusEl.className = "status" + (mode === "error" ? " error" : mode === "success" ? " success" : "");
    }

    async function api(path, method = "GET", body = null) {
      const options = { method, headers: { "Accept": "application/json" } };
      if (body !== null) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
      }
      const response = await fetch(path, options);
      const payload = await response.json().catch(() => ({ message: "invalid_json" }));
      if (!response.ok) {
        const message = payload.message || payload.error || ("HTTP " + response.status);
        throw new Error(message);
      }
      return payload;
    }

    function extractPhone(data) {
      const candidates = [
        data?.phone_number,
        data?.phone,
        data?.number,
        data?.response?.phone_number,
        data?.response?.phone,
        data?.result?.phone_number,
        data?.result?.phone,
      ];
      for (const value of candidates) {
        if (typeof value === "string" && value.trim().length > 0) {
          return value.trim();
        }
      }
      return "";
    }

    async function resolveVkUserId() {
      try {
        await vkBridge.send("VKWebAppInit");
      } catch (_) {}
      try {
        const userInfo = await vkBridge.send("VKWebAppGetUserInfo");
        const id = Number(userInfo?.id || "0");
        if (Number.isFinite(id) && id > 0) {
          return id;
        }
      } catch (_) {}
      return signedUid > 0 ? signedUid : 0;
    }

    async function prepareSession() {
      vkUserId = await resolveVkUserId();
      if (!vkUserId) {
        throw new Error("Не удалось определить VK user id.");
      }
      const started = await api("/api/v1/vk/miniapp/session/start", "POST", {
        vk_user_id: vkUserId,
        uid: signedUid,
        ts: signedTs,
        sig: signedSig,
      });
      sessionId = String(started.session_id || "");
      if (!sessionId) {
        throw new Error("Сервис не вернул session_id.");
      }
      setStatus("Сессия готова. Нажмите «Подтвердить номер».", "info");
    }

    async function requestPhoneFromBridge() {
      try {
        const phoneResult = await vkBridge.send("VKWebAppGetPhoneNumber");
        const phone = extractPhone(phoneResult);
        if (phone) {
          return phone;
        }
      } catch (_) {}

      try {
        const personalCard = await vkBridge.send("VKWebAppGetPersonalCard", { type: ["phone_number"] });
        const phone = extractPhone(personalCard);
        if (phone) {
          return phone;
        }
      } catch (_) {}

      return "";
    }

    async function submitPhone() {
      if (!sessionId || !vkUserId) {
        throw new Error("Сессия не подготовлена.");
      }
      setStatus("Запрашиваем номер телефона в VK...", "info");
      const phoneRaw = await requestPhoneFromBridge();
      if (!phoneRaw) {
        throw new Error("VK не вернул номер телефона. Разрешите доступ и повторите.");
      }

      setStatus("Проверяем и фиксируем номер...", "info");
      const result = await api("/api/v1/vk/miniapp/session/phone", "POST", {
        session_id: sessionId,
        vk_user_id: vkUserId,
        phone: phoneRaw,
        uid: signedUid,
        ts: signedTs,
        sig: signedSig,
      });

      if (result.status !== "verified") {
        throw new Error("Сервис не подтвердил номер. Повторите попытку.");
      }

      verifyBtn.disabled = true;
      closeBtn.style.display = "block";
      setStatus("Номер подтвержден.\nВернитесь в бот и нажмите «✅ Я подтвердил номер».", "success");
    }

    verifyBtn.addEventListener("click", async () => {
      verifyBtn.disabled = true;
      try {
        await submitPhone();
      } catch (error) {
        setStatus(String(error?.message || error), "error");
        verifyBtn.disabled = false;
      }
    });

    closeBtn.addEventListener("click", async () => {
      try {
        await vkBridge.send("VKWebAppClose");
      } catch (_) {
        window.close();
      }
    });

    prepareSession().catch((error) => {
      setStatus(String(error?.message || error), "error");
      verifyBtn.disabled = true;
    });
  </script>
</body>
</html>
"""


def build_postgres_session_factory(settings: AppSettings) -> sessionmaker[Session]:
    """Создает PostgreSQL session factory для Mini App сервиса."""

    engine = build_engine(settings.postgres_sqlalchemy_dsn, echo=settings.postgres_echo)
    return build_session_factory(engine)


def _json_response_ok(payload: dict[str, Any]) -> web.Response:
    """Формирует стандартный JSON-ответ 200."""

    return web.json_response(payload, status=200)


def _json_response_error(*, status: int, message: str) -> web.Response:
    """Формирует стандартный JSON-ответ ошибки."""

    return web.json_response({"status": "error", "message": message}, status=status)


def _resolve_request_id(request: web.Request) -> str:
    """Возвращает request_id из заголовка или генерирует новый для трассировки."""

    raw_request_id = str(request.headers.get(_H_REQUEST_ID) or "").strip()
    if raw_request_id:
        return raw_request_id[:128]
    return uuid4().hex


def _resolve_caller_ip(request: web.Request) -> str:
    """Определяет IP вызывающей стороны без доверия пользовательскому payload."""

    x_real_ip = str(request.headers.get("X-Real-IP") or "").strip()
    if x_real_ip:
        return x_real_ip
    return str(request.remote or "-")


def _get_request_id(request: web.Request) -> str:
    """Безопасно возвращает request_id текущего запроса для бизнес-логов."""

    return str(request.get(_REQUEST_ID_KEY, "-"))


@web.middleware
async def _request_audit_middleware(
    request: web.Request,
    handler: Any,
) -> web.StreamResponse:
    """Логирует входящий Mini App HTTP-запрос и пробрасывает `X-Request-Id` в ответ.

    Middleware не читает тело запроса и не логирует query string: обработчики сами парсят JSON,
    а в логах не должны появляться телефон, подписи ссылок или другие чувствительные поля.
    """

    request_id = _resolve_request_id(request)
    request[_REQUEST_ID_KEY] = request_id
    started_at = time.perf_counter()
    status = 500

    try:
        response = await handler(request)
        status = response.status
        response.headers[_H_REQUEST_ID] = request_id
        return response
    except web.HTTPException as error:
        status = error.status
        error.headers[_H_REQUEST_ID] = request_id
        raise
    except Exception:
        logger.bind(component=_COMPONENT, stage="http_audit").exception(
            "Mini App запрос завершился исключением. request_id={request_id}, method={method}, path={path}.",
            request_id=request_id,
            method=request.method,
            path=request.path,
        )
        raise
    finally:
        latency_ms = (time.perf_counter() - started_at) * 1000
        level = "WARNING" if status >= 500 else "INFO"
        logger.bind(component=_COMPONENT, stage="http_audit").log(
            level,
            "Mini App запрос обработан. request_id={request_id}, caller_ip={caller_ip}, "
            "method={method}, path={path}, status={status}, latency_ms={latency_ms:.2f}.",
            request_id=request_id,
            caller_ip=_resolve_caller_ip(request),
            method=request.method,
            path=request.path,
            status=status,
            latency_ms=latency_ms,
        )


def _parse_positive_int(data: dict[str, Any], key: str) -> int:
    """Читает обязательное целое положительное поле."""

    value = data.get(key)
    number = int(value)
    if number <= 0:
        raise ValueError(f"{key} must be positive")
    return number


def _extract_signed_context(data: dict[str, Any]) -> tuple[int, int, str]:
    """Извлекает из запроса обязательные поля подписанного контекста."""

    uid = _parse_positive_int(data, "uid")
    ts = _parse_positive_int(data, "ts")
    sig = str(data.get("sig") or "").strip()
    if not sig:
        raise ValueError("sig is required")
    return uid, ts, sig


def _extract_bearer_token(request: web.Request) -> str:
    """Извлекает Bearer-токен из заголовка Authorization."""

    auth_header = str(request.headers.get("Authorization", "")).strip()
    if not auth_header.lower().startswith("bearer "):
        return ""
    return auth_header[7:].strip()


def _isoformat_utc(value: datetime | None) -> str | None:
    """Сериализует datetime в ISO-строку UTC."""

    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


async def _health_handler(request: web.Request) -> web.Response:
    """Healthcheck endpoint."""

    return _json_response_ok({"status": "ok", "service": "vk-phone-verification"})


async def _readiness_handler(request: web.Request) -> web.Response:
    """Readiness endpoint: проверяет конфигурацию сервиса и доступность PostgreSQL."""

    settings: AppSettings = request.app[_SETTINGS_KEY]
    session_factory: sessionmaker[Session] = request.app[_SESSION_FACTORY_KEY]
    checks: dict[str, str] = {
        "service_enabled": (
            "ok" if settings.vk_phone_verification_service_enabled else "disabled"
        ),
        "link_secret": "ok" if settings.vk_phone_verification_link_secret.strip() else "missing",
        "api_token": "ok" if settings.vk_phone_verification_api_token.strip() else "missing",
        "database": "unknown",
    }

    try:
        with session_factory() as db_session:
            db_session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as error:  # noqa: BLE001
        checks["database"] = "error"
        logger.bind(component=_COMPONENT, stage="readiness").warning(
            "Readiness Mini App сервиса не прошел проверку БД. request_id={request_id}, error={error}.",
            request_id=_get_request_id(request),
            error=str(error) or type(error).__name__,
        )

    is_ready = all(value == "ok" for value in checks.values())
    status_code = 200 if is_ready else 503
    if not is_ready:
        logger.bind(component=_COMPONENT, stage="readiness").warning(
            "Readiness Mini App сервиса вернул not_ready. request_id={request_id}, checks={checks}.",
            request_id=_get_request_id(request),
            checks=checks,
        )

    return web.json_response(
        {
            "status": "ok" if is_ready else "not_ready",
            "service": "vk-phone-verification",
            "checks": checks,
        },
        status=status_code,
    )


async def _miniapp_page_handler(request: web.Request) -> web.Response:
    """Возвращает HTML Mini App страницы подтверждения телефона."""

    return web.Response(text=_MINIAPP_HTML, content_type="text/html")


async def _session_start_handler(request: web.Request) -> web.Response:
    """Стартует или возвращает активную сессию подтверждения телефона."""

    settings: AppSettings = request.app[_SETTINGS_KEY]
    session_factory: sessionmaker[Session] = request.app[_SESSION_FACTORY_KEY]

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        logger.bind(component=_COMPONENT, stage="miniapp_session_start").warning(
            "Старт сессии Mini App отклонен: некорректный JSON. request_id={request_id}.",
            request_id=_get_request_id(request),
        )
        return _json_response_error(status=400, message="Некорректный JSON.")
    if not isinstance(payload, dict):
        logger.bind(component=_COMPONENT, stage="miniapp_session_start").warning(
            "Старт сессии Mini App отклонен: JSON payload не объект. request_id={request_id}.",
            request_id=_get_request_id(request),
        )
        return _json_response_error(status=400, message="JSON payload должен быть объектом.")

    try:
        vk_user_id = _parse_positive_int(payload, "vk_user_id")
        uid, ts, sig = _extract_signed_context(payload)
    except (TypeError, ValueError):
        logger.bind(component=_COMPONENT, stage="miniapp_session_start").warning(
            "Старт сессии Mini App отклонен: некорректные параметры. request_id={request_id}.",
            request_id=_get_request_id(request),
        )
        return _json_response_error(status=400, message="Некорректные параметры vk_user_id/uid/ts/sig.")

    if uid != vk_user_id:
        logger.bind(component=_COMPONENT, stage="miniapp_session_start", user_id=str(vk_user_id)).warning(
            "Старт сессии Mini App отклонен: uid не совпадает с vk_user_id. request_id={request_id}.",
            request_id=_get_request_id(request),
        )
        return _json_response_error(status=403, message="Подписанный uid не совпадает с vk_user_id.")

    is_valid_signature = verify_vk_phone_verification_signature(
        vk_user_id=uid,
        issued_at=ts,
        signature=sig,
        secret=settings.vk_phone_verification_link_secret,
        max_age_seconds=settings.vk_phone_verification_link_ttl_seconds,
    )
    if not is_valid_signature:
        logger.bind(component=_COMPONENT, stage="miniapp_session_start", user_id=str(vk_user_id)).warning(
            "Старт сессии Mini App отклонен: подпись ссылки недействительна или истекла. request_id={request_id}.",
            request_id=_get_request_id(request),
        )
        return _json_response_error(status=403, message="Подпись ссылки недействительна или истекла.")

    now_utc = datetime.now(timezone.utc)
    with session_factory() as db_session:
        repository = SQLAlchemyVkPhoneVerificationSessionRepository(db_session)
        repository.expire_outdated_created_sessions(now_utc=now_utc)
        session = repository.create_or_get_active_session(
            vk_user_id=vk_user_id,
            launch_uid=uid,
            launch_ts=ts,
            now_utc=now_utc,
            ttl_seconds=settings.vk_phone_verification_session_ttl_seconds,
            payload_json={"source": "miniapp_start"},
        )
        db_session.commit()

    logger.bind(component=_COMPONENT, stage="miniapp_session_start", user_id=str(vk_user_id)).info(
        "Сессия Mini App готова. request_id={request_id}, session_id={session_id}, status={status}.",
        request_id=_get_request_id(request),
        session_id=str(session.session_id),
        status=session.status,
    )
    return _json_response_ok(
        {
            "status": "created",
            "session_id": str(session.session_id),
            "expires_at": _isoformat_utc(session.expires_at),
        }
    )


async def _session_phone_handler(request: web.Request) -> web.Response:
    """Принимает номер телефона из Mini App и завершает сессию подтверждения."""

    settings: AppSettings = request.app[_SETTINGS_KEY]
    session_factory: sessionmaker[Session] = request.app[_SESSION_FACTORY_KEY]

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        logger.bind(component=_COMPONENT, stage="miniapp_phone_submit").warning(
            "Прием телефона Mini App отклонен: некорректный JSON. request_id={request_id}.",
            request_id=_get_request_id(request),
        )
        return _json_response_error(status=400, message="Некорректный JSON.")
    if not isinstance(payload, dict):
        logger.bind(component=_COMPONENT, stage="miniapp_phone_submit").warning(
            "Прием телефона Mini App отклонен: JSON payload не объект. request_id={request_id}.",
            request_id=_get_request_id(request),
        )
        return _json_response_error(status=400, message="JSON payload должен быть объектом.")

    try:
        session_id = UUID(str(payload.get("session_id") or "").strip())
        vk_user_id = _parse_positive_int(payload, "vk_user_id")
        uid, ts, sig = _extract_signed_context(payload)
        phone_raw = str(payload.get("phone") or "").strip()
        if not phone_raw:
            raise ValueError("phone is empty")
    except (TypeError, ValueError):
        logger.bind(component=_COMPONENT, stage="miniapp_phone_submit").warning(
            "Прием телефона Mini App отклонен: некорректные параметры. request_id={request_id}.",
            request_id=_get_request_id(request),
        )
        return _json_response_error(
            status=400,
            message="Некорректные параметры session_id/vk_user_id/uid/ts/sig/phone.",
        )

    if uid != vk_user_id:
        logger.bind(component=_COMPONENT, stage="miniapp_phone_submit", user_id=str(vk_user_id)).warning(
            "Прием телефона Mini App отклонен: uid не совпадает с vk_user_id. request_id={request_id}, session_id={session_id}.",
            request_id=_get_request_id(request),
            session_id=str(session_id),
        )
        return _json_response_error(status=403, message="Подписанный uid не совпадает с vk_user_id.")

    is_valid_signature = verify_vk_phone_verification_signature(
        vk_user_id=uid,
        issued_at=ts,
        signature=sig,
        secret=settings.vk_phone_verification_link_secret,
        max_age_seconds=settings.vk_phone_verification_link_ttl_seconds,
    )
    if not is_valid_signature:
        logger.bind(component=_COMPONENT, stage="miniapp_phone_submit", user_id=str(vk_user_id)).warning(
            "Прием телефона Mini App отклонен: подпись ссылки недействительна или истекла. request_id={request_id}, session_id={session_id}.",
            request_id=_get_request_id(request),
            session_id=str(session_id),
        )
        return _json_response_error(status=403, message="Подпись ссылки недействительна или истекла.")

    try:
        phone_e164 = normalize_phone(phone_raw)
    except ValueError:
        logger.bind(component=_COMPONENT, stage="miniapp_phone_submit", user_id=str(vk_user_id)).warning(
            "Прием телефона Mini App отклонен: номер не нормализован. request_id={request_id}, session_id={session_id}.",
            request_id=_get_request_id(request),
            session_id=str(session_id),
        )
        return _json_response_error(status=400, message="Не удалось нормализовать номер телефона.")

    now_utc = datetime.now(timezone.utc)
    with session_factory() as db_session:
        repository = SQLAlchemyVkPhoneVerificationSessionRepository(db_session)
        repository.expire_outdated_created_sessions(now_utc=now_utc)
        row = repository.get_session_by_id_for_update(session_id=session_id)
        if row is None:
            logger.bind(component=_COMPONENT, stage="miniapp_phone_submit", user_id=str(vk_user_id)).warning(
                "Прием телефона Mini App отклонен: сессия не найдена. request_id={request_id}, session_id={session_id}.",
                request_id=_get_request_id(request),
                session_id=str(session_id),
            )
            return _json_response_error(status=404, message="Сессия не найдена.")
        if row.vk_user_id != vk_user_id:
            logger.bind(component=_COMPONENT, stage="miniapp_phone_submit", user_id=str(vk_user_id)).warning(
                "Прием телефона Mini App отклонен: сессия принадлежит другому VK пользователю. request_id={request_id}, session_id={session_id}.",
                request_id=_get_request_id(request),
                session_id=str(session_id),
            )
            return _json_response_error(status=403, message="Сессия принадлежит другому VK пользователю.")

        session_snapshot = repository.mark_expired_if_needed(row=row, now_utc=now_utc)
        if session_snapshot.status == "expired":
            db_session.commit()
            logger.bind(component=_COMPONENT, stage="miniapp_phone_submit", user_id=str(vk_user_id)).info(
                "Сессия Mini App истекла до приема телефона. request_id={request_id}, session_id={session_id}.",
                request_id=_get_request_id(request),
                session_id=str(session_id),
            )
            return _json_response_error(status=410, message="Сессия истекла. Вернитесь в бот и начните снова.")
        if session_snapshot.status == "verified" and session_snapshot.phone_e164:
            db_session.commit()
            logger.bind(component=_COMPONENT, stage="miniapp_phone_submit", user_id=str(vk_user_id)).info(
                "Сессия Mini App уже была подтверждена ранее. request_id={request_id}, session_id={session_id}.",
                request_id=_get_request_id(request),
                session_id=str(session_snapshot.session_id),
            )
            return _json_response_ok(
                {
                    "status": "verified",
                    "session_id": str(session_snapshot.session_id),
                    "phone_e164": session_snapshot.phone_e164,
                }
            )

        verified_session = repository.mark_verified(
            row=row,
            phone_e164=phone_e164,
            now_utc=now_utc,
            payload_json={"source": "miniapp_phone", "raw_phone": phone_raw},
        )
        db_session.commit()

    logger.bind(component=_COMPONENT, stage="miniapp_phone_submit", user_id=str(vk_user_id)).info(
        "Телефон Mini App подтвержден. request_id={request_id}, session_id={session_id}.",
        request_id=_get_request_id(request),
        session_id=str(verified_session.session_id),
    )
    return _json_response_ok(
        {
            "status": "verified",
            "session_id": str(verified_session.session_id),
            "phone_e164": verified_session.phone_e164,
        }
    )


async def _session_status_handler(request: web.Request) -> web.Response:
    """Отдает статус подтверждения телефона для polling со стороны VK-бота."""

    settings: AppSettings = request.app[_SETTINGS_KEY]
    session_factory: sessionmaker[Session] = request.app[_SESSION_FACTORY_KEY]

    provided_token = _extract_bearer_token(request)
    expected_token = settings.vk_phone_verification_api_token.strip()
    if not expected_token or provided_token != expected_token:
        logger.bind(component=_COMPONENT, stage="miniapp_status_check").warning(
            "Проверка статуса Mini App отклонена по токену. request_id={request_id}.",
            request_id=_get_request_id(request),
        )
        return _json_response_error(status=401, message="unauthorized")

    raw_vk_user_id = str(request.query.get("vk_user_id") or "").strip()
    try:
        vk_user_id = int(raw_vk_user_id)
        if vk_user_id <= 0:
            raise ValueError
    except ValueError:
        logger.bind(component=_COMPONENT, stage="miniapp_status_check").warning(
            "Проверка статуса Mini App отклонена: некорректный vk_user_id. request_id={request_id}.",
            request_id=_get_request_id(request),
        )
        return _json_response_error(status=400, message="Некорректный vk_user_id.")

    now_utc = datetime.now(timezone.utc)
    with session_factory() as db_session:
        repository = SQLAlchemyVkPhoneVerificationSessionRepository(db_session)
        repository.expire_outdated_created_sessions(now_utc=now_utc)
        session = repository.get_latest_session_for_vk_user(vk_user_id=vk_user_id)
        db_session.commit()

    if session is None:
        logger.bind(component=_COMPONENT, stage="miniapp_status_check", user_id=str(vk_user_id)).info(
            "Статус Mini App для VK пользователя: not_found. request_id={request_id}.",
            request_id=_get_request_id(request),
        )
        return _json_response_ok({"status": "not_found"})
    if session.status == "verified" and session.phone_e164:
        logger.bind(component=_COMPONENT, stage="miniapp_status_check", user_id=str(vk_user_id)).info(
            "Статус Mini App для VK пользователя: verified. request_id={request_id}, session_id={session_id}.",
            request_id=_get_request_id(request),
            session_id=str(session.session_id),
        )
        return _json_response_ok(
            {
                "status": "verified",
                "phone_e164": session.phone_e164,
            }
        )
    if session.status == "failed":
        logger.bind(component=_COMPONENT, stage="miniapp_status_check", user_id=str(vk_user_id)).info(
            "Статус Mini App для VK пользователя: failed. request_id={request_id}, session_id={session_id}.",
            request_id=_get_request_id(request),
            session_id=str(session.session_id),
        )
        return _json_response_ok(
            {
                "status": "failed",
                "message": session.failure_reason or "Проверка завершилась ошибкой.",
            }
        )
    if session.status == "created":
        logger.bind(component=_COMPONENT, stage="miniapp_status_check", user_id=str(vk_user_id)).info(
            "Статус Mini App для VK пользователя: pending. request_id={request_id}, session_id={session_id}.",
            request_id=_get_request_id(request),
            session_id=str(session.session_id),
        )
        return _json_response_ok({"status": "pending"})
    logger.bind(component=_COMPONENT, stage="miniapp_status_check", user_id=str(vk_user_id)).info(
        "Статус Mini App для VK пользователя: not_found из терминального статуса. request_id={request_id}, session_id={session_id}, source_status={source_status}.",
        request_id=_get_request_id(request),
        session_id=str(session.session_id),
        source_status=session.status,
    )
    return _json_response_ok({"status": "not_found"})


def build_web_app(
    *,
    settings: AppSettings,
    session_factory: sessionmaker[Session],
) -> web.Application:
    """Собирает aiohttp web-приложение VK Mini App verification сервиса."""

    app = web.Application(
        client_max_size=_MAX_JSON_BODY_BYTES,
        middlewares=[_request_audit_middleware],
    )
    app[_SETTINGS_KEY] = settings
    app[_SESSION_FACTORY_KEY] = session_factory
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/ready", _readiness_handler)
    app.router.add_get("/vk/miniapp", _miniapp_page_handler)
    app.router.add_get("/api/v1/vk/miniapp/session/status", _session_status_handler)
    app.router.add_post("/api/v1/vk/miniapp/session/start", _session_start_handler)
    app.router.add_post("/api/v1/vk/miniapp/session/phone", _session_phone_handler)
    return app


async def _wait_for_shutdown_signal(component: str) -> None:
    """Ожидает SIGTERM/SIGINT и завершает no-op процесс."""

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


async def run_vk_phone_verification_service(settings: AppSettings | None = None) -> None:
    """Запускает отдельный web-сервис подтверждения телефона VK Mini App."""

    app_settings = settings or AppSettings()
    configure_logging(service_name="vk-miniapp-service", log_level=app_settings.log_level)
    app_logger = logger.bind(component=_COMPONENT, stage="startup")
    app_logger.info(
        "Инициализация VK Mini App verification service. ENV={env}.",
        env=app_settings.env,
    )

    if not app_settings.vk_phone_verification_service_enabled:
        app_logger.info("Сервис выключен (VK_PHONE_VERIFICATION_SERVICE_ENABLED=false).")
        await _wait_for_shutdown_signal(component=_COMPONENT)
        return

    if not app_settings.vk_phone_verification_link_secret.strip():
        app_logger.warning(
            "Сервис не запущен: не задан VK_PHONE_VERIFICATION_LINK_SECRET. "
            "Для безопасности endpoint'ы Mini App отключены."
        )
        await _wait_for_shutdown_signal(component=_COMPONENT)
        return

    if not app_settings.vk_phone_verification_api_token.strip():
        app_logger.warning(
            "Сервис не запущен: не задан VK_PHONE_VERIFICATION_API_TOKEN. "
            "Без токена status endpoint был бы небезопасен."
        )
        await _wait_for_shutdown_signal(component=_COMPONENT)
        return

    session_factory = build_postgres_session_factory(app_settings)
    web_app = build_web_app(settings=app_settings, session_factory=session_factory)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(
        runner,
        host=app_settings.vk_phone_verification_service_host,
        port=app_settings.vk_phone_verification_service_port,
    )
    await site.start()
    app_logger.info(
        "VK Mini App verification service запущен на {host}:{port}.",
        host=app_settings.vk_phone_verification_service_host,
        port=app_settings.vk_phone_verification_service_port,
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
        app_logger.info("VK Mini App verification service завершен.")


def main() -> None:
    """Синхронная точка входа для запуска сервиса из CLI/docker."""

    asyncio.run(run_vk_phone_verification_service())


if __name__ == "__main__":
    main()
