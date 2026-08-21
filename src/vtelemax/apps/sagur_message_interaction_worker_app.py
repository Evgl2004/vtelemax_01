"""Точка входа отдельного работника доставки нажатий кнопок в SAGUR."""

from __future__ import annotations

import asyncio
import contextlib
import signal

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker

from vtelemax.adapters.sagur_message_interaction_delivery import (
    PeriodicSagurMessageInteractionWorker,
    SagurMessageInteractionDeliveryProcessor,
    SagurMessageInteractionHttpClient,
)
from vtelemax.infrastructure import configure_logging
from vtelemax.infrastructure.postgres import build_engine, build_session_factory
from vtelemax.settings import AppSettings


def build_postgres_session_factory(settings: AppSettings) -> sessionmaker[Session]:
    """Создаёт фабрику коротких транзакций PostgreSQL для очереди нажатий."""

    engine = build_engine(settings.postgres_sqlalchemy_dsn, echo=settings.postgres_echo)
    return build_session_factory(engine)


def _install_shutdown_signal_handlers(stop_event: asyncio.Event, *, component: str) -> None:
    """Связывает SIGTERM/SIGINT с единым событием мягкой остановки."""

    def _request_shutdown(source: str) -> None:
        if stop_event.is_set():
            return
        logger.bind(component=component, stage="shutdown").info(
            "Получен сигнал остановки работника: {source}.",
            source=source,
        )
        stop_event.set()

    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(stop_signal, _request_shutdown, stop_signal.name)


async def _wait_for_shutdown_signal(component: str) -> None:
    """Ожидает сигнал завершения в безопасном выключенном режиме."""

    stop_event = asyncio.Event()
    _install_shutdown_signal_handlers(stop_event, component=component)
    await stop_event.wait()


async def run_sagur_message_interaction_worker(settings: AppSettings | None = None) -> None:
    """Собирает зависимости и запускает последовательную пакетную доставку."""

    app_settings = settings or AppSettings()
    configure_logging(
        service_name="sagur-message-interaction-worker",
        log_level=app_settings.log_level,
    )
    app_logger = logger.bind(
        component="sagur_message_interaction_worker_app",
        stage="startup",
    )
    app_logger.info(
        "Инициализация работника доставки нажатий SAGUR. ENV={env}.",
        env=app_settings.env,
    )

    if not app_settings.sagur_message_interaction_sync_enabled:
        app_logger.info(
            "Работник доставки нажатий SAGUR выключен "
            "(SAGUR_MESSAGE_INTERACTION_SYNC_ENABLED=false)."
        )
        await _wait_for_shutdown_signal("sagur_message_interaction_worker_app")
        return

    hmac_secret = app_settings.sagur_message_interactions_hmac_secret
    if not hmac_secret:
        app_logger.error(
            "Работник доставки нажатий SAGUR не запущен: укажите "
            "SAGUR_MESSAGE_INTERACTION_SYNC_HMAC_SECRET или "
            "SAGUR_INTEGRATION_HMAC_SECRET."
        )
        await _wait_for_shutdown_signal("sagur_message_interaction_worker_app")
        return

    session_factory = build_postgres_session_factory(app_settings)
    http_client = SagurMessageInteractionHttpClient(
        base_url=app_settings.sagur_message_interaction_sync_base_url,
        endpoint_path=app_settings.sagur_message_interaction_sync_endpoint,
        hmac_secret=hmac_secret,
        timeout_seconds=app_settings.sagur_message_interaction_sync_http_timeout_seconds,
        max_response_bytes=app_settings.sagur_message_interaction_sync_max_response_bytes,
        require_https=app_settings.sagur_message_interaction_sync_require_https,
    )
    processor = SagurMessageInteractionDeliveryProcessor(
        session_factory=session_factory,
        http_client=http_client,
        batch_size=app_settings.sagur_message_interaction_sync_batch_size,
        retry_base_seconds=app_settings.sagur_message_interaction_sync_retry_base_seconds,
        retry_max_seconds=app_settings.sagur_message_interaction_sync_retry_max_seconds,
        lock_timeout_seconds=app_settings.sagur_message_interaction_sync_lock_timeout_seconds,
    )
    worker = PeriodicSagurMessageInteractionWorker(
        processor=processor,
        interval_seconds=app_settings.sagur_message_interaction_sync_schedule_minutes * 60,
    )
    stop_event = asyncio.Event()
    _install_shutdown_signal_handlers(
        stop_event,
        component="sagur_message_interaction_worker_app",
    )

    worker_task = asyncio.create_task(
        worker.run_forever(),
        name="sagur_message_interaction_worker",
    )
    try:
        await stop_event.wait()
    finally:
        await worker.shutdown()
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
        await http_client.close()
        app_logger.info("Работник доставки нажатий SAGUR завершён.")


def main() -> None:
    """Синхронная точка входа для Docker и командной строки."""

    asyncio.run(run_sagur_message_interaction_worker())


if __name__ == "__main__":
    main()
