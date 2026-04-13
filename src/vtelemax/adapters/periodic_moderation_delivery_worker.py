"""Периодический воркер доставки pending-сообщений модерации.

MVP-контур:
1. Периодически запускает `process_once` для целевой платформы.
2. Работает автономно (без входящих апдейтов пользователей).
3. Без ретраев failed-сообщений (ретраи — отдельный этап развития).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from loguru import logger

from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor
from vtelemax.core import PendingModeratorDelivery, PlatformName


@dataclass(slots=True)
class PeriodicPendingDeliveryWorker:
    """Периодический доставщик pending-сообщений для одной платформы."""

    target_platform: PlatformName
    processor: PendingModeratorDeliveryProcessor
    sender: Callable[[PendingModeratorDelivery, str], Awaitable[None]]
    interval_seconds: float = 15.0
    batch_limit: int = 20
    lock: asyncio.Lock | None = None
    _stop_event: asyncio.Event = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds должен быть больше 0.")
        if self.batch_limit <= 0:
            raise ValueError("batch_limit должен быть больше 0.")
        self._stop_event = asyncio.Event()

    async def run_forever(self) -> None:
        """Запускает периодический цикл обработки до сигнала остановки."""

        worker_logger = logger.bind(
            platform=self.target_platform,
            component="moderation_delivery_worker",
            stage="run_forever",
        )
        worker_logger.info(
            "Periodic worker запущен. interval={interval}s, limit={limit}.",
            interval=self.interval_seconds,
            limit=self.batch_limit,
        )
        try:
            while not self._stop_event.is_set():
                await self.process_once()
                await self._wait_for_next_tick()
        except asyncio.CancelledError:
            worker_logger.info("Periodic worker остановлен по отмене задачи.")
            raise
        finally:
            worker_logger.info("Periodic worker завершил работу.")

    async def process_once(self) -> tuple[int, int]:
        """Выполняет один периодический проход."""

        if self.lock is None:
            return await self._process_once_internal()

        if self.lock.locked():
            logger.bind(
                platform=self.target_platform,
                component="moderation_delivery_worker",
                stage="lock_wait",
            ).debug("Пропуск прохода: предыдущая доставка pending ещё выполняется.")
            return 0, 0

        async with self.lock:
            return await self._process_once_internal()

    async def shutdown(self) -> None:
        """Запрашивает мягкую остановку воркера."""

        if self._stop_event.is_set():
            return
        logger.bind(
            platform=self.target_platform,
            component="moderation_delivery_worker",
            stage="shutdown",
        ).info("Получен сигнал остановки periodic worker.")
        self._stop_event.set()

    async def _process_once_internal(self) -> tuple[int, int]:
        """Внутренний проход с обработкой исключений."""

        worker_logger = logger.bind(
            platform=self.target_platform,
            component="moderation_delivery_worker",
            stage="process_once",
        )
        try:
            sent_count, failed_count = await self.processor.process_once(
                sender=self.sender,
                limit=self.batch_limit,
            )
        except Exception:  # noqa: BLE001
            worker_logger.exception("Ошибка periodic-обработки pending-сообщений.")
            return 0, 0

        worker_logger.debug(
            "Periodic-проход завершен. sent={sent}, failed={failed}.",
            sent=sent_count,
            failed=failed_count,
        )
        return sent_count, failed_count

    async def _wait_for_next_tick(self) -> None:
        """Ждёт следующий тик или сигнал остановки."""

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)

