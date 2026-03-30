"""Тесты единого гостевого контента core."""

from __future__ import annotations

from vtelemax.core import (
    GuestMenuAction,
    build_help_screen,
    build_iiko_sync_retry_screen,
    build_main_menu_screen,
    build_profile_review_text,
    build_start_contact_screen,
    build_support_feedback_screen,
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
    assert "👤 Профиль" in labels


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
    assert resolve_guest_menu_action("✅ Согласен") == GuestMenuAction.ACCEPT_RULES


def test_start_contact_screen_contains_phone_prompt() -> None:
    """Проверяет платформенное поведение экрана запроса телефона."""

    telegram_screen = build_start_contact_screen(platform="telegram")
    vk_screen = build_start_contact_screen(platform="vk")
    max_screen = build_start_contact_screen(platform="max")

    assert "+79991234567" not in telegram_screen.text
    assert "+79991234567" in vk_screen.text
    assert "+79991234567" not in max_screen.text
    assert "Поделиться контактом" in telegram_screen.text
    assert "Поделиться контактом" in max_screen.text

    assert len(telegram_screen.buttons) == 1
    assert telegram_screen.buttons[0].action == GuestMenuAction.SHARE_CONTACT
    assert vk_screen.buttons == ()
    assert len(max_screen.buttons) == 1
    assert max_screen.buttons[0].action == GuestMenuAction.SHARE_CONTACT


def test_profile_review_text_hides_consents_and_shows_platforms() -> None:
    """Профиль должен быть компактным: без дат согласий, но с платформами привязок."""

    profile_text = build_profile_review_text(
        phone_e164="+79123456789",
        accounts_count=3,
        accounts_platforms=("telegram", "vk", "max"),
        first_name_input="Иван",
    )

    assert "Согласие с правилами" not in profile_text
    assert "Дата согласия" not in profile_text
    assert "Дата решения по рассылке" not in profile_text
    assert "Привязанных аккаунтов" in profile_text
    assert "* 3" in profile_text
    assert "Telegram, VK, MAX" in profile_text


def test_support_feedback_screen_uses_actual_review_link() -> None:
    """Проверяет, что ссылка отзыва вынесена в кнопку, а не отображается в тексте."""

    screen = build_support_feedback_screen()

    assert "https://rdata.one/Nyyl" not in screen.text
    assert len(screen.buttons) == 2
    assert screen.buttons[0].url == "https://rdata.one/Nyyl"


def test_help_screen_does_not_mention_menu_command() -> None:
    """Проверяет, что в `/help` не рекламируется команда `/menu`."""

    screen = build_help_screen()

    assert "/start" in screen.text
    assert "/menu" not in screen.text


def test_iiko_sync_retry_screen_contains_retry_action() -> None:
    """Проверяет экран ошибки синхронизации с iiko и кнопку повтора."""

    screen = build_iiko_sync_retry_screen()

    assert "iiko" in screen.text.lower()
    assert len(screen.buttons) == 1
    assert screen.buttons[0].action == GuestMenuAction.RETRY_IIKO_SYNC
    assert resolve_guest_menu_action(screen.buttons[0].label) == GuestMenuAction.RETRY_IIKO_SYNC
