"""Тесты модели настроек приложения."""

from __future__ import annotations

import pytest

from vtelemax.settings import AppSettings


def test_settings_builds_postgres_dsn() -> None:
    """Проверяет корректную сборку SQLAlchemy DSN для PostgreSQL."""

    settings = AppSettings(
        POSTGRES_HOST="localhost",
        POSTGRES_PORT=5433,
        POSTGRES_DB="postgres",
        POSTGRES_USER="postgres",
        POSTGRES_PASSWORD="1234",
        TELEGRAM_BOT_TOKEN="dummy-token",
    )

    assert settings.postgres_sqlalchemy_dsn == "postgresql+psycopg://postgres:1234@localhost:5433/postgres"


def test_settings_validate_telegram_ready_raises_for_empty_token() -> None:
    """Проверяет обязательность токена Telegram для запуска бота."""

    settings = AppSettings(TELEGRAM_BOT_TOKEN="   ")

    with pytest.raises(ValueError):
        settings.validate_telegram_ready()


def test_settings_validate_vk_ready_raises_for_empty_token() -> None:
    """Проверяет обязательность токена VK для запуска бота."""

    settings = AppSettings(VK_BOT_TOKEN="   ")

    with pytest.raises(ValueError):
        settings.validate_vk_ready()


def test_settings_validate_max_ready_raises_for_empty_token() -> None:
    """Проверяет обязательность токена MAX для запуска бота."""

    settings = AppSettings(MAX_BOT_TOKEN="   ")

    with pytest.raises(ValueError):
        settings.validate_max_ready()


def test_settings_detects_iiko_configuration_enabled() -> None:
    """Проверяет, что флаг интеграции iiko активируется при заполненных обязательных полях."""

    settings = AppSettings(IIKO_API_KEY="test-key", IIKO_ORG_ID="org-1")

    assert settings.is_iiko_configured is True


def test_settings_detects_iiko_configuration_disabled() -> None:
    """Проверяет, что флаг iiko выключен при отсутствии обязательных полей."""

    settings = AppSettings(IIKO_API_KEY=" ", IIKO_ORG_ID="")

    assert settings.is_iiko_configured is False
