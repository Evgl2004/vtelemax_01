"""Тесты модели настроек приложения."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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


def test_settings_reads_moderation_delivery_worker_values() -> None:
    """Проверяет чтение настроек periodic worker из env-параметров."""

    settings = AppSettings(
        MODERATION_DELIVERY_INTERVAL_SECONDS=7.5,
        MODERATION_DELIVERY_BATCH_LIMIT=42,
    )

    assert settings.moderation_delivery_interval_seconds == 7.5
    assert settings.moderation_delivery_batch_limit == 42


def test_settings_rejects_non_positive_moderation_interval() -> None:
    """Проверяет валидацию интервала periodic worker."""

    with pytest.raises(ValidationError):
        AppSettings(MODERATION_DELIVERY_INTERVAL_SECONDS=0)


def test_settings_rejects_non_positive_moderation_batch_limit() -> None:
    """Проверяет валидацию batch limit periodic worker."""

    with pytest.raises(ValidationError):
        AppSettings(MODERATION_DELIVERY_BATCH_LIMIT=0)


def test_settings_reads_profile_sync_worker_values() -> None:
    """Checks reading profile sync worker settings from env."""

    settings = AppSettings(
        PROFILE_SYNC_ENABLED=True,
        PROFILE_SYNC_INTERVAL_SECONDS=12.5,
        PROFILE_SYNC_BATCH_LIMIT=30,
        PROFILE_SYNC_MAX_ATTEMPTS=7,
    )

    assert settings.profile_sync_enabled is True
    assert settings.profile_sync_interval_seconds == 12.5
    assert settings.profile_sync_batch_limit == 30
    assert settings.profile_sync_max_attempts == 7


def test_settings_rejects_non_positive_profile_sync_interval() -> None:
    """Checks validation of profile sync interval."""

    with pytest.raises(ValidationError):
        AppSettings(PROFILE_SYNC_INTERVAL_SECONDS=0)


def test_settings_rejects_non_positive_profile_sync_batch_limit_and_attempts() -> None:
    """Checks validation of profile sync batch limit and max attempts."""

    with pytest.raises(ValidationError):
        AppSettings(PROFILE_SYNC_BATCH_LIMIT=0)

    with pytest.raises(ValidationError):
        AppSettings(PROFILE_SYNC_MAX_ATTEMPTS=0)
