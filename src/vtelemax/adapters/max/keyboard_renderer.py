"""Рендеринг унифицированного `MaxScreen` в клавиатуру maxapi."""

from __future__ import annotations

from .menu_adapter import MaxScreen


def render_max_keyboard(screen: MaxScreen | None) -> object | None:
    """Преобразует `MaxScreen` в клавиатуру MAX.

    В тестовом окружении, где `maxapi` недоступен, возвращает
    сериализуемую структуру-замену.
    """

    if screen is None or not screen.rows:
        return None

    try:
        from maxapi.types import CallbackButton
        from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
    except Exception:
        return {
            "rows": [
                [{"text": button.label, "payload": button.payload} for button in row] for row in screen.rows
            ]
        }

    builder = InlineKeyboardBuilder()
    for row in screen.rows:
        builder.row(*[CallbackButton(text=button.label, payload=button.payload) for button in row])
    return builder.as_markup()

