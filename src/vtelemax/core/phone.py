"""Нормализация и базовая валидация телефонных номеров.

На стартовом этапе проекта принят российский профиль нормализации:

1. Удаляем из ввода все символы, кроме цифр.
2. Поддерживаем входы вида `8XXXXXXXXXX`, `7XXXXXXXXXX`, `+7XXXXXXXXXX`.
3. Для 10 цифр без кода страны считаем, что это российский номер и добавляем `+7`.
4. Канонический формат возвращается только как `+7XXXXXXXXXX`.
"""

from __future__ import annotations


def normalize_phone(raw_phone: str) -> str:
    """Приводит телефон к каноническому формату E.164 для РФ.

    Args:
        raw_phone: Телефон в произвольном пользовательском формате.

    Returns:
        Нормализованный телефон вида `+7XXXXXXXXXX`.

    Raises:
        ValueError: Если номер нельзя привести к поддерживаемому формату.
    """

    if raw_phone is None:
        raise ValueError("Телефон не может быть пустым (None).")

    digits = "".join(char for char in str(raw_phone) if char.isdigit())
    if not digits:
        raise ValueError("Телефон не содержит цифр.")

    if len(digits) == 10:
        # Локальный российский формат без кода страны.
        digits = "7" + digits
    elif len(digits) == 11 and digits.startswith("8"):
        # Российский формат с префиксом 8.
        digits = "7" + digits[1:]

    if len(digits) != 11 or not digits.startswith("7"):
        raise ValueError(
            "Поддерживаются только российские номера формата +7XXXXXXXXXX, "
            "8XXXXXXXXXX или XXXXXXXXXX."
        )

    return f"+{digits}"

