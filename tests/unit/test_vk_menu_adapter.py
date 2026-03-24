"""Тесты стартового VK-адаптера меню."""

from __future__ import annotations

from vtelemax.adapters.vk import VkGuestMenuAdapter, build_vk_payload, resolve_action_from_vk_payload
from vtelemax.core import GuestMenuAction


def test_vk_payload_build_and_resolve_roundtrip() -> None:
    """Проверяет корректную конвертацию action <-> payload."""

    payload = build_vk_payload(GuestMenuAction.SUPPORT)

    assert payload == {"cmd": "support"}
    assert resolve_action_from_vk_payload(payload) == GuestMenuAction.SUPPORT


def test_vk_main_menu_contains_expected_first_buttons() -> None:
    """Проверяет ключевые первые кнопки главного меню."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_main_menu_screen(user_name="Гость")

    assert screen.rows[0][0].label == "💰 Мой баланс"
    assert screen.rows[1][0].label == "🪪 Виртуальная карта"
    assert screen.rows[2][0].label == "🆘 Отдел заботы"


def test_vk_support_menu_respects_my_tickets_flag() -> None:
    """Проверяет условную кнопку 'Мои обращения' в VK-меню поддержки."""

    adapter = VkGuestMenuAdapter()
    without_tickets = adapter.build_support_menu_screen(has_tickets=False)
    with_tickets = adapter.build_support_menu_screen(has_tickets=True)

    labels_without = [button.label for row in without_tickets.rows for button in row]
    labels_with = [button.label for row in with_tickets.rows for button in row]

    assert "📋 Мои обращения" not in labels_without
    assert "📋 Мои обращения" in labels_with
