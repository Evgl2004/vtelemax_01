"""Unit-тесты periodic worker доставки pending-сообщений модерации."""

from __future__ import annotations

import asyncio

import pytest

from vtelemax.adapters.periodic_moderation_delivery_worker import PeriodicPendingDeliveryWorker
from vtelemax.core import PendingModeratorDelivery


class _StubProcessor:
    """Тестовый процессор, сохраняющий параметры последнего вызова."""

    def __init__(self, *, sent: int = 0, failed: int = 0) -> None:
        self.sent = sent
        self.failed = failed
        self.calls = 0
        self.last_limit: int | None = None

    async def process_once(self, *, sender, limit: int) -> tuple[int, int]:  # noqa: ANN001
        self.calls += 1
        self.last_limit = limit
        return self.sent, self.failed


async def _noop_sender(delivery: PendingModeratorDelivery, text: str) -> None:  # noqa: ARG001
    """Тестовый sender без сетевых вызовов."""


def test_worker_process_once_returns_processor_result() -> None:
    """Возвращает счётчики sent/failed из `processor.process_once`."""

    processor = _StubProcessor(sent=3, failed=1)
    worker = PeriodicPendingDeliveryWorker(
        target_platform="telegram",
        processor=processor,  # type: ignore[arg-type]
        sender=_noop_sender,
        interval_seconds=1.0,
        batch_limit=25,
    )

    sent_count, failed_count = asyncio.run(worker.process_once())

    assert sent_count == 3
    assert failed_count == 1
    assert processor.calls == 1
    assert processor.last_limit == 25


def test_worker_skips_pass_when_shared_lock_is_busy() -> None:
    """Пропускает проход, если shared lock уже удерживается другим процессом."""

    async def scenario() -> tuple[tuple[int, int], int]:
        lock = asyncio.Lock()
        await lock.acquire()
        processor = _StubProcessor(sent=1, failed=0)
        worker = PeriodicPendingDeliveryWorker(
            target_platform="vk",
            processor=processor,  # type: ignore[arg-type]
            sender=_noop_sender,
            interval_seconds=1.0,
            batch_limit=10,
            lock=lock,
        )
        try:
            result = await worker.process_once()
        finally:
            lock.release()
        return result, processor.calls

    (sent_count, failed_count), calls = asyncio.run(scenario())
    assert sent_count == 0
    assert failed_count == 0
    assert calls == 0


def test_worker_process_once_handles_processor_exception() -> None:
    """Не пробрасывает исключение процессора и возвращает `(0, 0)`."""

    class _FailingProcessor:
        async def process_once(self, *, sender, limit: int) -> tuple[int, int]:  # noqa: ANN001, ARG002
            raise RuntimeError("processor failed")

    worker = PeriodicPendingDeliveryWorker(
        target_platform="max",
        processor=_FailingProcessor(),  # type: ignore[arg-type]
        sender=_noop_sender,
        interval_seconds=1.0,
        batch_limit=10,
    )

    sent_count, failed_count = asyncio.run(worker.process_once())

    assert sent_count == 0
    assert failed_count == 0


def test_worker_run_forever_stops_after_shutdown_signal() -> None:
    """Корректно завершает цикл `run_forever` после `shutdown()`."""

    class _SignalProcessor(_StubProcessor):
        def __init__(self) -> None:
            super().__init__(sent=0, failed=0)
            self.called_event = asyncio.Event()

        async def process_once(self, *, sender, limit: int) -> tuple[int, int]:  # noqa: ANN001
            result = await super().process_once(sender=sender, limit=limit)
            self.called_event.set()
            return result

    async def scenario() -> int:
        processor = _SignalProcessor()
        worker = PeriodicPendingDeliveryWorker(
            target_platform="telegram",
            processor=processor,  # type: ignore[arg-type]
            sender=_noop_sender,
            interval_seconds=60.0,
            batch_limit=5,
        )
        task = asyncio.create_task(worker.run_forever())
        await asyncio.wait_for(processor.called_event.wait(), timeout=1.0)
        await worker.shutdown()
        await asyncio.wait_for(task, timeout=1.0)
        return processor.calls

    calls = asyncio.run(scenario())
    assert calls >= 1


def test_worker_rejects_non_positive_interval() -> None:
    """Проверяет валидацию интервала periodic worker."""

    processor = _StubProcessor()

    with pytest.raises(ValueError):
        PeriodicPendingDeliveryWorker(
            target_platform="telegram",
            processor=processor,  # type: ignore[arg-type]
            sender=_noop_sender,
            interval_seconds=0,
            batch_limit=10,
        )


def test_worker_rejects_non_positive_batch_limit() -> None:
    """Проверяет валидацию batch limit periodic worker."""

    processor = _StubProcessor()

    with pytest.raises(ValueError):
        PeriodicPendingDeliveryWorker(
            target_platform="telegram",
            processor=processor,  # type: ignore[arg-type]
            sender=_noop_sender,
            interval_seconds=1,
            batch_limit=0,
        )
