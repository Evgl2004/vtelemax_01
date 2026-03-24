"""Payload-конвертеры VK-адаптера для единого меню core."""

from __future__ import annotations

from vtelemax.core import GuestMenuAction


def build_vk_payload(action: GuestMenuAction) -> dict[str, str]:
    """Строит единый payload для кнопки VK."""

    return {"cmd": action.value}


def resolve_action_from_vk_payload(payload: dict[str, str] | None) -> GuestMenuAction | None:
    """Извлекает действие меню из payload VK."""

    if not payload:
        return None
    cmd = str(payload.get("cmd", "")).strip()
    if not cmd:
        return None
    try:
        return GuestMenuAction(cmd)
    except ValueError:
        return None

