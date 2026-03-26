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
        from maxapi.types import CallbackButton, LinkButton, RequestContactButton
        from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
    except Exception:
        return {
            "rows": [
                [
                    {
                        "text": button.label,
                        "payload": button.payload,
                        "url": button.url,
                        "request_contact": button.request_contact,
                    }
                    for button in row
                ]
                for row in screen.rows
            ]
        }

    builder = InlineKeyboardBuilder()
    for row in screen.rows:
        buttons = []
        for button in row:
            if button.request_contact:
                buttons.append(RequestContactButton(text=button.label))
            elif button.url:
                buttons.append(LinkButton(text=button.label, url=button.url))
            else:
                buttons.append(CallbackButton(text=button.label, payload=button.payload))
        builder.row(*buttons)
    return builder.as_markup()
