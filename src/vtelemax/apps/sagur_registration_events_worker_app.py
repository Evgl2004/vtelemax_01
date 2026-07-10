"""Entrypoint worker исходящих событий регистрации гостей в SAGUR."""

from __future__ import annotations

import asyncio
import contextlib
import signal

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker

from vtelemax.adapters.sagur_registration_events import (
    PeriodicSagurRegistrationEventsWorker,
    SagurRegistrationEventsProcessor,
    SagurRegistrationHttpClient,
    SagurRegistrationRecoveryProcessor,
)
from vtelemax.infrastructure import IikoLoyaltyGateway, configure_logging
from vtelemax.infrastructure.postgres import build_engine, build_session_factory
from vtelemax.settings import AppSettings


def build_postgres_session_factory(settings: AppSettings) -> sessionmaker[Session]:
    """Создает PostgreSQL session factory для worker."""

    engine = build_engine(settings.postgres_sqlalchemy_dsn, echo=settings.postgres_echo)
    return build_session_factory(engine)


def build_iiko_gateway(settings: AppSettings) -> IikoLoyaltyGateway | None:
    """Собирает iiko-шлюз для контрольного поиска восстановления."""

    if not settings.is_iiko_configured:
        return None
    return IikoLoyaltyGateway(
        api_key=settings.iiko_api_key,
        organization_id=settings.iiko_org_id,
        base_url=settings.iiko_base_url,
    )


async def _wait_for_shutdown_signal(component: str) -> None:
    """Ожидает SIGTERM/SIGINT для no-op режима worker."""

    stop_event = asyncio.Event()

    def _request_shutdown(source: str) -> None:
        if stop_event.is_set():
            return
        logger.bind(component=component, stage="shutdown").info(
            "Получен сигнал остановки worker: {source}.",
            source=source,
        )
        stop_event.set()

    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(stop_signal, _request_shutdown, stop_signal.name)

    await stop_event.wait()


async def run_sagur_registration_events_worker(settings: AppSettings | None = None) -> None:
    """Запускает periodic worker исходящих событий регистрации SAGUR."""

    app_settings = settings or AppSettings()
    configure_logging(
        service_name="sagur-registration-events-worker",
        log_level=app_settings.log_level,
    )
    app_logger = logger.bind(component="sagur_registration_events_worker_app", stage="startup")
    app_logger.info("Инициализация SAGUR registration worker. ENV={env}.", env=app_settings.env)

    if not app_settings.sagur_registration_events_enabled:
        app_logger.info("SAGUR registration worker выключен (SAGUR_REGISTRATION_EVENTS_ENABLED=false).")
        await _wait_for_shutdown_signal(component="sagur_registration_events_worker_app")
        return

    hmac_secret = app_settings.sagur_registration_events_hmac_secret
    if not hmac_secret:
        app_logger.warning(
            "SAGUR registration worker запущен без HMAC-секрета. "
            "Укажите VTELEMAX_REGISTRATION_CALLBACK_HMAC_SECRET."
        )
        await _wait_for_shutdown_signal(component="sagur_registration_events_worker_app")
        return

    session_factory = build_postgres_session_factory(app_settings)
    http_client = SagurRegistrationHttpClient(
        endpoint=app_settings.sagur_registration_events_endpoint,
        hmac_secret=hmac_secret,
        timeout_seconds=app_settings.sagur_registration_events_timeout_seconds,
    )
    delivery_processor = SagurRegistrationEventsProcessor(
        session_factory=session_factory,
        http_client=http_client,
        max_attempts=app_settings.sagur_registration_events_max_attempts,
        lock_timeout_seconds=app_settings.sagur_registration_events_lock_timeout_seconds,
    )

    recovery_processor = None
    if app_settings.sagur_registration_events_recovery_enabled:
        iiko_gateway = build_iiko_gateway(app_settings)
        if iiko_gateway is None:
            app_logger.warning(
                "Восстановление SAGUR registration выключено: не заданы IIKO_API_KEY/IIKO_ORG_ID."
            )
        else:
            recovery_processor = SagurRegistrationRecoveryProcessor(
                session_factory=session_factory,
                loyalty_gateway=iiko_gateway,
                max_attempts=app_settings.sagur_registration_events_recovery_max_attempts,
            )

    worker = PeriodicSagurRegistrationEventsWorker(
        delivery_processor=delivery_processor,
        recovery_processor=recovery_processor,
        interval_seconds=app_settings.sagur_registration_events_interval_seconds,
        batch_limit=app_settings.sagur_registration_events_batch_limit,
        recovery_interval_seconds=app_settings.sagur_registration_events_recovery_interval_seconds,
        recovery_batch_limit=app_settings.sagur_registration_events_recovery_batch_limit,
    )

    stop_event = asyncio.Event()

    def _request_shutdown(source: str) -> None:
        if stop_event.is_set():
            return
        logger.bind(component="sagur_registration_events_worker_app", stage="shutdown").info(
            "Получен сигнал остановки worker: {source}.",
            source=source,
        )
        stop_event.set()

    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(stop_signal, _request_shutdown, stop_signal.name)

    worker_task = asyncio.create_task(worker.run_forever(), name="sagur_registration_events_worker")
    try:
        await stop_event.wait()
    finally:
        await worker.shutdown()
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
        app_logger.info("SAGUR registration worker завершен.")


def main() -> None:
    """Синхронная точка входа для запуска worker из CLI/docker."""

    asyncio.run(run_sagur_registration_events_worker())


if __name__ == "__main__":
    main()
