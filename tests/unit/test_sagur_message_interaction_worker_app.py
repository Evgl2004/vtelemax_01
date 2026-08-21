"""Тесты точки запуска работника доставки нажатий SAGUR."""

from __future__ import annotations

import asyncio
import runpy
from dataclasses import dataclass
from typing import Any

import pytest

import vtelemax.apps.sagur_message_interaction_worker_app as worker_app
from vtelemax.settings import AppSettings


def _settings(**overrides: Any) -> AppSettings:
    values: dict[str, Any] = {
        "SAGUR_MESSAGE_INTERACTION_SYNC_ENABLED": True,
        "SAGUR_MESSAGE_INTERACTION_SYNC_BASE_URL": "https://example.test",
        "SAGUR_MESSAGE_INTERACTION_SYNC_ENDPOINT": "/events",
        "SAGUR_MESSAGE_INTERACTION_SYNC_HMAC_SECRET": "secret",
        "SAGUR_MESSAGE_INTERACTION_SYNC_SCHEDULE_MINUTES": 2,
    }
    values.update(overrides)
    return AppSettings(**values)


def test_build_postgres_session_factory_uses_project_engine_builders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    engine = object()
    factory = object()
    calls: dict[str, object] = {}

    def _build_engine(dsn: str, *, echo: bool) -> object:
        calls.update(dsn=dsn, echo=echo)
        return engine

    def _build_factory(value: object) -> object:
        assert value is engine
        return factory

    monkeypatch.setattr(worker_app, "build_engine", _build_engine)
    monkeypatch.setattr(worker_app, "build_session_factory", _build_factory)

    result = worker_app.build_postgres_session_factory(settings)

    assert result is factory
    assert calls == {"dsn": settings.postgres_sqlalchemy_dsn, "echo": settings.postgres_echo}


@pytest.mark.parametrize(
    ("settings", "expected_component"),
    [
        (
            _settings(SAGUR_MESSAGE_INTERACTION_SYNC_ENABLED=False),
            "sagur_message_interaction_worker_app",
        ),
        (
            _settings(
                SAGUR_MESSAGE_INTERACTION_SYNC_HMAC_SECRET=" ",
                SAGUR_INTEGRATION_HMAC_SECRET=" ",
            ),
            "sagur_message_interaction_worker_app",
        ),
    ],
)
def test_worker_stays_in_safe_wait_when_disabled_or_secret_missing(
    settings: AppSettings,
    expected_component: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waited: list[str] = []

    async def _wait(component: str) -> None:
        waited.append(component)

    monkeypatch.setattr(worker_app, "configure_logging", lambda **kwargs: None)
    monkeypatch.setattr(worker_app, "_wait_for_shutdown_signal", _wait)

    asyncio.run(worker_app.run_sagur_message_interaction_worker(settings))

    assert waited == [expected_component]


@dataclass(slots=True)
class _FakeWorker:
    processor: object
    interval_seconds: float
    started: bool = False
    stopped: bool = False

    async def run_forever(self) -> None:
        self.started = True
        await asyncio.Event().wait()

    async def shutdown(self) -> None:
        self.stopped = True


@dataclass(slots=True)
class _FakeHttpClient:
    parameters: dict[str, object]
    closed: bool = False

    async def close(self) -> None:
        self.closed = True


def test_enabled_worker_builds_dependencies_and_shuts_down_on_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    captured: dict[str, object] = {}
    fake_worker: _FakeWorker | None = None
    fake_http_client: _FakeHttpClient | None = None

    def _http_client(**kwargs: object) -> _FakeHttpClient:
        nonlocal fake_http_client
        captured["http"] = kwargs
        fake_http_client = _FakeHttpClient(kwargs)
        return fake_http_client

    def _processor(**kwargs: object) -> object:
        captured["processor"] = kwargs
        return object()

    def _worker(**kwargs: object) -> _FakeWorker:
        nonlocal fake_worker
        fake_worker = _FakeWorker(**kwargs)
        return fake_worker

    monkeypatch.setattr(worker_app, "configure_logging", lambda **kwargs: None)
    monkeypatch.setattr(worker_app, "build_postgres_session_factory", lambda settings: "factory")
    monkeypatch.setattr(worker_app, "SagurMessageInteractionHttpClient", _http_client)
    monkeypatch.setattr(worker_app, "SagurMessageInteractionDeliveryProcessor", _processor)
    monkeypatch.setattr(worker_app, "PeriodicSagurMessageInteractionWorker", _worker)

    async def _run_and_cancel() -> None:
        task = asyncio.create_task(worker_app.run_sagur_message_interaction_worker(settings))
        for _ in range(5):
            await asyncio.sleep(0)
            if fake_worker is not None and fake_worker.started:
                break
        assert fake_worker is not None and fake_worker.started
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_run_and_cancel())

    assert fake_worker is not None and fake_worker.stopped
    assert fake_http_client is not None and fake_http_client.closed
    assert captured["http"] == {
        "base_url": "https://example.test",
        "endpoint_path": "/events",
        "hmac_secret": "secret",
        "timeout_seconds": 20.0,
        "require_https": True,
    }
    processor = captured["processor"]
    assert isinstance(processor, dict)
    assert processor["session_factory"] == "factory"
    assert processor["batch_size"] == 100
    assert fake_worker.interval_seconds == 120


def test_wait_for_shutdown_signal_can_be_cancelled() -> None:
    async def _run() -> None:
        task = asyncio.create_task(worker_app._wait_for_shutdown_signal("test_component"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_run())


def test_shutdown_signal_handlers_set_event_once_and_tolerate_unsupported_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SignalLoop:
        def __init__(self, *, supported: bool) -> None:
            self.supported = supported
            self.calls = 0

        def add_signal_handler(self, _signal: object, callback: object, source: str) -> None:
            self.calls += 1
            if not self.supported:
                raise NotImplementedError
            callback(source)  # type: ignore[operator]

    supported_loop = _SignalLoop(supported=True)
    monkeypatch.setattr(worker_app.asyncio, "get_running_loop", lambda: supported_loop)
    stop_event = asyncio.Event()

    worker_app._install_shutdown_signal_handlers(stop_event, component="test_component")

    assert stop_event.is_set()
    assert supported_loop.calls == 2

    unsupported_loop = _SignalLoop(supported=False)
    monkeypatch.setattr(worker_app.asyncio, "get_running_loop", lambda: unsupported_loop)
    second_event = asyncio.Event()
    worker_app._install_shutdown_signal_handlers(second_event, component="test_component")
    assert not second_event.is_set()


def test_main_delegates_coroutine_to_asyncio_run(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[object] = []

    def _run(coroutine: object) -> None:
        called.append(coroutine)
        coroutine.close()  # type: ignore[attr-defined]

    monkeypatch.setattr(worker_app.asyncio, "run", _run)

    worker_app.main()

    assert len(called) == 1


def test_module_main_guard_calls_main(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[object] = []

    def _run(coroutine: object) -> None:
        called.append(coroutine)
        coroutine.close()  # type: ignore[attr-defined]

    monkeypatch.setattr(asyncio, "run", _run)

    runpy.run_path(worker_app.__file__, run_name="__main__")

    assert len(called) == 1
