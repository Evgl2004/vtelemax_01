"""Entrypoint отдельного worker-процесса синхронизации профиля с iiko."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Callable

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker

from vtelemax.adapters.periodic_profile_sync_worker import PeriodicProfileSyncWorker
from vtelemax.adapters.profile_sync import ProfileSyncProcessor
from vtelemax.core import (
    FinalizeProfileSyncTaskTransactionalUseCase,
    GetPersonByIdTransactionalUseCase,
    PullPendingProfileSyncTasksTransactionalUseCase,
)
from vtelemax.infrastructure import IikoLoyaltyGateway, configure_logging
from vtelemax.infrastructure.postgres import SQLAlchemyIdentityUnitOfWork, build_engine, build_session_factory
from vtelemax.settings import AppSettings


def build_postgres_session_factory(settings: AppSettings) -> sessionmaker[Session]:
    """Создает PostgreSQL session factory для воркера."""

    engine = build_engine(settings.postgres_sqlalchemy_dsn, echo=settings.postgres_echo)
    return build_session_factory(engine)


def build_pull_pending_profile_sync_use_case(
    session_factory: sessionmaker[Session],
) -> PullPendingProfileSyncTasksTransactionalUseCase:
    """Собирает use-case выбора pending-задач profile_sync_queue."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return PullPendingProfileSyncTasksTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_finalize_profile_sync_use_case(
    session_factory: sessionmaker[Session],
) -> FinalizeProfileSyncTaskTransactionalUseCase:
    """Собирает use-case фиксации результата обработки profile_sync_queue."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return FinalizeProfileSyncTaskTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_get_person_by_id_use_case(
    session_factory: sessionmaker[Session],
) -> GetPersonByIdTransactionalUseCase:
    """Собирает use-case чтения пользователя по person_id."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return GetPersonByIdTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_iiko_gateway(settings: AppSettings) -> IikoLoyaltyGateway | None:
    """Собирает iiko-шлюз или возвращает `None`, если интеграция выключена."""

    if not settings.is_iiko_configured:
        return None
    return IikoLoyaltyGateway(
        api_key=settings.iiko_api_key,
        organization_id=settings.iiko_org_id,
        base_url=settings.iiko_base_url,
    )


async def _wait_for_shutdown_signal(component: str) -> None:
    """Ожидает SIGTERM/SIGINT и завершает no-op процесс."""

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


async def run_profile_sync_worker(settings: AppSettings | None = None) -> None:
    """Запускает отдельный periodic worker синхронизации профиля."""

    app_settings = settings or AppSettings()
    configure_logging(service_name="profile-sync-worker", log_level=app_settings.log_level)
    app_logger = logger.bind(component="profile_sync_worker_app", stage="startup")
    app_logger.info("Инициализация profile sync worker. ENV={env}.", env=app_settings.env)

    if not app_settings.profile_sync_enabled:
        app_logger.info("Profile sync worker выключен (PROFILE_SYNC_ENABLED=false).")
        await _wait_for_shutdown_signal(component="profile_sync_worker_app")
        return

    iiko_gateway = build_iiko_gateway(app_settings)
    if iiko_gateway is None:
        app_logger.warning(
            "Profile sync worker запущен без iiko-конфигурации. "
            "Укажите IIKO_API_KEY и IIKO_ORG_ID либо выключите PROFILE_SYNC_ENABLED."
        )
        await _wait_for_shutdown_signal(component="profile_sync_worker_app")
        return

    session_factory = build_postgres_session_factory(app_settings)
    pull_pending_use_case = build_pull_pending_profile_sync_use_case(session_factory)
    finalize_use_case = build_finalize_profile_sync_use_case(session_factory)
    person_lookup_use_case = build_get_person_by_id_use_case(session_factory)

    processor = ProfileSyncProcessor(
        pull_pending_use_case=pull_pending_use_case,
        finalize_task_use_case=finalize_use_case,
        person_lookup_use_case=person_lookup_use_case,
        loyalty_gateway=iiko_gateway,
        max_attempts=app_settings.profile_sync_max_attempts,
    )
    worker = PeriodicProfileSyncWorker(
        processor=processor,
        interval_seconds=app_settings.profile_sync_interval_seconds,
        batch_limit=app_settings.profile_sync_batch_limit,
    )

    stop_event = asyncio.Event()

    def _request_shutdown(source: str) -> None:
        if stop_event.is_set():
            return
        logger.bind(component="profile_sync_worker_app", stage="shutdown").info(
            "Получен сигнал остановки worker: {source}.",
            source=source,
        )
        stop_event.set()

    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(stop_signal, _request_shutdown, stop_signal.name)

    worker_task = asyncio.create_task(worker.run_forever(), name="profile_sync_worker")
    try:
        await stop_event.wait()
    finally:
        await worker.shutdown()
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
        app_logger.info("Profile sync worker завершен.")


def main() -> None:
    """Синхронная точка входа для запуска worker из CLI/docker."""

    asyncio.run(run_profile_sync_worker())


if __name__ == "__main__":
    main()

