"""Payload-конвертеры MAX-адаптера для единого меню core."""

from __future__ import annotations

from vtelemax.core import GuestMenuAction


def build_max_payload(action: GuestMenuAction) -> str:
    """Строит payload callback-кнопки MAX."""

    return action.value


def resolve_action_from_max_payload(payload: object | None) -> GuestMenuAction | None:
    """Извлекает действие меню из payload MAX.

    Поддерживает оба варианта:

    1. строка (типичный callback payload в maxapi);
    2. словарь с ключом `cmd` (для унифицированных тестовых сценариев).
    """

    if payload is None:
        return None

    cmd: str
    if isinstance(payload, dict):
        raw_cmd = payload.get("cmd", "")
        cmd = str(raw_cmd).strip()
    else:
        cmd = str(payload).strip()

    if not cmd:
        return None

    try:
        return GuestMenuAction(cmd)
    except ValueError:
        return None

