"""Тесты Telegram-клавиатур меню."""

from __future__ import annotations

from vtelemax.adapters.telegram.menu import (
    DOCS_URL,
    RULES_ACCEPT_CALLBACK,
    USER_TICKETS_PREV_PAGE_PREFIX,
    USER_TICKETS_NEXT_PAGE_PREFIX,
    USER_TICKET_DETAILS_PREFIX,
    build_contact_request_keyboard,
    build_delivery_inline_keyboard,
    build_iiko_sync_retry_inline_keyboard,
    build_main_menu_inline_keyboard,
    build_profile_edit_inline_keyboard,
    build_profile_gender_inline_keyboard,
    build_rules_consent_inline_keyboard,
    build_support_feedback_inline_keyboard,
    build_support_menu_inline_keyboard,
    build_user_tickets_pagination_keyboard,
)
from vtelemax.core import (
    BUTTON_ACCEPT_RULES,
    BUTTON_DOCS_LINK,
    BUTTON_RETRY_IIKO_SYNC,
    GuestMenuAction,
)


def test_build_rules_consent_keyboard_contains_docs_and_accept_buttons() -> None:
    """Проверяет, что клавиатура правил содержит кнопку документов и кнопку согласия."""

    keyboard = build_rules_consent_inline_keyboard()

    assert keyboard.inline_keyboard
    assert len(keyboard.inline_keyboard) == 2

    docs_row = keyboard.inline_keyboard[0]
    accept_row = keyboard.inline_keyboard[1]
    assert len(docs_row) == 1
    assert len(accept_row) == 1

    docs_button = docs_row[0]
    accept_button = accept_row[0]

    assert docs_button.text == BUTTON_DOCS_LINK
    assert docs_button.url == DOCS_URL

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
    """Проверяет клавиатуру экрана «Оставить отзыв»: ссылка и кнопка возврата."""

    keyboard = build_support_feedback_inline_keyboard()

    assert len(keyboard.inline_keyboard) == 2
    link_button = keyboard.inline_keyboard[0][0]
    back_button = keyboard.inline_keyboard[1][0]

    assert link_button.url == "https://rdata.one/Nyyl"
    assert back_button.callback_data == GuestMenuAction.BACK_TO_SUPPORT.value


def test_build_delivery_keyboard_contains_links_and_back_button() -> None:
    """Проверяет, что в подменю «Доставка» есть URL-кнопки и возврат в меню."""

    keyboard = build_delivery_inline_keyboard()

    assert len(keyboard.inline_keyboard) == 5
    first_button = keyboard.inline_keyboard[0][0]
    assert first_button.text == "Грузика Нани"
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


def test_all_telegram_callback_data_fit_telegram_limits() -> None:
    """Проверяет, что callback_data не превышает лимит Telegram (64 байта)."""

    keyboards = [
        build_main_menu_inline_keyboard(),
        build_delivery_inline_keyboard(),
        build_support_menu_inline_keyboard(has_tickets=False),
        build_support_menu_inline_keyboard(has_tickets=True),
        build_support_feedback_inline_keyboard(),
        build_profile_edit_inline_keyboard(can_edit_birth_date=True),
        build_profile_edit_inline_keyboard(can_edit_birth_date=False),
        build_profile_gender_inline_keyboard(),
        build_iiko_sync_retry_inline_keyboard(),
    ]

    for keyboard in keyboards:
        for row in keyboard.inline_keyboard:
            for button in row:
                callback_data = button.callback_data
                if callback_data is None:
                    continue
                assert len(callback_data.encode("utf-8")) <= 64


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
