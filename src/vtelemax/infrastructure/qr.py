"""Утилиты генерации QR-кода для сценариев виртуальной карты.

Модуль вынесен в инфраструктурный слой, чтобы:
1. Не дублировать QR-логику в Telegram/VK/MAX-роутерах.
2. Сохранять единый формат PNG-картинки для всех платформ.
3. Аккуратно обрабатывать отсутствие необязательной зависимости `qrcode`.
"""

from __future__ import annotations

from io import BytesIO


class QrGenerationError(RuntimeError):
    """Ошибка генерации QR-кода на инфраструктурном уровне."""


def generate_qr_png_bytes(data: str) -> bytes:
    """Генерирует PNG-байты QR-кода по переданной строке.

    Args:
        data: Строка для кодирования (обычно номер виртуальной карты).

    Returns:
        PNG-байты с QR-кодом.

    Raises:
        ValueError: Если в функцию передана пустая строка.
        QrGenerationError: Если не установлена библиотека `qrcode` или генерация не удалась.
    """

    normalized_data = str(data).strip()
    if not normalized_data:
        raise ValueError("Строка для генерации QR-кода не может быть пустой.")

    try:
        import qrcode
    except Exception as error:  # noqa: BLE001
        raise QrGenerationError(
            "Библиотека `qrcode` недоступна. Установите зависимости проекта заново."
        ) from error

    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=12,
            border=2,
        )
        qr.add_data(normalized_data)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    except Exception as error:  # noqa: BLE001
        raise QrGenerationError("Не удалось сгенерировать QR-код.") from error
