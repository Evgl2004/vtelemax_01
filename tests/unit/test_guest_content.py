"""Тесты единого гостевого контента core."""

from __future__ import annotations

from vtelemax.core import (
    GuestMenuAction,
    build_business_lunch_screen,
    build_table_booking_screen,
    build_help_screen,
    build_iiko_sync_retry_screen,
    build_delivery_screen,
    build_main_menu_screen,
    build_profile_screen,
    build_profile_review_text,
    build_start_contact_screen,
    build_support_feedback_screen,
    build_support_menu_screen,
    resolve_guest_menu_action,
    build_vacancies_screen,
)


def test_main_menu_screen_contains_prototype_buttons() -> None:
    """Проверяет наличие эталонных кнопок главного меню из прототипа."""

    screen = build_main_menu_screen(user_name="Гость")
    labels = [button.label for button in screen.buttons]

    assert "💰 Мой баланс" in labels
    assert "🪪 Карта" in labels
    assert "🚚 Доставка" in labels
    assert "❓ Мне только спросить" in labels
    assert "🎟️ Купоны" in labels
    assert "✍️ Оставить отзыв" in labels
    assert "👤 Профиль" in labels
    assert "💼 Вакансии" not in labels


def test_support_menu_screen_includes_my_tickets_only_when_requested() -> None:
    """Проверяет условное отображение пункта 'Мои обращения'."""

    without_tickets = build_support_menu_screen(has_tickets=False)
    with_tickets = build_support_menu_screen(has_tickets=True)

    labels_without = [button.label for button in without_tickets.buttons]
    labels_with = [button.label for button in with_tickets.buttons]

    assert "📋 Мои обращения" not in labels_without
    assert "📋 Мои обращения" in labels_with


def test_resolve_guest_menu_action_detects_text_and_command() -> None:
    """Проверяет распознавание действия по кнопке и разрешенной slash-команде."""

    assert resolve_guest_menu_action("💰 Мой баланс") == GuestMenuAction.BALANCE
    assert resolve_guest_menu_action("Главное меню") == GuestMenuAction.MAIN_MENU
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
    assert "📩 *Уведомления:* Отказ ❌" in profile_text


def test_profile_review_text_shows_active_notifications_status() -> None:
    """Проверяет отображение активного статуса уведомлений в профиле."""

    profile_text = build_profile_review_text(
        phone_e164="+79123456789",
        accounts_count=1,
        accounts_platforms=("telegram",),
        first_name_input="Иван",
        notifications_allowed=True,
    )

    assert "📩 *Уведомления:* Активны ✅" in profile_text


def test_profile_screen_shows_enable_notifications_button_when_declined() -> None:
    """Проверяет, что при отказе от рассылки в профиле есть кнопка включения уведомлений."""

    screen = build_profile_screen(
        phone_e164="+79123456789",
        accounts_count=1,
        accounts_platforms=("vk",),
        first_name_input="Иван",
        notifications_allowed=False,
    )
    actions = [button.action for button in screen.buttons]

    assert actions[0] == GuestMenuAction.PROFILE_NOTIFICATIONS_ENABLE
    assert GuestMenuAction.PROFILE_EDIT in actions
    assert GuestMenuAction.VACANCIES in actions
    assert GuestMenuAction.COUPONS not in actions
    assert GuestMenuAction.BACK_TO_MAIN in actions


def test_profile_screen_hides_enable_notifications_button_when_active() -> None:
    """Проверяет, что при активной рассылке кнопка включения уведомлений не показывается."""

    screen = build_profile_screen(
        phone_e164="+79123456789",
        accounts_count=1,
        accounts_platforms=("max",),
        first_name_input="Иван",
        notifications_allowed=True,
    )
    actions = [button.action for button in screen.buttons]

    assert GuestMenuAction.PROFILE_NOTIFICATIONS_ENABLE not in actions


def test_support_feedback_screen_uses_actual_review_link() -> None:
    """Проверяет, что ссылка отзыва вынесена в кнопку, а не отображается в тексте."""

    screen = build_support_feedback_screen()

    assert "https://rdata.one/Nyyl" not in screen.text
    assert len(screen.buttons) == 4  # 3 заведения + кнопка "Назад в меню"
    # Проверяем, что первые три кнопки — это ссылки на отзывы заведений
    expected_urls = {
        "https://rdata.one/nwKl",
        "https://rdata.one/xxKl",
        "https://rdata.one/vxKl",
    }
    actual_urls = {button.url for button in screen.buttons if button.url}
    assert actual_urls == expected_urls
    # Последняя кнопка — "Назад в меню" без URL
    assert screen.buttons[-1].action == GuestMenuAction.BACK_TO_MAIN
    assert screen.buttons[-1].url is None


def test_delivery_screen_contains_expected_links() -> None:
    """Проверяет, что экран «Доставка» содержит 3 ссылки и кнопку возврата."""

    screen = build_delivery_screen()
    urls = [button.url for button in screen.buttons]

    assert screen.screen_id == "delivery"
    assert len(screen.buttons) == 4
    assert urls[:3] == [
        "https://gruzinka.rest.market/",
        "https://china.rest.market/",
        "https://uzbechka.rest.market/",
    ]
    assert screen.buttons[3].action == GuestMenuAction.BACK_TO_MAIN
    assert screen.buttons[3].url is None


def test_guest_venue_screens_do_not_include_susami() -> None:
    """Проверяет отсутствие закрываемого бренда во всех пользовательских экранах заведений."""

    screens = (
        build_delivery_screen(),
        build_business_lunch_screen(),
        build_table_booking_screen(),
        build_support_feedback_screen(),
    )

    for screen in screens:
        assert all("Сами Сусами" not in button.label for button in screen.buttons)
        assert all("susami" not in (button.url or "").lower() for button in screen.buttons)


def test_vacancies_screen_returns_to_profile_after_menu_swap() -> None:
    """Проверяет возврат из вакансий в профиль после переноса пункта меню."""

    screen = build_vacancies_screen()

    assert screen.screen_id == "vacancies"
    assert screen.buttons[0].action == GuestMenuAction.PROFILE
    assert screen.buttons[0].label == "🔙 Назад в профиль"


def test_help_screen_does_not_mention_menu_command() -> None:
    """Проверяет, что в `/help` не рекламируется команда `/menu`."""

    screen = build_help_screen()

    assert "/start" in screen.text
    assert "/help" in screen.text
    assert "/menu" not in screen.text
    assert "Отдел заботы" not in screen.text
    assert "Мне только спросить" in screen.text


def test_iiko_sync_retry_screen_contains_retry_action() -> None:
    """Проверяет экран ошибки синхронизации с iiko и кнопку повтора."""

    screen = build_iiko_sync_retry_screen()

    assert "iiko" in screen.text.lower()
    assert len(screen.buttons) == 1
    assert screen.buttons[0].action == GuestMenuAction.RETRY_IIKO_SYNC
    assert resolve_guest_menu_action(screen.buttons[0].label) == GuestMenuAction.RETRY_IIKO_SYNC
