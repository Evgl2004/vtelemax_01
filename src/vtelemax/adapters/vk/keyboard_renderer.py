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
                    "type": "callback",
                    "label": button.label,
                    "payload": json.dumps(button.payload, ensure_ascii=False),
                }
            if button.url:
                # Для кнопок-ссылок цвет не указываем (VK API не поддерживает цвет для open_link)
                rendered_row.append(
                    {
                        "action": action,
                    }
                )
            else:
                rendered_row.append(
                    {
                        "action": action,
                        "color": _resolve_button_color(button),
                    }
                )
        buttons.append(rendered_row)

    if screen.screen_id in {"start_rules", "notifications_consent"}:
        # Для onboarding-экранов фиксируем вертикальную раскладку кнопок (по одной в ряд).
        flattened = [button for row in buttons for button in row]
        buttons = [[button] for button in flattened]

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
    if action == GuestMenuAction.BACK_TO_MAIN:
        return "negative"
    if action == GuestMenuAction.BACK_TO_SUPPORT:
        return "primary"
    if action in {GuestMenuAction.SUPPORT, GuestMenuAction.SUPPORT_QUESTION, GuestMenuAction.MY_TICKETS}:
        return "primary"
    if action in {GuestMenuAction.SUPPORT_FEEDBACK, GuestMenuAction.SUPPORT_CONTACTS, GuestMenuAction.OPEN_DOCS}:
        return "secondary"
    if action in {GuestMenuAction.SHARE_CONTACT, GuestMenuAction.ACCEPT_RULES, GuestMenuAction.RETRY_IIKO_SYNC}:
        return "positive"
    if action == GuestMenuAction.VACANCIES:
        return "secondary"
    # BALANCE, VIRTUAL_CARD, PROFILE, HELP, ABOUT, DELIVERY, PROFILE_EDIT, etc.
    return "primary"
