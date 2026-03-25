"""Тесты конфигурации логирования."""

from __future__ import annotations

import pytest

from vtelemax.infrastructure.logging_config import configure_logging, normalize_log_level


def test_normalize_log_level_accepts_upper_and_lower_case() -> None:
    """Проверяет нормализацию уровня логирования в верхний регистр."""

    assert normalize_log_level("info") == "INFO"
    assert normalize_log_level("DeBuG") == "DEBUG"


def test_normalize_log_level_raises_on_invalid_value() -> None:
    """Грязный сценарий: неподдерживаемый уровень должен приводить к ошибке."""

    with pytest.raises(ValueError):
        normalize_log_level("VERBOSE")


def test_configure_logging_accepts_valid_level() -> None:
    """Проверяет, что конфиг логирования успешно применяет валидный уровень."""

    applied_level = configure_logging(service_name="unit-test", log_level="WARNING")
    assert applied_level == "WARNING"
