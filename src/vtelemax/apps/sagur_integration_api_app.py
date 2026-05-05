"""Entrypoint for SAGUR integration read-only API service."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from datetime import datetime, timezone
from typing import Any

from aiohttp import web
from loguru import logger

from vtelemax.infrastructure import configure_logging
from vtelemax.settings import AppSettings

_COMPONENT = "sagur_integration_api_app"
_MAX_JSON_BODY_BYTES = 8 * 1024
_SETTINGS_KEY = web.AppKey("settings", AppSettings)


def _json_response_ok(payload: dict[str, Any]) -> web.Response:
    return web.json_response(payload, status=200)


def _json_response_error(*, status: int, message: str) -> web.Response:
    return web.json_response({"status": "error", "message": message}, status=status)


async def _health_handler(request: web.Request) -> web.Response:
    return _json_response_ok({"status": "ok", "service": "sagur-integration-api"})


async def _snapshot_handler(request: web.Request) -> web.Response:
    return _json_response_error(status=501, message="snapshot endpoint is not implemented yet")


async def _delta_handler(request: web.Request) -> web.Response:
    return _json_response_error(status=501, message="delta endpoint is not implemented yet")


def build_web_app(*, settings: AppSettings) -> web.Application:
    app = web.Application(client_max_size=_MAX_JSON_BODY_BYTES)
    app[_SETTINGS_KEY] = settings
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/internal/integration/v1/sagur/recipients/snapshot", _snapshot_handler)
    app.router.add_get("/internal/integration/v1/sagur/recipients/delta", _delta_handler)
    return app


async def _wait_for_shutdown_signal(component: str) -> None:
    stop_event = asyncio.Event()

    def _request_shutdown(source: str) -> None:
        if stop_event.is_set():
            return
        logger.bind(component=component, stage="shutdown").info(
            "Shutdown signal received: {source}.",
            source=source,
        )
        stop_event.set()

    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(stop_signal, _request_shutdown, stop_signal.name)

    await stop_event.wait()


def _validate_service_settings(settings: AppSettings) -> None:
    if settings.sagur_integration_default_limit > settings.sagur_integration_max_limit:
        raise ValueError(
            "SAGUR_INTEGRATION_DEFAULT_LIMIT must be less than or equal to "
            "SAGUR_INTEGRATION_MAX_LIMIT."
        )


async def run_sagur_integration_api(settings: AppSettings | None = None) -> None:
    app_settings = settings or AppSettings()
    configure_logging(service_name="sagur-integration-api", log_level=app_settings.log_level)
    app_logger = logger.bind(component=_COMPONENT, stage="startup")
    app_logger.info("Initializing SAGUR integration API. ENV={env}.", env=app_settings.env)

    if not app_settings.sagur_integration_api_enabled:
        app_logger.info("Service disabled (SAGUR_INTEGRATION_API_ENABLED=false).")
        await _wait_for_shutdown_signal(component=_COMPONENT)
        return

    _validate_service_settings(app_settings)

    web_app = build_web_app(settings=app_settings)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(
        runner,
        host=app_settings.sagur_integration_service_host,
        port=app_settings.sagur_integration_service_port,
    )
    await site.start()
    app_logger.info(
        "SAGUR integration API started on {host}:{port} at {started_at}.",
        host=app_settings.sagur_integration_service_host,
        port=app_settings.sagur_integration_service_port,
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    stop_event = asyncio.Event()

    def _request_shutdown(source: str) -> None:
        if stop_event.is_set():
            return
        logger.bind(component=_COMPONENT, stage="shutdown").info(
            "Shutdown signal received: {source}.",
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
        app_logger.info("SAGUR integration API stopped.")


def main() -> None:
    asyncio.run(run_sagur_integration_api())


if __name__ == "__main__":
    main()
