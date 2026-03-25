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
    max_bot_token: str = Field(default="", alias="MAX_BOT_TOKEN")
    max_bot_username: str = Field(default="", alias="MAX_BOT_USERNAME")
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
