"""Unit-тесты entrypoint отдельного delivery worker модерации."""

from __future__ import annotations

import pytest

from vtelemax.apps import moderation_delivery_worker_app as worker_app
from vtelemax.settings import AppSettings


async def _dummy_sender(*args, **kwargs) -> None:  # noqa: ANN002, ANN003, ARG001
    """Тестовый sender без сетевых вызовов."""


def test_parse_args_reads_platform() -> None:
    """Проверяет, что CLI-контракт корректно парсит `--platform`."""

    args = worker_app.parse_args(["--platform", "telegram"])
    assert args.platform == "telegram"


def test_parse_args_rejects_unknown_platform() -> None:
    """Проверяет, что CLI отклоняет неподдерживаемую платформу."""

    with pytest.raises(SystemExit):
        worker_app.parse_args(["--platform", "unknown"])


def test_build_runtime_for_platform_dispatches_to_specific_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверяет маршрутизацию runtime по платформе."""

    tg_runtime = worker_app.WorkerRuntime(sender=_dummy_sender)
    vk_runtime = worker_app.WorkerRuntime(sender=_dummy_sender)
    max_runtime = worker_app.WorkerRuntime(sender=_dummy_sender)

    monkeypatch.setattr(worker_app, "_build_telegram_runtime", lambda settings: tg_runtime)
    monkeypatch.setattr(worker_app, "_build_vk_runtime", lambda settings: vk_runtime)
    monkeypatch.setattr(worker_app, "_build_max_runtime", lambda settings: max_runtime)

    settings = AppSettings()
    assert worker_app.build_runtime_for_platform(settings, platform="telegram") is tg_runtime
    assert worker_app.build_runtime_for_platform(settings, platform="vk") is vk_runtime
    assert worker_app.build_runtime_for_platform(settings, platform="max") is max_runtime


def test_build_runtime_for_platform_rejects_unknown_platform() -> None:
    """Проверяет защиту от неподдерживаемого значения платформы."""

    with pytest.raises(ValueError):
        worker_app.build_runtime_for_platform(AppSettings(), platform="other")  # type: ignore[arg-type]
