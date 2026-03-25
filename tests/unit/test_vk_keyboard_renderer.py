"""Тесты рендера VK-клавиатур."""

from __future__ import annotations

import json

from vtelemax.adapters.vk import VkGuestMenuAdapter, render_vk_keyboard


def test_render_vk_keyboard_returns_json_for_screen_with_buttons() -> None:
    """Проверяет, что экран с кнопками рендерится в JSON."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_main_menu_screen(user_name="Гость")

    keyboard_json = render_vk_keyboard(screen)

    assert keyboard_json is not None
    assert "Мой баланс" in keyboard_json
    assert "payload" in keyboard_json
    parsed = json.loads(keyboard_json)
    assert parsed["inline"] is True


def test_render_vk_keyboard_returns_none_for_screen_without_buttons() -> None:
    """Проверяет отсутствие клавиатуры для экранов без кнопок."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_help_screen()

    keyboard_json = render_vk_keyboard(screen)

    assert keyboard_json is None
