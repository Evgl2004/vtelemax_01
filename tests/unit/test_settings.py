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


def test_settings_reads_telegram_proxy_url() -> None:
    """Проверяет чтение адреса Telegram-прокси из переменной окружения."""

    settings = AppSettings(TELEGRAM_PROXY_URL="http://xray-telegram:10809")

    assert settings.telegram_proxy_url == "http://xray-telegram:10809"


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


def test_settings_reads_sagur_registration_events_values() -> None:
    """Проверяет настройки исходящих событий регистрации SAGUR."""

    settings = AppSettings(
        SAGUR_REGISTRATION_EVENTS_ENABLED=True,
        SAGUR_REGISTRATION_EVENTS_ENDPOINT="https://example.test/registration-events",
        SAGUR_INTEGRATION_HMAC_SECRET="shared-secret",
        VTELEMAX_REGISTRATION_CALLBACK_HMAC_SECRET="registration-secret",
        SAGUR_REGISTRATION_EVENTS_TIMEOUT_SECONDS=3.5,
        SAGUR_REGISTRATION_EVENTS_INTERVAL_SECONDS=90,
        SAGUR_REGISTRATION_EVENTS_BATCH_LIMIT=7,
        SAGUR_REGISTRATION_EVENTS_MAX_ATTEMPTS=4,
        SAGUR_REGISTRATION_EVENTS_RECOVERY_ENABLED=True,
        SAGUR_REGISTRATION_EVENTS_RECOVERY_INTERVAL_SECONDS=600,
        SAGUR_REGISTRATION_EVENTS_RECOVERY_BATCH_LIMIT=3,
        SAGUR_REGISTRATION_EVENTS_RECOVERY_MAX_ATTEMPTS=2,
        SAGUR_REGISTRATION_EVENTS_RECOVERY_FIRST_DELAY_SECONDS=45,
        SAGUR_REGISTRATION_EVENTS_LOCK_TIMEOUT_SECONDS=180,
    )

    assert settings.sagur_registration_events_enabled is True
    assert settings.sagur_registration_events_endpoint == "https://example.test/registration-events"
    assert settings.sagur_registration_events_hmac_secret == "registration-secret"
    assert settings.sagur_registration_events_timeout_seconds == 3.5
    assert settings.sagur_registration_events_interval_seconds == 90
    assert settings.sagur_registration_events_batch_limit == 7
    assert settings.sagur_registration_events_max_attempts == 4
    assert settings.sagur_registration_events_recovery_enabled is True
    assert settings.sagur_registration_events_recovery_interval_seconds == 600
    assert settings.sagur_registration_events_recovery_batch_limit == 3
    assert settings.sagur_registration_events_recovery_max_attempts == 2
    assert settings.sagur_registration_events_recovery_first_delay_seconds == 45
    assert settings.sagur_registration_events_lock_timeout_seconds == 180


def test_settings_uses_sagur_integration_secret_for_registration_events_when_dedicated_secret_empty() -> None:
    """Проверяет общий HMAC-секрет SAGUR для welcome-callback при пустом отдельном секрете."""

    settings = AppSettings(
        SAGUR_INTEGRATION_HMAC_SECRET=" shared-secret ",
        VTELEMAX_REGISTRATION_CALLBACK_HMAC_SECRET=" ",
    )

    assert settings.sagur_registration_events_hmac_secret == "shared-secret"


def test_settings_returns_empty_sagur_registration_secret_when_not_configured() -> None:
    """Проверяет пустой HMAC-секрет регистрации, когда оба источника не настроены."""

    settings = AppSettings(
        SAGUR_INTEGRATION_HMAC_SECRET=" ",
        VTELEMAX_REGISTRATION_CALLBACK_HMAC_SECRET=" ",
    )

    assert settings.sagur_registration_events_hmac_secret == ""


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


def test_settings_rejects_non_positive_sagur_registration_values() -> None:
    """Проверяет валидацию лимитов и интервалов SAGUR registration worker."""

    with pytest.raises(ValidationError):
        AppSettings(SAGUR_REGISTRATION_EVENTS_INTERVAL_SECONDS=0)

    with pytest.raises(ValidationError):
        AppSettings(SAGUR_REGISTRATION_EVENTS_BATCH_LIMIT=0)

    with pytest.raises(ValidationError):
        AppSettings(SAGUR_REGISTRATION_EVENTS_RECOVERY_MAX_ATTEMPTS=0)


def test_settings_reads_max_contact_hash_flags() -> None:
    """Проверяет чтение флагов strict/shadow верификации MAX-контакта."""

    settings = AppSettings(
        MAX_CONTACT_STRICT_HASH_ENABLED=True,
        MAX_CONTACT_HASH_SHADOW_MODE_ENABLED=False,
    )

    assert settings.max_contact_strict_hash_enabled is True
    assert settings.max_contact_hash_shadow_mode_enabled is False
