"""Тесты стартового VK-адаптера меню."""

from __future__ import annotations

from vtelemax.adapters.vk import VkGuestMenuAdapter, build_vk_payload, resolve_action_from_vk_payload
from vtelemax.adapters.vk.menu_adapter import build_coupon_scope_payload, build_coupon_show_payload
from vtelemax.core import (
    BUTTON_VK_MINIAPP_VERIFY_CHECK,
    BUTTON_VK_MINIAPP_VERIFY_PHONE,
    GuestMenuAction,
)


def test_vk_payload_build_and_resolve_roundtrip() -> None:
    """Проверяет корректную конвертацию action <-> payload."""

    payload = build_vk_payload(GuestMenuAction.SUPPORT)

    assert payload == {"cmd": "support"}
    assert resolve_action_from_vk_payload(payload) == GuestMenuAction.SUPPORT


def test_vk_main_menu_contains_expected_first_buttons() -> None:
    """Проверяет ключевые первые кнопки главного меню (специальная группировка для VK)."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_main_menu_screen(user_name="Гость")

    # Проверяем, что шесть строк (две пары + четыре одиночные/пары)
    assert len(screen.rows) == 6
    # Первая строка: баланс и виртуальная карта
    assert len(screen.rows[0]) == 2
    assert screen.rows[0][0].label == "💰 Мой баланс"
    assert screen.rows[0][1].label == "🪪 Карта"
    # Вторая строка: "Мне только спросить" (одна кнопка)
    assert len(screen.rows[1]) == 1
    assert screen.rows[1][0].label == "❓ Мне только спросить"
    # Третья строка: обратная связь (одна кнопка)
    assert len(screen.rows[2]) == 1
    assert screen.rows[2][0].label == "✍️ Оставить отзыв"
    # Четвертая строка: бизнес-ланч и бронь стола (две кнопки)
    assert len(screen.rows[3]) == 2
    assert screen.rows[3][0].label == "🍽️ Бизнес-ланч"
    assert screen.rows[3][1].label == "🪑 Бронь стола"
    # Пятая строка: доставка и купоны (две кнопки)
    assert len(screen.rows[4]) == 2
    assert screen.rows[4][0].label == "🚚 Доставка"
    assert screen.rows[4][1].label == "🎟️ Купоны"
    # Шестая строка: профиль (одна кнопка)
    assert len(screen.rows[5]) == 1
    assert screen.rows[5][0].label == "👤 Профиль"


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
    """Проверяет, что на экране правил есть две кнопки документов и кнопка согласия."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_start_rules_screen()

    assert len(screen.rows) == 3
    # Первая кнопка - согласие на ПД
    assert screen.rows[0][0].url == "https://sagur.24vds.ru/personal-data-consent/vk/"
    assert screen.rows[0][0].payload.get("cmd") == GuestMenuAction.OPEN_DOCS.value
    # Вторая кнопка - политика конфиденциальности
    assert screen.rows[1][0].url == "https://sagur.24vds.ru/privacy-policy/vk/"
    assert screen.rows[1][0].payload.get("cmd") == GuestMenuAction.OPEN_DOCS.value
    # Третья кнопка - согласие
    assert screen.rows[2][0].url is None
    assert screen.rows[2][0].payload.get("cmd") == GuestMenuAction.ACCEPT_RULES.value


def test_vk_start_contact_screen_has_no_buttons_for_manual_input() -> None:
    """Проверяет, что VK-экран телефона не содержит кнопок и ждёт ручной ввод."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_start_contact_screen()

    assert screen.rows == ()


def test_vk_start_contact_screen_uses_miniapp_buttons_when_feature_enabled() -> None:
    """Проверяет, что VK-экран телефона содержит Mini App flow-кнопки при включенном флаге."""

    adapter = VkGuestMenuAdapter(
        vk_phone_verification_miniapp_enabled=True,
        vk_phone_verification_miniapp_url="https://example.org/vk-miniapp",
    )
    screen = adapter.build_start_contact_screen()

    assert screen.screen_id == "start_contact"
    assert len(screen.rows) == 2
    assert "+79991234567" not in screen.text

    open_miniapp_button = screen.rows[0][0]
    check_status_button = screen.rows[1][0]

    assert open_miniapp_button.label == BUTTON_VK_MINIAPP_VERIFY_PHONE
    assert open_miniapp_button.url == "https://example.org/vk-miniapp"
    assert open_miniapp_button.payload.get("cmd") == GuestMenuAction.OPEN_DOCS.value

    assert check_status_button.label == BUTTON_VK_MINIAPP_VERIFY_CHECK
    assert check_status_button.url is None
    assert check_status_button.payload.get("cmd") == GuestMenuAction.VK_PHONE_VERIFICATION_CHECK.value


def test_vk_profile_screen_hides_miniapp_buttons_when_feature_disabled() -> None:
    """Проверяет, что в профиле VK нет Mini App-кнопок при выключенном флаге."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_profile_screen(
        phone_e164="+79120000001",
        accounts_count=1,
        notifications_allowed=True,
    )

    labels = [button.label for row in screen.rows for button in row]
    assert BUTTON_VK_MINIAPP_VERIFY_PHONE not in labels
    assert BUTTON_VK_MINIAPP_VERIFY_CHECK not in labels


def test_vk_profile_screen_shows_miniapp_buttons_when_feature_enabled() -> None:
    """Проверяет, что в профиле VK появляются Mini App-кнопки при включенном флаге."""

    adapter = VkGuestMenuAdapter(
        vk_phone_verification_miniapp_enabled=True,
        vk_phone_verification_miniapp_url="https://example.org/vk-miniapp",
    )
    screen = adapter.build_profile_screen(
        phone_e164="+79120000002",
        accounts_count=1,
        notifications_allowed=True,
        miniapp_url_override="https://example.org/vk-miniapp?uid=1001&ts=1&sig=abc",
    )

    open_miniapp_button = screen.rows[-2][0]
    check_status_button = screen.rows[-1][0]

    assert open_miniapp_button.label == BUTTON_VK_MINIAPP_VERIFY_PHONE
    assert open_miniapp_button.url == "https://example.org/vk-miniapp?uid=1001&ts=1&sig=abc"
    assert open_miniapp_button.payload.get("cmd") == GuestMenuAction.OPEN_DOCS.value

    assert check_status_button.label == BUTTON_VK_MINIAPP_VERIFY_CHECK
    assert check_status_button.url is None
    assert check_status_button.payload.get("cmd") == GuestMenuAction.VK_PHONE_VERIFICATION_CHECK.value


def test_vk_support_feedback_screen_contains_link_and_back_button() -> None:
    """Проверяет, что в VK-экране отзыва есть 4 кнопки-ссылки на заведения и кнопка возврата в меню."""

    adapter = VkGuestMenuAdapter()
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
        assert row[0].payload.get("cmd") == GuestMenuAction.OPEN_DOCS.value
    # Проверяем кнопку "Назад в меню"
    back_button = screen.rows[4][0]
    assert back_button.url is None
    assert back_button.payload.get("cmd") == GuestMenuAction.BACK_TO_MAIN.value


def test_vk_support_question_screen_has_back_to_main_button() -> None:
    """Проверяет, что экран «Мне только спросить» содержит возврат в главное меню."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_support_question_screen()

    assert len(screen.rows) == 1
    assert len(screen.rows[0]) == 1
    assert screen.rows[0][0].label == "🔙 Назад в меню"
    assert screen.rows[0][0].payload.get("cmd") == GuestMenuAction.BACK_TO_MAIN.value


def test_vk_coupon_screens_use_dynamic_payloads_and_back_buttons() -> None:
    """Проверяет VK-экраны купонов и корректную навигацию назад."""

    adapter = VkGuestMenuAdapter()

    root = adapter.build_coupons_root_screen(
        text="root",
        scope_buttons=(
            (build_coupon_scope_payload("global"), "🎟️ Общие (1)"),
            (build_coupon_scope_payload("bnYW5p"), "💃 Грузинка Нани (2)"),
        ),
    )
    coupon_list = adapter.build_coupons_list_screen(
        text="list",
        coupon_buttons=((build_coupon_show_payload("22222222222242228222222222222222"), "🎟️ Купон • 1234"),),
    )
    card = adapter.build_coupon_card_screen(text="card")

    assert root.screen_id == "coupons_root"
    assert root.rows[0][0].payload == {"cmd": "coupon_scope:global"}
    assert root.rows[1][0].payload == {"cmd": "coupon_scope:bnYW5p"}
    assert root.rows[-1][0].label == "🔙 Назад в меню"
    assert root.rows[-1][0].payload == {"cmd": GuestMenuAction.BACK_TO_MAIN.value}

    assert coupon_list.screen_id == "coupon_list"
    assert coupon_list.rows[0][0].payload == {"cmd": "coupon_show:22222222222242228222222222222222"}
    assert coupon_list.rows[-1][0].label == "🔙 Назад к купонам"
    assert coupon_list.rows[-1][0].payload == {"cmd": GuestMenuAction.COUPONS.value}

    assert card.screen_id == "coupon_card"
    assert card.rows[0][0].label == "🔙 Назад к купонам"
    assert card.rows[0][0].payload == {"cmd": GuestMenuAction.COUPONS.value}
