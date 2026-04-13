"""Unit tests for periodic profile sync worker."""

from __future__ import annotations

import asyncio

import pytest

from vtelemax.adapters.periodic_profile_sync_worker import PeriodicProfileSyncWorker


class _ProcessorStub:
    def __init__(self, *, done: int = 0, failed: int = 0, rescheduled: int = 0) -> None:
        self.done = done
        self.failed = failed
        self.rescheduled = rescheduled
        self.calls = 0
        self.last_limit: int | None = None

    async def process_once(self, *, limit: int) -> tuple[int, int, int]:
        self.calls += 1
        self.last_limit = limit
        return self.done, self.failed, self.rescheduled


def test_profile_sync_worker_process_once_returns_processor_result() -> None:
    processor = _ProcessorStub(done=3, failed=1, rescheduled=2)
    worker = PeriodicProfileSyncWorker(
        processor=processor,  # type: ignore[arg-type]
        interval_seconds=1.0,
        batch_limit=25,
    )

    done_count, failed_count, rescheduled_count = asyncio.run(worker.process_once())

    assert done_count == 3
    assert failed_count == 1
    assert rescheduled_count == 2
    assert processor.calls == 1
    assert processor.last_limit == 25


def test_profile_sync_worker_skips_pass_when_shared_lock_is_busy() -> None:
    async def scenario() -> tuple[tuple[int, int, int], int]:
        lock = asyncio.Lock()
        await lock.acquire()
        processor = _ProcessorStub(done=1)
        worker = PeriodicProfileSyncWorker(
            processor=processor,  # type: ignore[arg-type]
            interval_seconds=1.0,
            batch_limit=10,
            lock=lock,
        )
        try:
            result = await worker.process_once()
        finally:
            lock.release()
        return result, processor.calls

    (done_count, failed_count, rescheduled_count), calls = asyncio.run(scenario())
    assert done_count == 0
    assert failed_count == 0
    assert rescheduled_count == 0
    assert calls == 0


def test_profile_sync_worker_process_once_handles_processor_exception() -> None:
    class _FailingProcessor:
        async def process_once(self, *, limit: int) -> tuple[int, int, int]:  # noqa: ARG002
            raise RuntimeError("processor failed")

    worker = PeriodicProfileSyncWorker(
        processor=_FailingProcessor(),  # type: ignore[arg-type]
        interval_seconds=1.0,
        batch_limit=10,
    )

    done_count, failed_count, rescheduled_count = asyncio.run(worker.process_once())

    assert done_count == 0
    assert failed_count == 0
    assert rescheduled_count == 0


def test_profile_sync_worker_run_forever_stops_after_shutdown_signal() -> None:
    class _SignalProcessor(_ProcessorStub):
        def __init__(self) -> None:
            super().__init__(done=0, failed=0, rescheduled=0)
            self.called_event = asyncio.Event()

        async def process_once(self, *, limit: int) -> tuple[int, int, int]:
            result = await super().process_once(limit=limit)
            self.called_event.set()
            return result

    async def scenario() -> int:
        processor = _SignalProcessor()
        worker = PeriodicProfileSyncWorker(
            processor=processor,  # type: ignore[arg-type]
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


def test_profile_sync_worker_rejects_non_positive_interval() -> None:
    processor = _ProcessorStub()

    with pytest.raises(ValueError):
        PeriodicProfileSyncWorker(
            processor=processor,  # type: ignore[arg-type]
            interval_seconds=0,
            batch_limit=10,
        )


def test_profile_sync_worker_rejects_non_positive_batch_limit() -> None:
    processor = _ProcessorStub()

    with pytest.raises(ValueError):
        PeriodicProfileSyncWorker(
            processor=processor,  # type: ignore[arg-type]
            interval_seconds=1,
            batch_limit=0,
        )

