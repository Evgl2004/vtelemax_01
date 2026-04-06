"""Тесты стартового MAX-адаптера меню."""

from __future__ import annotations

from vtelemax.adapters.max import (
    MaxGuestMenuAdapter,
    build_max_payload,
    resolve_action_from_max_payload,
)
from vtelemax.core import GuestMenuAction


def test_max_payload_build_and_resolve_roundtrip() -> None:
    """Проверяет корректную конвертацию action <-> payload."""

    payload = build_max_payload(GuestMenuAction.SUPPORT)

    assert payload == "support"
    assert resolve_action_from_max_payload(payload) == GuestMenuAction.SUPPORT


def test_max_main_menu_contains_expected_first_buttons() -> None:
    """Проверяет ключевые первые кнопки главного меню (вертикальный список)."""

    adapter = MaxGuestMenuAdapter()
    screen = adapter.build_main_menu_screen(user_name="Гость")

    # Проверяем, что семь строк, каждая с одной кнопкой
    assert len(screen.rows) == 7
    assert screen.rows[0][0].label == "💰 Мой баланс"
    assert screen.rows[1][0].label == "🪪 Виртуальная карта"
    assert screen.rows[2][0].label == "🚚 Доставка"
    assert screen.rows[3][0].label == "❓ Мне только спросить"
    assert screen.rows[4][0].label == "💼 Вакансии"
    assert screen.rows[5][0].label == "✍️ Оставить отзыв"
    assert screen.rows[6][0].label == "👤 Профиль"


def test_max_support_menu_respects_my_tickets_flag() -> None:
    """Проверяет условную кнопку «Мои обращения» в MAX-меню поддержки."""

    adapter = MaxGuestMenuAdapter()
    without_tickets = adapter.build_support_menu_screen(has_tickets=False)
    with_tickets = adapter.build_support_menu_screen(has_tickets=True)

    labels_without = [button.label for row in without_tickets.rows for button in row]
    labels_with = [button.label for row in with_tickets.rows for button in row]

    assert "📋 Мои обращения" not in labels_without
    assert "📋 Мои обращения" in labels_with


def test_max_start_rules_screen_has_rules_and_consent_buttons() -> None:
    """Проверяет, что на экране правил есть две кнопки документов и кнопка согласия."""

    adapter = MaxGuestMenuAdapter()
    screen = adapter.build_start_rules_screen()

    assert len(screen.rows) == 3
    # Первая кнопка - согласие на ПД
    assert screen.rows[0][0].url == "https://sagur.24vds.ru/personal-data-consent/max/"
    assert screen.rows[0][0].payload == GuestMenuAction.OPEN_DOCS.value
    # Вторая кнопка - политика конфиденциальности
    assert screen.rows[1][0].url == "https://sagur.24vds.ru/privacy-policy/max/"
    assert screen.rows[1][0].payload == GuestMenuAction.OPEN_DOCS.value
    # Третья кнопка - согласие
    assert screen.rows[2][0].url is None
    assert screen.rows[2][0].payload == GuestMenuAction.ACCEPT_RULES.value


def test_max_start_contact_screen_has_request_contact_button() -> None:
    """Проверяет, что MAX-экран телефона содержит кнопку запроса контакта."""

    adapter = MaxGuestMenuAdapter()
    screen = adapter.build_start_contact_screen()

    assert len(screen.rows) == 1
    assert screen.rows[0][0].request_contact is True
    assert screen.rows[0][0].payload == GuestMenuAction.SHARE_CONTACT.value


def test_max_support_feedback_screen_contains_link_and_back_button() -> None:
    """Проверяет, что в MAX-экране отзыва есть кнопка-ссылка и кнопка возврата."""

    adapter = MaxGuestMenuAdapter()
    screen = adapter.build_support_feedback_screen()

    assert len(screen.rows) == 2
    assert screen.rows[0][0].url == "https://rdata.one/Nyyl"
    assert screen.rows[1][0].payload == GuestMenuAction.BACK_TO_SUPPORT.value


def test_max_support_question_screen_has_back_to_tickets_button() -> None:
    """Проверяет, что экран «Мне только спросить» содержит возврат в «Мои обращения»."""

    adapter = MaxGuestMenuAdapter()
    screen = adapter.build_support_question_screen()

    assert len(screen.rows) == 1
    assert len(screen.rows[0]) == 1
    assert screen.rows[0][0].label == "📋 Мои обращения"
    assert screen.rows[0][0].payload == GuestMenuAction.MY_TICKETS.value
