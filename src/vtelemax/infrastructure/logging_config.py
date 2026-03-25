"""Централизованная конфигурация логирования vtelemax.

Модуль предоставляет:

1. валидацию уровня логирования из окружения;
2. единый формат лог-строк для всех приложений;
3. базовые поля контекста (`service`, `platform`, `component`, `stage`, `user_id`).
"""

from __future__ import annotations

import sys

from loguru import logger

_ALLOWED_LOG_LEVELS = {
    "TRACE",
    "DEBUG",
    "INFO",
    "SUCCESS",
    "WARNING",
    "ERROR",
    "CRITICAL",
}


def normalize_log_level(raw_level: str) -> str:
    """Нормализует и валидирует уровень логирования.

    Args:
        raw_level: Строковое значение уровня (`INFO`, `DEBUG` и т.д.).

    Returns:
        Валидное значение уровня в верхнем регистре.

    Raises:
        ValueError: Если уровень не входит в поддерживаемый список.
    """

    normalized = (raw_level or "").strip().upper()
    if normalized not in _ALLOWED_LOG_LEVELS:
        allowed = ", ".join(sorted(_ALLOWED_LOG_LEVELS))
        raise ValueError(
            "Недопустимый LOG_LEVEL="
            f"{raw_level!r}. Поддерживаемые уровни: {allowed}."
        )
    return normalized


def configure_logging(*, service_name: str, log_level: str) -> str:
    """Инициализирует loguru для текущего процесса.

    Args:
        service_name: Название процесса/сервиса (например, `telegram-bot`).
        log_level: Уровень логирования из настроек.

    Returns:
        Нормализованный уровень логирования, который применен к sink.
    """

    normalized_level = normalize_log_level(log_level)
    logger.remove()
    logger.configure(
        extra={
            "service": service_name,
            "platform": "-",
            "component": "-",
            "stage": "-",
            "user_id": "-",
        }
    )
    logger.add(
        sys.stdout,
        level=normalized_level,
        backtrace=False,
        diagnose=False,
        enqueue=False,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | "
            "{extra[service]} | {extra[platform]} | {extra[component]} | "
            "stage={extra[stage]} | user={extra[user_id]} | {message}"
        ),
    )
    logger.bind(component="logging", stage="init").info(
        "Логирование инициализировано. Уровень: {level}.",
        level=normalized_level,
    )
    return normalized_level
