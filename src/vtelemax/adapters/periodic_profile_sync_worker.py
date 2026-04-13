"""Периодический воркер обработки очереди синхронизации профиля."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field

from loguru import logger

from vtelemax.adapters.profile_sync import ProfileSyncProcessor, log_profile_sync_cycle


@dataclass(slots=True)
class PeriodicProfileSyncWorker:
    """Периодически обрабатывает `profile_sync_queue` до сигнала остановки."""

    processor: ProfileSyncProcessor
    interval_seconds: float = 15.0
    batch_limit: int = 50
    lock: asyncio.Lock | None = None
    _stop_event: asyncio.Event = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds должен быть больше 0.")
        if self.batch_limit <= 0:
            raise ValueError("batch_limit должен быть больше 0.")
        self._stop_event = asyncio.Event()

    async def run_forever(self) -> None:
        """Запускает периодический цикл обработки очереди."""

        worker_logger = logger.bind(component="profile_sync_worker", stage="run_forever")
        worker_logger.info(
            "Profile sync worker запущен. interval={interval}s, limit={limit}.",
            interval=self.interval_seconds,
            limit=self.batch_limit,
        )
        try:
            while not self._stop_event.is_set():
                await self.process_once()
                await self._wait_for_next_tick()
        except asyncio.CancelledError:
            worker_logger.info("Profile sync worker остановлен по отмене задачи.")
            raise
        finally:
            worker_logger.info("Profile sync worker завершил работу.")

    async def process_once(self) -> tuple[int, int, int]:
        """Выполняет один периодический проход."""

        if self.lock is None:
            return await self._process_once_internal()

        if self.lock.locked():
            logger.bind(component="profile_sync_worker", stage="lock_wait").debug(
                "Пропуск прохода: предыдущая обработка profile_sync_queue еще выполняется."
            )
            return 0, 0, 0

        async with self.lock:
            return await self._process_once_internal()

    async def shutdown(self) -> None:
        """Запрашивает мягкую остановку воркера."""

        if self._stop_event.is_set():
            return
        logger.bind(component="profile_sync_worker", stage="shutdown").info(
            "Получен сигнал остановки profile sync worker."
        )
        self._stop_event.set()

    async def _process_once_internal(self) -> tuple[int, int, int]:
        """Внутренний проход с обработкой исключений."""

        worker_logger = logger.bind(component="profile_sync_worker", stage="process_once")
        try:
            done_count, failed_count, rescheduled_count = await self.processor.process_once(
                limit=self.batch_limit
            )
        except Exception:  # noqa: BLE001
            worker_logger.exception("Ошибка periodic-обработки profile_sync_queue.")
            return 0, 0, 0

        log_profile_sync_cycle(
            done_count=done_count,
            failed_count=failed_count,
            rescheduled_count=rescheduled_count,
        )
        return done_count, failed_count, rescheduled_count

    async def _wait_for_next_tick(self) -> None:
        """Ждет следующий тик или сигнал остановки."""

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)

