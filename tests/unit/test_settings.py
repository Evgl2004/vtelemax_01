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
