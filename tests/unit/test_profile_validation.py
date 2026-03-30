"""Тесты валидации полей профиля."""

from __future__ import annotations

from datetime import date, timedelta

from vtelemax.core.profile_validation import parse_birth_date


def _safe_years_ago(years: int) -> date:
    """Возвращает дату `N` лет назад с учетом 29 февраля."""

    today = date.today()
    try:
        return today.replace(year=today.year - years)
    except ValueError:
        # Для 29 февраля смещаемся на 28 февраля невисокосного года.
        return today.replace(year=today.year - years, month=2, day=28)


def test_parse_birth_date_accepts_adult_age() -> None:
    """Проверяет, что совершеннолетняя дата рождения проходит валидацию."""

    raw = _safe_years_ago(30).strftime("%d.%m.%Y")
    assert parse_birth_date(raw) == _safe_years_ago(30)


def test_parse_birth_date_rejects_underage_user() -> None:
    """Проверяет отклонение даты рождения для пользователя младше 18 лет."""

    raw = _safe_years_ago(17).strftime("%d.%m.%Y")
    assert parse_birth_date(raw) is None


def test_parse_birth_date_rejects_age_over_100() -> None:
    """Проверяет отклонение даты рождения для возраста больше 100 лет."""

    raw = _safe_years_ago(101).strftime("%d.%m.%Y")
    assert parse_birth_date(raw) is None


def test_parse_birth_date_rejects_future_date() -> None:
    """Проверяет отклонение даты рождения из будущего."""

    raw = (date.today() + timedelta(days=1)).strftime("%d.%m.%Y")
    assert parse_birth_date(raw) is None
