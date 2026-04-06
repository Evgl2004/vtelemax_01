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
    """Проверяет ключевые первые кнопки главного меню (специальная группировка для VK)."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_main_menu_screen(user_name="Гость")

    # Проверяем, что пять строк (две пары + три одиночные)
    assert len(screen.rows) == 5
    # Первая строка: баланс и виртуальная карта
    assert len(screen.rows[0]) == 2
    assert screen.rows[0][0].label == "💰 Мой баланс"
    assert screen.rows[0][1].label == "🪪 Виртуальная карта"
    # Вторая строка: "Мне только спросить" и обратная связь
    assert len(screen.rows[1]) == 2
    assert screen.rows[1][0].label == "❓ Мне только спросить"
    assert screen.rows[1][1].label == "✍️ Оставить отзыв"
    # Третья строка: доставка (одна кнопка)
    assert len(screen.rows[2]) == 1
    assert screen.rows[2][0].label == "🚚 Доставка"
    # Четвертая строка: вакансии (одна кнопка)
    assert len(screen.rows[3]) == 1
    assert screen.rows[3][0].label == "💼 Вакансии"
    # Пятая строка: профиль (одна кнопка)
    assert len(screen.rows[4]) == 1
    assert screen.rows[4][0].label == "👤 Профиль"


def test_vk_support_menu_respects_my_tickets_flag() -> None:
    """Проверяет условную кнопку 'Мои обращения' в VK-меню поддержки."""

    adapter = VkGuestMenuAdapter()
    without_tickets = adapter.build_support_menu_screen(has_tickets=False)
    with_tickets = adapter.build_support_menu_screen(has_tickets=True)

    labels_without = [button.label for row in without_tickets.rows for button in row]
    labels_with = [button.label for row in with_tickets.rows for button in row]

    assert "📋 Мои обращения" not in labels_without
    assert "📋 Мои обращения" in labels_with


def test_vk_start_rules_screen_has_rules_and_consent_buttons() -> None:
    """Проверяет, что на экране правил есть кнопка документов и кнопка согласия."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_start_rules_screen()

    assert len(screen.rows) == 3
    assert screen.rows[0][0].url is not None
    assert screen.rows[1][0].url is not None
    assert screen.rows[2][0].payload.get("cmd") == GuestMenuAction.ACCEPT_RULES.value


def test_vk_start_contact_screen_has_no_buttons_for_manual_input() -> None:
    """Проверяет, что VK-экран телефона не содержит кнопок и ждёт ручной ввод."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_start_contact_screen()

    assert screen.rows == ()


def test_vk_support_feedback_screen_contains_link_and_back_button() -> None:
    """Проверяет, что в VK-экране отзыва есть кнопка-ссылка и кнопка возврата."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_support_feedback_screen()

    assert len(screen.rows) == 2
    assert screen.rows[0][0].url == "https://rdata.one/Nyyl"
    assert screen.rows[1][0].payload.get("cmd") == GuestMenuAction.BACK_TO_SUPPORT.value
