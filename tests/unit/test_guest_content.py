"""Тесты единого гостевого контента core."""

from __future__ import annotations

from vtelemax.core import (
    GuestMenuAction,
    build_main_menu_screen,
    build_start_contact_screen,
    build_support_menu_screen,
    resolve_guest_menu_action,
)


def test_main_menu_screen_contains_prototype_buttons() -> None:
    """Проверяет наличие эталонных кнопок главного меню из прототипа."""

    screen = build_main_menu_screen(user_name="Гость")
    labels = [button.label for button in screen.buttons]

    assert "💰 Мой баланс" in labels
    assert "🪪 Виртуальная карта" in labels
    assert "🆘 Отдел заботы" in labels
    assert "💼 Вакансии" in labels


def test_support_menu_screen_includes_my_tickets_only_when_requested() -> None:
    """Проверяет условное отображение пункта 'Мои обращения'."""

    without_tickets = build_support_menu_screen(has_tickets=False)
    with_tickets = build_support_menu_screen(has_tickets=True)

    labels_without = [button.label for button in without_tickets.buttons]
    labels_with = [button.label for button in with_tickets.buttons]

    assert "📋 Мои обращения" not in labels_without
    assert "📋 Мои обращения" in labels_with


def test_resolve_guest_menu_action_detects_text_and_command() -> None:
    """Проверяет распознавание действия по кнопке и slash-команде."""

    assert resolve_guest_menu_action("💰 Мой баланс") == GuestMenuAction.BALANCE
    assert resolve_guest_menu_action("/menu") == GuestMenuAction.MAIN_MENU


def test_start_contact_screen_contains_phone_prompt() -> None:
    """Проверяет наличие текстового запроса отправки контакта."""

    screen = build_start_contact_screen()
    assert "Поделиться контактом" in screen.text
