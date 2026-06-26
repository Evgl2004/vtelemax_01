"""Тесты Telegram-клавиатур меню."""

from __future__ import annotations

from vtelemax.adapters.telegram.menu import (
    GUEST_MESSAGE_CLOSE_CALLBACK,
    MOD_CLOSE_PREFIX,
    MOD_LIST_PREFIX,
    MOD_OPEN_PREFIX,
    MOD_PAGE_PREFIX,
    MOD_PHONE_HIDE_PREFIX,
    MOD_PHONE_SHOW_PREFIX,
    MOD_REPLY_PREFIX,
    MOD_TICKET_PREFIX,
    RULES_ACCEPT_CALLBACK,
    USER_TICKETS_PREV_PAGE_PREFIX,
    USER_TICKETS_NEXT_PAGE_PREFIX,
    USER_TICKET_DETAILS_PREFIX,
    build_coupon_card_inline_keyboard,
    build_coupon_delivery_inline_keyboard,
    build_coupon_scope_callback,
    build_coupon_show_callback,
    build_coupons_list_inline_keyboard,
    build_coupons_root_inline_keyboard,
    build_contact_request_keyboard,
    build_delivery_inline_keyboard,
    build_iiko_sync_retry_inline_keyboard,
    build_guest_message_close_inline_keyboard,
    build_main_menu_inline_keyboard,
    build_moderation_main_inline_keyboard,
    build_moderation_notification_inline_keyboard,
    build_moderation_ticket_details_inline_keyboard,
    build_moderation_tickets_inline_keyboard,
    build_profile_edit_cancel_inline_keyboard,
    build_profile_edit_inline_keyboard,
    build_profile_gender_inline_keyboard,
    build_profile_inline_keyboard,
    build_profile_notifications_toggle_inline_keyboard,
    build_rules_consent_inline_keyboard,
    build_support_feedback_inline_keyboard,
    build_support_menu_inline_keyboard,
    build_user_tickets_pagination_keyboard,
)
from vtelemax.core import (
    BUTTON_ACCEPT_RULES,
    BUTTON_PERSONAL_DATA_CONSENT_LINK,
    BUTTON_PRIVACY_POLICY_LINK,
    BUTTON_PROFILE_EDIT_CANCEL,
    BUTTON_RETRY_IIKO_SYNC,
    OpenSupportTicketSummary,
    PERSONAL_DATA_CONSENT_URLS,
    PRIVACY_POLICY_URLS,
    SupportTicketStatus,
    GuestMenuAction,
)


def test_build_rules_consent_keyboard_contains_docs_and_accept_buttons() -> None:
    """Проверяет, что клавиатура правил содержит две кнопки документов и кнопку согласия."""

    keyboard = build_rules_consent_inline_keyboard()

    assert keyboard.inline_keyboard
    assert len(keyboard.inline_keyboard) == 3

    personal_data_row = keyboard.inline_keyboard[0]
    privacy_policy_row = keyboard.inline_keyboard[1]
    accept_row = keyboard.inline_keyboard[2]
    assert len(personal_data_row) == 1
    assert len(privacy_policy_row) == 1
    assert len(accept_row) == 1

    personal_data_button = personal_data_row[0]
    privacy_policy_button = privacy_policy_row[0]
    accept_button = accept_row[0]

    assert personal_data_button.text == BUTTON_PERSONAL_DATA_CONSENT_LINK
    assert personal_data_button.url == PERSONAL_DATA_CONSENT_URLS["telegram"]

    assert privacy_policy_button.text == BUTTON_PRIVACY_POLICY_LINK
    assert privacy_policy_button.url == PRIVACY_POLICY_URLS["telegram"]

    assert accept_button.text == BUTTON_ACCEPT_RULES
    assert accept_button.callback_data == RULES_ACCEPT_CALLBACK


def test_build_contact_request_keyboard_contains_request_contact_button() -> None:
    """Проверяет, что клавиатура телефона запрашивает контакт Telegram-пользователя."""

    keyboard = build_contact_request_keyboard()

    assert keyboard.keyboard
    assert len(keyboard.keyboard) == 1
    assert len(keyboard.keyboard[0]) == 1
    button = keyboard.keyboard[0][0]
    assert button.text
    assert button.request_contact is True


def test_build_iiko_sync_retry_keyboard_contains_retry_button() -> None:
    """Проверяет inline-клавиатуру повтора синхронизации с iiko."""

    keyboard = build_iiko_sync_retry_inline_keyboard()

    assert len(keyboard.inline_keyboard) == 1
    assert len(keyboard.inline_keyboard[0]) == 1
    button = keyboard.inline_keyboard[0][0]
    assert button.text == BUTTON_RETRY_IIKO_SYNC
    assert button.callback_data == GuestMenuAction.RETRY_IIKO_SYNC.value


def test_build_support_feedback_keyboard_contains_link_and_back_button() -> None:
    """Проверяет клавиатуру экрана «Оставить отзыв»: 4 ссылки на заведения и кнопка возврата в меню."""

    keyboard = build_support_feedback_inline_keyboard()

    assert len(keyboard.inline_keyboard) == 5  # 4 заведения + назад
    # Проверяем кнопки заведений
    expected_urls = {
        "https://rdata.one/nwKl",
        "https://rdata.one/pwKl",
        "https://rdata.one/xxKl",
        "https://rdata.one/vxKl",
    }
    actual_urls = {row[0].url for row in keyboard.inline_keyboard[:4]}
    assert actual_urls == expected_urls
    # Проверяем, что callback_data у ссылок None
    for row in keyboard.inline_keyboard[:4]:
        assert row[0].callback_data is None
    # Проверяем кнопку "Назад в меню"
    back_button = keyboard.inline_keyboard[4][0]
    assert back_button.text == "🔙 Назад в меню"
    assert back_button.url is None
    assert back_button.callback_data == GuestMenuAction.BACK_TO_MAIN.value


def test_build_delivery_keyboard_contains_links_and_back_button() -> None:
    """Проверяет, что в подменю «Доставка» есть URL-кнопки и возврат в меню."""

    keyboard = build_delivery_inline_keyboard()

    assert len(keyboard.inline_keyboard) == 5
    first_button = keyboard.inline_keyboard[0][0]
    assert first_button.text == "💃 Грузинка Нани"
    assert first_button.url == "https://gruzinka.rest.market/"
    assert first_button.callback_data is None
    for row in keyboard.inline_keyboard[:4]:
        button = row[0]
        assert button.url is not None
        assert button.callback_data is None
    back_button = keyboard.inline_keyboard[4][0]
    assert back_button.text == "🔙 Назад в меню"
    assert back_button.url is None
    assert back_button.callback_data == GuestMenuAction.BACK_TO_MAIN.value


def test_build_main_menu_keyboard_contains_support_question_and_feedback_link() -> None:
    """Проверяет, что главное inline-меню содержит вопрос, ссылку на отзыв и новую группировку."""

    keyboard = build_main_menu_inline_keyboard()
    
    # Проверяем структуру: 6 строк
    assert len(keyboard.inline_keyboard) == 6
    
    # Строка 1: Баланс | Виртуальная карта (2 кнопки)
    row1 = keyboard.inline_keyboard[0]
    assert len(row1) == 2
    assert row1[0].text == "💰 Мой баланс"
    assert row1[0].callback_data == GuestMenuAction.BALANCE.value
    assert row1[1].text == "🪪 Карта"
    assert row1[1].callback_data == GuestMenuAction.VIRTUAL_CARD.value
    
    # Строка 2: Мне только спросить (1 кнопка)
    row2 = keyboard.inline_keyboard[1]
    assert len(row2) == 1
    assert row2[0].text == "❓ Мне только спросить"
    assert row2[0].callback_data == GuestMenuAction.SUPPORT_QUESTION.value
    
    # Строка 3: Оставить отзыв (теперь подменю с выбором заведения)
    row3 = keyboard.inline_keyboard[2]
    assert len(row3) == 1
    assert row3[0].text == "✍️ Оставить отзыв"
    assert row3[0].url is None
    assert row3[0].callback_data == GuestMenuAction.SUPPORT_FEEDBACK.value
    
    # Строка 4: Бизнес-ланч | Бронь стола (2 кнопки)
    row4 = keyboard.inline_keyboard[3]
    assert len(row4) == 2
    assert row4[0].text == "🍽️ Бизнес-ланч"
    assert row4[0].callback_data == GuestMenuAction.BUSINESS_LUNCH.value
    assert row4[1].text == "🪑 Бронь стола"
    assert row4[1].callback_data == GuestMenuAction.TABLE_BOOKING.value
    
    # Строка 5: Доставка | Купоны (2 кнопки)
    row5 = keyboard.inline_keyboard[4]
    assert len(row5) == 2
    assert row5[0].text == "🚚 Доставка"
    assert row5[0].callback_data == GuestMenuAction.DELIVERY.value
    assert row5[1].text == "🎟️ Купоны"
    assert row5[1].callback_data == GuestMenuAction.COUPONS.value
    
    # Строка 6: Профиль (1 кнопка)
    row6 = keyboard.inline_keyboard[5]
    assert len(row6) == 1
    assert row6[0].text == "👤 Профиль"
    assert row6[0].callback_data == GuestMenuAction.PROFILE.value


def test_all_telegram_callback_data_fit_telegram_limits() -> None:
    """Проверяет, что callback_data не превышает лимит Telegram (64 байта)."""
    from datetime import datetime, timezone
    from uuid import uuid4

    sample_ticket_id = uuid4()
    moderation_tickets = (
        OpenSupportTicketSummary(
            ticket_id=sample_ticket_id,
            status=SupportTicketStatus.OPEN,
            source_platform="telegram",
            last_guest_platform="telegram",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )
    keyboards = [
        build_main_menu_inline_keyboard(),
        build_guest_message_close_inline_keyboard(),
        build_delivery_inline_keyboard(),
        build_support_menu_inline_keyboard(has_tickets=False),
        build_support_menu_inline_keyboard(has_tickets=True),
        build_support_feedback_inline_keyboard(),
        build_profile_inline_keyboard(notifications_allowed=True),
        build_profile_inline_keyboard(notifications_allowed=False),
        build_coupons_root_inline_keyboard(
            scope_buttons=((build_coupon_scope_callback("global"), "🎟️ Общие (1)"),)
        ),
        build_coupons_list_inline_keyboard(
            coupon_buttons=((build_coupon_show_callback(sample_ticket_id.hex), "🎟️ Купон • ABCD"),)
        ),
        build_coupon_card_inline_keyboard(),
        build_profile_edit_inline_keyboard(can_edit_birth_date=True),
        build_profile_edit_inline_keyboard(can_edit_birth_date=False),
        build_profile_gender_inline_keyboard(),
        build_profile_notifications_toggle_inline_keyboard(notifications_allowed=True),
        build_profile_notifications_toggle_inline_keyboard(notifications_allowed=False),
        build_iiko_sync_retry_inline_keyboard(),
        build_moderation_main_inline_keyboard(),
        build_moderation_notification_inline_keyboard(str(sample_ticket_id)),
        build_moderation_tickets_inline_keyboard(
            filter_key="new",
            current_page=1,
            total_pages=3,
            tickets=moderation_tickets,
        ),
        build_moderation_ticket_details_inline_keyboard(
            ticket_id=str(sample_ticket_id),
            filter_key="new",
            page=12,
            status_value="open",
        ),
    ]

    for keyboard in keyboards:
        for row in keyboard.inline_keyboard:
            for button in row:
                callback_data = button.callback_data
                if callback_data is None:
                    continue
                assert len(callback_data.encode("utf-8")) <= 64


def test_build_profile_inline_keyboard_depends_on_notifications_status() -> None:
    """Проверяет условную кнопку включения уведомлений на экране профиля."""

    active_keyboard = build_profile_inline_keyboard(notifications_allowed=True)
    declined_keyboard = build_profile_inline_keyboard(notifications_allowed=False)

    active_texts = [button.text for row in active_keyboard.inline_keyboard for button in row]
    declined_texts = [button.text for row in declined_keyboard.inline_keyboard for button in row]

    assert "✅ Получать уведомления!" not in active_texts
    assert "✅ Получать уведомления!" in declined_texts


def test_build_coupon_keyboards_use_expected_callbacks() -> None:
    """Проверяет клавиатуры корня, списка и карточки купонов."""

    root_keyboard = build_coupons_root_inline_keyboard(
        scope_buttons=(
            (build_coupon_scope_callback("global"), "🎟️ Общие (1)"),
            (build_coupon_scope_callback("bnYW5p"), "💃 Грузинка Нани (2)"),
        )
    )
    list_keyboard = build_coupons_list_inline_keyboard(
        coupon_buttons=((build_coupon_show_callback("22222222222242228222222222222222"), "🎟️ Купон • 1234"),)
    )
    card_keyboard = build_coupon_card_inline_keyboard()

    assert root_keyboard.inline_keyboard[0][0].callback_data == "coupon_scope:global"
    assert root_keyboard.inline_keyboard[1][0].callback_data == "coupon_scope:bnYW5p"
    assert root_keyboard.inline_keyboard[-1][0].text == "🔙 Назад в меню"
    assert root_keyboard.inline_keyboard[-1][0].callback_data == GuestMenuAction.BACK_TO_MAIN.value

    assert list_keyboard.inline_keyboard[0][0].callback_data == "coupon_show:22222222222242228222222222222222"
    assert list_keyboard.inline_keyboard[-1][0].text == "🔙 Назад к купонам"
    assert list_keyboard.inline_keyboard[-1][0].callback_data == GuestMenuAction.COUPONS.value

    assert len(card_keyboard.inline_keyboard) == 1
    assert len(card_keyboard.inline_keyboard[0]) == 1
    assert card_keyboard.inline_keyboard[0][0].text == "🔙 Назад к купонам"
    assert card_keyboard.inline_keyboard[0][0].callback_data == GuestMenuAction.COUPONS.value


def test_build_profile_notifications_toggle_keyboard_has_single_toggle_button() -> None:
    """Проверяет отдельное подменю уведомлений с одной кнопкой переключения."""

    active_keyboard = build_profile_notifications_toggle_inline_keyboard(notifications_allowed=True)
    declined_keyboard = build_profile_notifications_toggle_inline_keyboard(notifications_allowed=False)

    assert len(active_keyboard.inline_keyboard) == 2
    assert len(active_keyboard.inline_keyboard[0]) == 1
    assert active_keyboard.inline_keyboard[0][0].text == "❌ Выключить уведомления"
    assert active_keyboard.inline_keyboard[0][0].callback_data == GuestMenuAction.PROFILE_NOTIFICATIONS_TOGGLE.value
    assert len(active_keyboard.inline_keyboard[1]) == 1
    assert active_keyboard.inline_keyboard[1][0].text == BUTTON_PROFILE_EDIT_CANCEL
    assert active_keyboard.inline_keyboard[1][0].callback_data == GuestMenuAction.PROFILE_EDIT_CANCEL.value

    assert len(declined_keyboard.inline_keyboard) == 2
    assert len(declined_keyboard.inline_keyboard[0]) == 1
    assert declined_keyboard.inline_keyboard[0][0].text == "✅ Включить уведомления"
    assert declined_keyboard.inline_keyboard[0][0].callback_data == GuestMenuAction.PROFILE_NOTIFICATIONS_TOGGLE.value
    assert len(declined_keyboard.inline_keyboard[1]) == 1
    assert declined_keyboard.inline_keyboard[1][0].text == BUTTON_PROFILE_EDIT_CANCEL
    assert declined_keyboard.inline_keyboard[1][0].callback_data == GuestMenuAction.PROFILE_EDIT_CANCEL.value


def test_build_profile_edit_cancel_keyboard_contains_profile_back_button() -> None:
    """Проверяет отдельную inline-клавиатуру для текстовых шагов редактирования профиля."""

    keyboard = build_profile_edit_cancel_inline_keyboard()

    assert len(keyboard.inline_keyboard) == 1
    assert len(keyboard.inline_keyboard[0]) == 1
    button = keyboard.inline_keyboard[0][0]
    assert button.text == BUTTON_PROFILE_EDIT_CANCEL
    assert button.callback_data == GuestMenuAction.PROFILE_EDIT_CANCEL.value


def test_build_guest_message_close_keyboard_contains_close_callback() -> None:
    """Проверяет inline-кнопку закрытия входящего сообщения от модератора."""

    keyboard = build_guest_message_close_inline_keyboard()

    assert len(keyboard.inline_keyboard) == 1
    assert len(keyboard.inline_keyboard[0]) == 1
    button = keyboard.inline_keyboard[0][0]
    assert button.text == "❌ Закрыть"
    assert button.callback_data == GUEST_MESSAGE_CLOSE_CALLBACK


def test_build_user_tickets_pagination_keyboard() -> None:
    """Проверяет формирование клавиатуры пагинации тикетов."""
    from uuid import uuid4
    from datetime import datetime, timezone
    from vtelemax.core import PersonSupportTicketSummary, SupportTicketStatus

    # Создаем 6 тикетов
    tickets = tuple(
        PersonSupportTicketSummary(
            ticket_id=uuid4(),
            status=SupportTicketStatus.OPEN,
            source_platform="telegram",
            last_guest_platform="telegram",
            created_at=datetime(2025, 1, i + 1, tzinfo=timezone.utc),
        )
        for i in range(6)
    )

    # Страница 1, всего страниц 2 (per_page=5)
    keyboard = build_user_tickets_pagination_keyboard(
        current_page=1,
        total_pages=2,
        tickets=tickets[:5],  # первые 5 тикетов
        has_tickets=True,
    )

    inline_keyboard = keyboard.inline_keyboard
    # Ожидаем: 5 строк тикетов + строка создания нового тикета + строка навигации + строка назад
    # Но навигация добавляется только если total_pages > 1, и если текущая страница не первая/последняя?
    # В логике: навигационные кнопки добавляются, если total_pages > 1.
    # Для страницы 1 из 2: кнопка "Вперед" и номер страницы, кнопка "Назад" не добавляется.
    # Проверим общее количество строк.
    # 5 тикетов + 1 создание + 1 навигация + 1 назад = 8 строк? Но навигация - это одна строка с кнопками.
    # Посчитаем.
    # Тикеты: 5 строк
    ticket_rows = inline_keyboard[:5]
    # Следующая строка - создание нового тикета
    create_row = inline_keyboard[5]
    # Следующая строка - навигация
    nav_row = inline_keyboard[6]
    # Последняя строка - назад
    back_row = inline_keyboard[7]

    assert len(inline_keyboard) == 8

    # Проверяем кнопки тикетов
    for i, row in enumerate(ticket_rows):
        assert len(row) == 1
        button = row[0]
        assert button.text.startswith("🆕 #")
        assert button.callback_data.startswith(USER_TICKET_DETAILS_PREFIX)

    # Проверяем кнопку создания нового тикета
    assert len(create_row) == 1
    assert create_row[0].text == "📝 Создать новый тикет"
    assert create_row[0].callback_data == "support_question_from_list"

    # Проверяем навигацию: должна быть кнопка номера страницы и "Вперед"
    assert len(nav_row) == 2  # номер страницы и вперед
    assert nav_row[0].text == "1/2"
    assert nav_row[0].callback_data == "noop"
    assert nav_row[1].text == "Вперед ▶️"
    assert nav_row[1].callback_data.startswith(USER_TICKETS_NEXT_PAGE_PREFIX)

    # Проверяем кнопку назад в главное меню
    assert len(back_row) == 1
    assert back_row[0].text == "🔙 Назад в меню"
    assert back_row[0].callback_data == "back_to_main"

    # Тест для случая без тикетов
    keyboard_empty = build_user_tickets_pagination_keyboard(
        current_page=1,
        total_pages=1,
        tickets=(),
        has_tickets=False,
    )
    # Должна быть только кнопка назад (и возможно создание нового тикета? Нет, has_tickets=False)
    # В логике: если has_tickets=False, кнопка создания не добавляется.
    # Навигация не добавляется (total_pages = 1).
    # Ожидаем одну строку - назад.
    assert len(keyboard_empty.inline_keyboard) == 1
    assert keyboard_empty.inline_keyboard[0][0].text == "🔙 Назад в меню"


def test_build_moderation_keyboards_use_expected_callback_prefixes() -> None:
    """Проверяет префиксы callback-data для экрана модерации."""
    from datetime import datetime, timezone
    from uuid import uuid4

    ticket_id = uuid4()
    tickets = (
        OpenSupportTicketSummary(
            ticket_id=ticket_id,
            status=SupportTicketStatus.OPEN,
            source_platform="telegram",
            last_guest_platform="telegram",
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        ),
    )
    tickets_keyboard = build_moderation_tickets_inline_keyboard(
        filter_key="new",
        current_page=2,
        total_pages=4,
        tickets=tickets,
    )
    main_keyboard = build_moderation_main_inline_keyboard()
    details_keyboard = build_moderation_ticket_details_inline_keyboard(
        ticket_id=str(ticket_id),
        filter_key="new",
        page=2,
        status_value="open",
    )

    callbacks = [
        button.callback_data
        for row in main_keyboard.inline_keyboard + tickets_keyboard.inline_keyboard + details_keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]
    assert any(data.startswith(MOD_LIST_PREFIX) for data in callbacks)
    assert any(data.startswith(MOD_PAGE_PREFIX) for data in callbacks)
    assert any(data.startswith(MOD_TICKET_PREFIX) for data in callbacks)
    assert any(data.startswith(MOD_REPLY_PREFIX) for data in callbacks)
    assert any(data.startswith(MOD_CLOSE_PREFIX) for data in callbacks)
    assert any(data.startswith(MOD_PHONE_SHOW_PREFIX) for data in callbacks)
    assert not any(data.startswith(MOD_OPEN_PREFIX) for data in callbacks)

    closed_details_keyboard = build_moderation_ticket_details_inline_keyboard(
        ticket_id=str(ticket_id),
        filter_key="new",
        page=2,
        status_value="closed",
    )
    closed_callbacks = [
        button.callback_data
        for row in closed_details_keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]
    assert any(data.startswith(MOD_OPEN_PREFIX) for data in closed_callbacks)
    assert any(data.startswith(MOD_PHONE_SHOW_PREFIX) for data in closed_callbacks)

    visible_phone_keyboard = build_moderation_ticket_details_inline_keyboard(
        ticket_id=str(ticket_id),
        filter_key="new",
        page=2,
        status_value="open",
        show_phone=True,
    )
    visible_phone_callbacks = [
        button.callback_data
        for row in visible_phone_keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]
    assert any(data.startswith(MOD_PHONE_HIDE_PREFIX) for data in visible_phone_callbacks)


def test_build_moderation_notification_keyboard_has_reply_and_phone_toggle() -> None:
    """Проверяет кнопки в уведомлении модератора: быстрый ответ и показ телефона."""
    from uuid import uuid4

    ticket_id = str(uuid4())
    keyboard = build_moderation_notification_inline_keyboard(ticket_id)

    assert len(keyboard.inline_keyboard) == 2
    reply_button = keyboard.inline_keyboard[0][0]
    phone_button = keyboard.inline_keyboard[1][0]

    assert reply_button.text == "✍️ Ответить"
    assert reply_button.callback_data == f"{MOD_REPLY_PREFIX}{ticket_id}_new_1"
    assert phone_button.text == "📞 Телефон гостя"
    assert phone_button.callback_data == f"{MOD_PHONE_SHOW_PREFIX}{ticket_id}_new_1"


def test_build_coupon_delivery_keyboard_opens_coupons_menu() -> None:
    """Проверяет кнопку перехода из рассылки купона в меню купонов."""

    keyboard = build_coupon_delivery_inline_keyboard()
    button = keyboard.inline_keyboard[0][0]

    assert button.text == "🎟️ Перейти к купонам"
    assert button.callback_data == GuestMenuAction.COUPONS.value
