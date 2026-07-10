"""Централизованные настройки проекта vtelemax.

Модуль отвечает за:

1. Чтение переменных окружения из `.env` и системного окружения.
2. Валидацию и типизацию параметров запуска.
3. Формирование DSN/URL для подключения к PostgreSQL.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Основная модель настроек приложения.

    Значения читаются из:

    1. переменных окружения процесса;
    2. локального файла `.env` (если существует).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    env: str = Field(default="development", alias="ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5433, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="postgres", alias="POSTGRES_DB")
    postgres_user: str = Field(default="postgres", alias="POSTGRES_USER")
    postgres_password: str = Field(default="1234", alias="POSTGRES_PASSWORD")
    postgres_echo: bool = Field(default=False, alias="POSTGRES_ECHO")
    postgres_auto_create_schema: bool = Field(default=False, alias="POSTGRES_AUTO_CREATE_SCHEMA")

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_bot_username: str = Field(default="", alias="TELEGRAM_BOT_USERNAME")
    vk_bot_token: str = Field(default="", alias="VK_BOT_TOKEN")
    vk_group_id: int = Field(default=0, alias="VK_GROUP_ID")
    vk_phone_verification_miniapp_enabled: bool = Field(
        default=False,
        alias="VK_PHONE_VERIFICATION_MINIAPP_ENABLED",
    )
    vk_phone_verification_miniapp_url: str = Field(
        default="",
        alias="VK_PHONE_VERIFICATION_MINIAPP_URL",
    )
    vk_phone_verification_status_url: str = Field(
        default="",
        alias="VK_PHONE_VERIFICATION_STATUS_URL",
    )
    vk_phone_verification_api_token: str = Field(
        default="",
        alias="VK_PHONE_VERIFICATION_API_TOKEN",
    )
    vk_phone_verification_timeout_seconds: float = Field(
        default=5.0,
        alias="VK_PHONE_VERIFICATION_TIMEOUT_SECONDS",
        gt=0,
    )
    vk_phone_verification_link_secret: str = Field(
        default="",
        alias="VK_PHONE_VERIFICATION_LINK_SECRET",
    )
    vk_phone_verification_link_ttl_seconds: int = Field(
        default=900,
        alias="VK_PHONE_VERIFICATION_LINK_TTL_SECONDS",
        gt=30,
    )
    vk_phone_verification_service_enabled: bool = Field(
        default=False,
        alias="VK_PHONE_VERIFICATION_SERVICE_ENABLED",
    )
    vk_phone_verification_service_host: str = Field(
        default="0.0.0.0",
        alias="VK_PHONE_VERIFICATION_SERVICE_HOST",
    )
    vk_phone_verification_service_port: int = Field(
        default=8085,
        alias="VK_PHONE_VERIFICATION_SERVICE_PORT",
        gt=0,
    )
    vk_phone_verification_session_ttl_seconds: int = Field(
        default=900,
        alias="VK_PHONE_VERIFICATION_SESSION_TTL_SECONDS",
        gt=30,
    )
    sagur_integration_api_enabled: bool = Field(
        default=False,
        alias="SAGUR_INTEGRATION_API_ENABLED",
    )
    sagur_integration_service_host: str = Field(
        default="0.0.0.0",
        alias="SAGUR_INTEGRATION_SERVICE_HOST",
    )
    sagur_integration_service_port: int = Field(
        default=8086,
        alias="SAGUR_INTEGRATION_SERVICE_PORT",
        gt=0,
    )
    sagur_integration_default_limit: int = Field(
        default=1000,
        alias="SAGUR_INTEGRATION_DEFAULT_LIMIT",
        gt=0,
    )
    sagur_integration_max_limit: int = Field(
        default=5000,
        alias="SAGUR_INTEGRATION_MAX_LIMIT",
        gt=0,
    )
    sagur_integration_rate_limit_rpm: int = Field(
        default=60,
        alias="SAGUR_INTEGRATION_RATE_LIMIT_RPM",
        gt=0,
    )
    sagur_integration_hmac_secret: str = Field(
        default="",
        alias="SAGUR_INTEGRATION_HMAC_SECRET",
    )
    sagur_integration_hmac_max_skew_seconds: int = Field(
        default=60,
        alias="SAGUR_INTEGRATION_HMAC_MAX_SKEW_SECONDS",
        gt=0,
    )
    sagur_integration_ip_allowlist: str = Field(
        default="",
        alias="SAGUR_INTEGRATION_IP_ALLOWLIST",
    )
    sagur_include_vk_pending_verification: bool = Field(
        default=False,
        alias="SAGUR_INCLUDE_VK_PENDING_VERIFICATION",
    )
    sagur_registration_events_enabled: bool = Field(
        default=False,
        alias="SAGUR_REGISTRATION_EVENTS_ENABLED",
    )
    sagur_registration_events_endpoint: str = Field(
        default="https://sagur.24vds.ru/internal/integration/v1/vtelemax/registration-events",
        alias="SAGUR_REGISTRATION_EVENTS_ENDPOINT",
    )
    vtelemax_registration_callback_hmac_secret: str = Field(
        default="",
        alias="VTELEMAX_REGISTRATION_CALLBACK_HMAC_SECRET",
    )
    sagur_registration_events_timeout_seconds: float = Field(
        default=5.0,
        alias="SAGUR_REGISTRATION_EVENTS_TIMEOUT_SECONDS",
        gt=0,
    )
    sagur_registration_events_interval_seconds: float = Field(
        default=60.0,
        alias="SAGUR_REGISTRATION_EVENTS_INTERVAL_SECONDS",
        gt=0,
    )
    sagur_registration_events_batch_limit: int = Field(
        default=20,
        alias="SAGUR_REGISTRATION_EVENTS_BATCH_LIMIT",
        gt=0,
    )
    sagur_registration_events_max_attempts: int = Field(
        default=8,
        alias="SAGUR_REGISTRATION_EVENTS_MAX_ATTEMPTS",
        gt=0,
    )
    sagur_registration_events_recovery_enabled: bool = Field(
        default=True,
        alias="SAGUR_REGISTRATION_EVENTS_RECOVERY_ENABLED",
    )
    sagur_registration_events_recovery_interval_seconds: float = Field(
        default=300.0,
        alias="SAGUR_REGISTRATION_EVENTS_RECOVERY_INTERVAL_SECONDS",
        gt=0,
    )
    sagur_registration_events_recovery_batch_limit: int = Field(
        default=10,
        alias="SAGUR_REGISTRATION_EVENTS_RECOVERY_BATCH_LIMIT",
        gt=0,
    )
    sagur_registration_events_recovery_max_attempts: int = Field(
        default=3,
        alias="SAGUR_REGISTRATION_EVENTS_RECOVERY_MAX_ATTEMPTS",
        gt=0,
    )
    sagur_registration_events_recovery_first_delay_seconds: int = Field(
        default=120,
        alias="SAGUR_REGISTRATION_EVENTS_RECOVERY_FIRST_DELAY_SECONDS",
        gt=0,
    )
    sagur_registration_events_lock_timeout_seconds: int = Field(
        default=300,
        alias="SAGUR_REGISTRATION_EVENTS_LOCK_TIMEOUT_SECONDS",
        gt=0,
    )
    max_bot_token: str = Field(default="", alias="MAX_BOT_TOKEN")
    max_bot_username: str = Field(default="", alias="MAX_BOT_USERNAME")
    max_contact_strict_hash_enabled: bool = Field(
        default=False,
        alias="MAX_CONTACT_STRICT_HASH_ENABLED",
    )
    max_contact_hash_shadow_mode_enabled: bool = Field(
        default=True,
        alias="MAX_CONTACT_HASH_SHADOW_MODE_ENABLED",
    )
    vk_pending_verification_delivery_enabled: bool = Field(
        default=False,
        alias="VK_PENDING_VERIFICATION_DELIVERY_ENABLED",
    )
    moderation_delivery_interval_seconds: float = Field(
        default=15.0,
        alias="MODERATION_DELIVERY_INTERVAL_SECONDS",
        gt=0,
    )
    moderation_delivery_batch_limit: int = Field(
        default=20,
        alias="MODERATION_DELIVERY_BATCH_LIMIT",
        gt=0,
    )
    profile_sync_enabled: bool = Field(default=True, alias="PROFILE_SYNC_ENABLED")
    profile_sync_interval_seconds: float = Field(
        default=15.0,
        alias="PROFILE_SYNC_INTERVAL_SECONDS",
        gt=0,
    )
    profile_sync_batch_limit: int = Field(
        default=50,
        alias="PROFILE_SYNC_BATCH_LIMIT",
        gt=0,
    )
    profile_sync_max_attempts: int = Field(
        default=5,
        alias="PROFILE_SYNC_MAX_ATTEMPTS",
        gt=0,
    )
    iiko_api_key: str = Field(default="", alias="IIKO_API_KEY")
    iiko_org_id: str = Field(default="", alias="IIKO_ORG_ID")
    iiko_base_url: str = Field(default="https://api-ru.iiko.services/api/1", alias="IIKO_BASE_URL")

    @property
    def postgres_sqlalchemy_dsn(self) -> str:
        """Возвращает SQLAlchemy DSN для PostgreSQL (driver `psycopg`)."""

        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def validate_telegram_ready(self) -> None:
        """Проверяет, что настройки достаточны для запуска Telegram-бота."""

        if not self.telegram_bot_token.strip():
            raise ValueError(
                "Не задан TELEGRAM_BOT_TOKEN. Укажите токен бота в .env или переменной окружения."
            )

    def validate_vk_ready(self) -> None:
        """Проверяет, что настройки достаточны для запуска VK-бота."""

        if not self.vk_bot_token.strip():
            raise ValueError("Не задан VK_BOT_TOKEN. Укажите токен в .env или переменной окружения.")

    def validate_max_ready(self) -> None:
        """Проверяет, что настройки достаточны для запуска MAX-бота."""

        if not self.max_bot_token.strip():
            raise ValueError("Не задан MAX_BOT_TOKEN. Укажите токен в .env или переменной окружения.")

    @property
    def is_iiko_configured(self) -> bool:
        """Показывает, включена ли интеграция с iiko для разделов лояльности."""

        return bool(self.iiko_api_key.strip() and self.iiko_org_id.strip())

    @property
    def sagur_registration_events_hmac_secret(self) -> str:
        """Возвращает HMAC-секрет исходящего события регистрации SAGUR."""

        dedicated_secret = self.vtelemax_registration_callback_hmac_secret.strip()
        if dedicated_secret:
            return dedicated_secret
        return self.sagur_integration_hmac_secret.strip()
