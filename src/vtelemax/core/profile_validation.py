"""Валидация и нормализация полей профиля пользователя.

Модуль используется адаптерами Telegram/VK/MAX в режимах регистрации
и редактирования профиля, чтобы правила были едиными между платформами.
"""

from __future__ import annotations

from datetime import date, datetime
import re

_NAME_ALLOWED_PATTERN = re.compile(r"^[A-Za-zА-Яа-яЁё\-\s]{2,50}$")
_EMAIL_ALLOWED_PATTERN = re.compile(
    r"^(?=.{5,254}$)[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,63}$"
)


def normalize_person_name(raw_text: str) -> str | None:
    """Нормализует и проверяет имя/фамилию.

    Разрешены:
    1. кириллица и латиница;
    2. пробел;
    3. дефис.
    """

    normalized = " ".join(str(raw_text or "").strip().split())
    if not normalized:
        return None
    if not _NAME_ALLOWED_PATTERN.fullmatch(normalized):
        return None
    return normalized.title()


def normalize_email(raw_text: str) -> str | None:
    """Нормализует и проверяет email."""

    normalized = str(raw_text or "").strip()
    if not normalized:
        return None
    if not _EMAIL_ALLOWED_PATTERN.fullmatch(normalized):
        return None
    return normalized.lower()


def parse_birth_date(raw_text: str) -> date | None:
    """Преобразует строку `ДД.ММ.ГГГГ` в дату.

    Ограничения:
    1. дата должна быть реальной;
    2. дата не должна быть в будущем;
    3. возраст должен быть в диапазоне 18..100 лет включительно.
    """

    raw = str(raw_text or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.strptime(raw, "%d.%m.%Y").date()
    except ValueError:
        return None

    today = date.today()
    if parsed > today:
        return None

    age = today.year - parsed.year - ((today.month, today.day) < (parsed.month, parsed.day))
    if age < 18:
        return None
    if age > 100:
        return None
    return parsed
