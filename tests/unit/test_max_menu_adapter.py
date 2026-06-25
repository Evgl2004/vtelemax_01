"""Тесты стартового MAX-адаптера меню."""

from __future__ import annotations

from vtelemax.adapters.max import (
    MaxGuestMenuAdapter,
    build_max_payload,
    resolve_action_from_max_payload,
)
from vtelemax.adapters.max.menu_adapter import build_coupon_scope_payload, build_coupon_show_payload
from vtelemax.core import GuestMenuAction


def test_max_payload_build_and_resolve_roundtrip() -> None:
    """Проверяет корректную конвертацию action <-> payload."""

    payload = build_max_payload(GuestMenuAction.SUPPORT)

    assert payload == "support"
    assert resolve_action_from_max_payload(payload) == GuestMenuAction.SUPPORT


def test_max_main_menu_contains_expected_first_buttons() -> None:
    """Проверяет ключевые первые кнопки главного меню (группировка как в VK)."""

    adapter = MaxGuestMenuAdapter()
    screen = adapter.build_main_menu_screen(user_name="Гость")

    # Ожидаем 6 строк
    assert len(screen.rows) == 6
    # Строка 0: Баланс | Виртуальная карта
    assert screen.rows[0][0].label == "💰 Мой баланс"
    assert screen.rows[0][1].label == "🪪 Карта"
    # Строка 1: Мне только спросить
    assert screen.rows[1][0].label == "❓ Мне только спросить"
    # Строка 2: Обратная связь
    assert screen.rows[2][0].label == "✍️ Оставить отзыв"
    # Строка 3: Бизнес-ланч | Бронь стола
    assert screen.rows[3][0].label == "🍽️ Бизнес-ланч"
    assert screen.rows[3][1].label == "🪑 Бронь стола"
    # Строка 4: Доставка | Купоны
    assert screen.rows[4][0].label == "🚚 Доставка"
    assert screen.rows[4][1].label == "🎟️ Купоны"
    # Строка 5: Профиль
    assert screen.rows[5][0].label == "👤 Профиль"


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
    """Проверяет, что в MAX-экране отзыва есть 4 кнопки-ссылки на заведения и кнопка возврата в меню."""

    adapter = MaxGuestMenuAdapter()
    screen = adapter.build_support_feedback_screen()

    assert len(screen.rows) == 5  # 4 заведения + назад
    # Проверяем кнопки заведений
    expected_urls = {
        "https://rdata.one/nwKl",
        "https://rdata.one/pwKl",
        "https://rdata.one/xxKl",
        "https://rdata.one/vxKl",
    }
    actual_urls = {row[0].url for row in screen.rows[:4]}
    assert actual_urls == expected_urls
    # Проверяем, что payload у ссылок OPEN_DOCS
    for row in screen.rows[:4]:
        assert row[0].payload == build_max_payload(GuestMenuAction.OPEN_DOCS)
    # Проверяем кнопку "Назад в меню"
    back_button = screen.rows[4][0]
    assert back_button.url is None
    assert back_button.payload == build_max_payload(GuestMenuAction.BACK_TO_MAIN)


def test_max_support_question_screen_has_back_to_main_button() -> None:
    """Проверяет, что экран «Мне только спросить» содержит возврат в главное меню."""

    adapter = MaxGuestMenuAdapter()
    screen = adapter.build_support_question_screen()

    assert len(screen.rows) == 1
    assert len(screen.rows[0]) == 1
    assert screen.rows[0][0].label == "🔙 Назад в меню"
    assert screen.rows[0][0].payload == GuestMenuAction.BACK_TO_MAIN.value


def test_max_coupon_screens_use_dynamic_payloads_and_back_buttons() -> None:
    """Проверяет MAX-экраны купонов и корректную навигацию назад."""

    adapter = MaxGuestMenuAdapter()

    root = adapter.build_coupons_root_screen(
        text="root",
        scope_buttons=(
            (build_coupon_scope_payload("global"), "🎟️ Общие (1)"),
            (build_coupon_scope_payload("bnYW5p"), "🏠 Грузинка Нани (2)"),
        ),
    )
    coupon_list = adapter.build_coupons_list_screen(
        text="list",
        coupon_buttons=((build_coupon_show_payload("22222222222242228222222222222222"), "🎟️ Купон • 1234"),),
    )
    card = adapter.build_coupon_card_screen(text="card")

    assert root.screen_id == "coupons_root"
    assert root.rows[0][0].payload == "coupon_scope:global"
    assert root.rows[1][0].payload == "coupon_scope:bnYW5p"
    assert root.rows[-1][0].label == "🔙 Назад в меню"
    assert root.rows[-1][0].payload == GuestMenuAction.BACK_TO_MAIN.value

    assert coupon_list.screen_id == "coupon_list"
    assert coupon_list.rows[0][0].payload == "coupon_show:22222222222242228222222222222222"
    assert coupon_list.rows[-1][0].label == "🔙 Назад к купонам"
    assert coupon_list.rows[-1][0].payload == GuestMenuAction.COUPONS.value

    assert card.screen_id == "coupon_card"
    assert card.rows[0][0].label == "🔙 Назад к купонам"
    assert card.rows[0][0].payload == GuestMenuAction.COUPONS.value
