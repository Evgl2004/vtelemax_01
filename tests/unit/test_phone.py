"""Тесты нормализации телефона для strict identity."""

import pytest

from vtelemax.core.phone import normalize_phone


@pytest.mark.parametrize(
    ("raw_phone", "expected"),
    [
        ("+7 (912) 345-67-89", "+79123456789"),
        ("8 (912) 345-67-89", "+79123456789"),
        ("79123456789", "+79123456789"),
        ("9123456789", "+79123456789"),
    ],
)
def test_normalize_phone_accepts_common_russian_formats(raw_phone: str, expected: str) -> None:
    """Проверяет канонизацию наиболее частых пользовательских форматов."""

    assert normalize_phone(raw_phone) == expected


@pytest.mark.parametrize(
    "raw_phone",
    [
        "",
        "abc",
        "+12345",
        "+380991234567",
    ],
)
def test_normalize_phone_rejects_unsupported_values(raw_phone: str) -> None:
    """Проверяет, что неподдерживаемые форматы отвергаются."""

    with pytest.raises(ValueError):
        normalize_phone(raw_phone)

