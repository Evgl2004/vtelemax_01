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
