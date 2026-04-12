"""Тесты рендера VK-клавиатур."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from uuid import uuid4

from vtelemax.adapters.vk import VkGuestMenuAdapter, render_vk_keyboard
from vtelemax.core import OpenSupportTicketSummary, SupportTicketStatus


def test_render_vk_keyboard_returns_json_for_screen_with_buttons() -> None:
    """Проверяет, что экран с кнопками рендерится в JSON."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_main_menu_screen(user_name="Гость")

    keyboard_json = render_vk_keyboard(screen)

    assert keyboard_json is not None
    assert "💰 Мой баланс" in keyboard_json
    assert "payload" in keyboard_json
    parsed = json.loads(keyboard_json)
    assert parsed["inline"] is True


def test_render_vk_keyboard_returns_none_for_screen_without_buttons() -> None:
    """Проверяет отсутствие клавиатуры для экранов без кнопок."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_help_screen()

    keyboard_json = render_vk_keyboard(screen)

    assert keyboard_json is None


def test_render_vk_start_rules_keyboard_contains_inline_buttons() -> None:
    """Проверяет, что для onboarding-экрана правил рендерится inline-клавиатура."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_start_rules_screen()

    keyboard_json = render_vk_keyboard(screen)

    assert keyboard_json is not None
    parsed = json.loads(keyboard_json)
    assert parsed["inline"] is True
    assert len(parsed["buttons"]) == 3


def test_vk_keyboard_button_colors() -> None:
    """Проверяет, что кнопки получают правильные цвета согласно логике."""
    from vtelemax.adapters.vk.keyboard_renderer import _resolve_button_color
    from vtelemax.adapters.vk.payloads import build_vk_payload
    from vtelemax.core import GuestMenuAction
    from vtelemax.adapters.vk.menu_adapter import VkButton

    # Тестовые кейсы: (действие, ожидаемый цвет)
    test_cases = [
        (GuestMenuAction.BACK_TO_MAIN, "negative"),
        (GuestMenuAction.BACK_TO_SUPPORT, "primary"),
        (GuestMenuAction.SUPPORT, "primary"),
        (GuestMenuAction.SUPPORT_QUESTION, "primary"),
        (GuestMenuAction.MY_TICKETS, "primary"),
        (GuestMenuAction.SUPPORT_FEEDBACK, "secondary"),
        (GuestMenuAction.SUPPORT_CONTACTS, "secondary"),
        (GuestMenuAction.OPEN_DOCS, "secondary"),
        (GuestMenuAction.SHARE_CONTACT, "positive"),
        (GuestMenuAction.ACCEPT_RULES, "positive"),
        (GuestMenuAction.RETRY_IIKO_SYNC, "positive"),
        (GuestMenuAction.VACANCIES, "secondary"),
        (GuestMenuAction.BALANCE, "primary"),
        (GuestMenuAction.VIRTUAL_CARD, "primary"),
        (GuestMenuAction.PROFILE, "primary"),
        (GuestMenuAction.HELP, "primary"),
        (GuestMenuAction.ABOUT, "primary"),
        (GuestMenuAction.DELIVERY, "primary"),
    ]

    for action, expected_color in test_cases:
        payload = build_vk_payload(action)
        button = VkButton(label="Тест", payload=payload, url=None)
        color = _resolve_button_color(button)
        assert color == expected_color, f"Для действия {action} ожидался цвет {expected_color}, получен {color}"


def test_vk_moderation_tickets_keyboard_does_not_exceed_inline_row_limit() -> None:
    """Проверяет, что экран списка тикетов модератора не превышает лимит VK inline-строк."""

    adapter = VkGuestMenuAdapter()
    tickets = tuple(
        OpenSupportTicketSummary(
            ticket_id=uuid4(),
            status=SupportTicketStatus.OPEN,
            source_platform="vk",
            last_guest_platform="vk",
            created_at=datetime(2026, 4, 13, tzinfo=timezone.utc),
        )
        for _ in range(12)
    )
    screen = adapter.build_moderation_tickets_screen(
        filter_key="all",
        current_page=1,
        total_pages=3,
        tickets=tickets,
    )

    assert len(screen.rows) <= 6
    assert screen.rows[-1][0].label == "⬅️ К фильтрам"
