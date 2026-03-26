"""Рендеринг унифицированного `VkScreen` в клавиатуру vkbottle."""

from __future__ import annotations

import json

from vtelemax.core import GuestMenuAction

from .menu_adapter import VkButton, VkScreen
from .payloads import resolve_action_from_vk_payload


def render_vk_keyboard(screen: VkScreen | None) -> str | None:
    """Преобразует `VkScreen` в JSON-клавиатуру VK.

    Реализация выполняется без прямого импорта `vkbottle`, чтобы модуль
    оставался тестопригодным даже в ограниченных окружениях.
    """

    if screen is None or not screen.rows:
        return None

    buttons: list[list[dict[str, object]]] = []
    for row in screen.rows:
        rendered_row: list[dict[str, object]] = []
        for button in row:
            if button.url:
                action = {
                    "type": "open_link",
                    "label": button.label,
                    "link": button.url,
                    "payload": json.dumps(button.payload, ensure_ascii=False),
                }
            else:
                action = {
                    "type": "text",
                    "label": button.label,
                    "payload": json.dumps(button.payload, ensure_ascii=False),
                }
            rendered_row.append(
                {
                    "action": action,
                    "color": _resolve_button_color(button),
                }
            )
        buttons.append(rendered_row)

    return json.dumps(
        {
            "one_time": False,
            # В прототипе VK-кнопки были inline и отображались как часть сообщения.
            "inline": True,
            "buttons": buttons,
        },
        ensure_ascii=False,
    )


def _resolve_button_color(button: VkButton) -> str:
    """Выбирает цвет кнопки в зависимости от действия меню."""

    action = resolve_action_from_vk_payload(button.payload)
    if action is None:
        return "primary"
    if action in {GuestMenuAction.BACK_TO_MAIN, GuestMenuAction.BACK_TO_SUPPORT}:
        return "negative"
    if action in {GuestMenuAction.SUPPORT, GuestMenuAction.SUPPORT_QUESTION}:
        return "primary"
    if action in {GuestMenuAction.SUPPORT_FEEDBACK, GuestMenuAction.SUPPORT_CONTACTS}:
        return "secondary"
    if action == GuestMenuAction.SHARE_CONTACT:
        return "positive"
    if action == GuestMenuAction.OPEN_DOCS:
        return "secondary"
    return "primary"
