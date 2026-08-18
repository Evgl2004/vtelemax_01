"""Отдельный entrypoint periodic worker доставки pending-сообщений модерации.

Процесс запускается как самостоятельный контейнер/процесс и не смешивается
с жизненным циклом polling-процесса бота.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker

from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor
from vtelemax.adapters.periodic_moderation_delivery_worker import PeriodicPendingDeliveryWorker
from vtelemax.core import (
    PendingModeratorDelivery,
    PlatformName,
    PullPendingModeratorMessagesTransactionalUseCase,
    UpdateModeratorMessageDeliveryStatusTransactionalUseCase,
)
from vtelemax.infrastructure import configure_logging
from vtelemax.infrastructure.postgres import (
    SQLAlchemyIdentityUnitOfWork,
    build_engine,
    build_session_factory,
)
from vtelemax.settings import AppSettings

WorkerPlatform = Literal["telegram", "vk", "max"]
DeliverySender = Callable[[PendingModeratorDelivery, str], Awaitable[None]]
AsyncCleanup = Callable[[], Awaitable[None]]


@dataclass(slots=True)
class WorkerRuntime:
    """Ресурсы платформы для работы delivery worker."""

    sender: DeliverySender
    cleanup: AsyncCleanup | None = None


def build_postgres_session_factory(settings: AppSettings) -> sessionmaker[Session]:
    """Создает PostgreSQL session factory для воркера."""

    engine = build_engine(settings.postgres_sqlalchemy_dsn, echo=settings.postgres_echo)
    return build_session_factory(engine)


def build_pull_pending_messages_use_case(
    session_factory: sessionmaker[Session],
) -> PullPendingModeratorMessagesTransactionalUseCase:
    """Собирает use-case выборки pending-сообщений модератора."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return PullPendingModeratorMessagesTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_update_delivery_status_use_case(
    session_factory: sessionmaker[Session],
) -> UpdateModeratorMessageDeliveryStatusTransactionalUseCase:
    """Собирает use-case фиксации статуса доставки pending-сообщения."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return UpdateModeratorMessageDeliveryStatusTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_delivery_processor(
    session_factory: sessionmaker[Session],
    *,
    target_platform: PlatformName,
) -> PendingModeratorDeliveryProcessor:
    """Собирает delivery processor для целевой платформы."""

    pull_pending_use_case = build_pull_pending_messages_use_case(session_factory)
    update_status_use_case = build_update_delivery_status_use_case(session_factory)
    return PendingModeratorDeliveryProcessor(
        target_platform=target_platform,
        pull_pending_use_case=pull_pending_use_case,
        update_status_use_case=update_status_use_case,
    )


async def _maybe_await(result: Any) -> None:
    """Ожидает результат, если это awaitable-объект."""

    if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
        await cast(Awaitable[None], result)


def _build_telegram_runtime(settings: AppSettings) -> WorkerRuntime:
    """Создает sender и cleanup для Telegram-доставки."""

    settings.validate_telegram_ready()
    try:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.client.session.aiohttp import AiohttpSession
        from aiogram.enums import ParseMode
    except ImportError as exc:  # pragma: no cover - защитный runtime-кейс
        raise RuntimeError(
            "Для запуска Telegram delivery-worker установите зависимости: pip install -e .[telegram]"
        ) from exc

    from vtelemax.adapters.telegram.router import build_telegram_pending_delivery_sender

    telegram_session = AiohttpSession(
        proxy=settings.telegram_proxy_url.strip() or None,
    )
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=telegram_session,
    )
    sender = build_telegram_pending_delivery_sender(bot)

    async def _cleanup() -> None:
        await bot.session.close()

    return WorkerRuntime(sender=sender, cleanup=_cleanup)


def _build_vk_runtime(settings: AppSettings) -> WorkerRuntime:
    """Создает sender и cleanup для VK-доставки."""

    settings.validate_vk_ready()
    try:
        from vkbottle.bot import Bot
    except ImportError as exc:  # pragma: no cover - защитный runtime-кейс
        raise RuntimeError(
            "Для запуска VK delivery-worker установите зависимости: pip install -e .[vk]"
        ) from exc

    from vtelemax.adapters.vk.router import build_vk_pending_delivery_sender

    bot = Bot(settings.vk_bot_token)
    sender = build_vk_pending_delivery_sender(bot)

    async def _cleanup() -> None:
        with contextlib.suppress(Exception):
            http_client = getattr(bot.api, "http_client", None)
            if http_client is not None:
                close_method = getattr(http_client, "close", None)
                if callable(close_method):
                    await _maybe_await(close_method())

    return WorkerRuntime(sender=sender, cleanup=_cleanup)


def _build_max_runtime(settings: AppSettings) -> WorkerRuntime:
    """Создает sender для MAX-доставки."""

    settings.validate_max_ready()
    try:
        from maxapi import Bot
    except ImportError as exc:  # pragma: no cover - защитный runtime-кейс
        raise RuntimeError(
            "Для запуска MAX delivery-worker установите зависимости: pip install -e .[max]"
        ) from exc

    from vtelemax.adapters.max.router import build_max_pending_delivery_sender

    bot = Bot(token=settings.max_bot_token)
    sender = build_max_pending_delivery_sender(bot)
    return WorkerRuntime(sender=sender, cleanup=None)


def build_runtime_for_platform(settings: AppSettings, *, platform: WorkerPlatform) -> WorkerRuntime:
    """Строит платформо-специфичный runtime для delivery worker."""

    if platform == "telegram":
        return _build_telegram_runtime(settings)
    if platform == "vk":
        return _build_vk_runtime(settings)
    if platform == "max":
        return _build_max_runtime(settings)
    raise ValueError(f"Неподдерживаемая платформа worker: {platform}.")


async def run_delivery_worker(
    *,
    platform: WorkerPlatform,
    settings: AppSettings | None = None,
) -> None:
    """Запускает отдельный periodic worker доставки pending-сообщений."""

    app_settings = settings or AppSettings()
    configure_logging(service_name=f"{platform}-delivery-worker", log_level=app_settings.log_level)
    app_logger = logger.bind(platform=platform, component="delivery_worker_app", stage="startup")
    app_logger.info("Инициализация delivery worker. ENV={env}.", env=app_settings.env)

    session_factory = build_postgres_session_factory(app_settings)
    delivery_processor = build_delivery_processor(
        session_factory,
        target_platform=cast(PlatformName, platform),
    )
    runtime = build_runtime_for_platform(app_settings, platform=platform)

    worker = PeriodicPendingDeliveryWorker(
        target_platform=cast(PlatformName, platform),
        processor=delivery_processor,
        sender=runtime.sender,
        interval_seconds=app_settings.moderation_delivery_interval_seconds,
        batch_limit=app_settings.moderation_delivery_batch_limit,
    )

    stop_event = asyncio.Event()

    def _request_shutdown(source: str) -> None:
        if stop_event.is_set():
            return
        logger.bind(platform=platform, component="delivery_worker_app", stage="shutdown").info(
            "Получен сигнал остановки воркера: {source}.",
            source=source,
        )
        stop_event.set()

    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(stop_signal, _request_shutdown, stop_signal.name)

    worker_task = asyncio.create_task(
        worker.run_forever(),
        name=f"{platform}_moderation_delivery_worker",
    )

    try:
        await stop_event.wait()
    finally:
        await worker.shutdown()
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
        if runtime.cleanup is not None:
            await runtime.cleanup()
        app_logger.info("Delivery worker завершен.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Парсит CLI-аргументы запуска delivery worker."""

    parser = argparse.ArgumentParser(
        description=(
            "Запуск отдельного periodic worker доставки pending-сообщений модерации "
            "для выбранной платформы."
        )
    )
    parser.add_argument(
        "--platform",
        required=True,
        choices=("telegram", "vk", "max"),
        help="Целевая платформа worker (telegram|vk|max).",
    )
    return parser.parse_args(argv)


def main() -> None:
    """Синхронная точка входа запуска отдельного delivery worker."""

    args = parse_args()
    asyncio.run(run_delivery_worker(platform=cast(WorkerPlatform, args.platform)))


if __name__ == "__main__":
    main()
