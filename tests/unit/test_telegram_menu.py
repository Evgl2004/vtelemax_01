"""Тесты Telegram-клавиатур меню."""

from __future__ import annotations

from vtelemax.adapters.telegram.menu import (
    DOCS_URL,
    PERSONAL_DATA_CONSENT_BUTTON_LABEL,
    PRIVACY_POLICY_BUTTON_LABEL,
    PRIVACY_POLICY_URL,
    RULES_ACCEPT_CALLBACK,
    build_contact_request_keyboard,
    build_delivery_inline_keyboard,
    build_iiko_sync_retry_inline_keyboard,
    build_main_menu_inline_keyboard,
    build_profile_edit_inline_keyboard,
    build_profile_gender_inline_keyboard,
    build_rules_consent_inline_keyboard,
    build_support_feedback_inline_keyboard,
    build_support_menu_inline_keyboard,
)
from vtelemax.core import (
    BUTTON_ACCEPT_RULES,
    BUTTON_RETRY_IIKO_SYNC,
    GuestMenuAction,
)


def test_build_rules_consent_keyboard_contains_docs_and_accept_buttons() -> None:
    """Проверяет, что клавиатура правил содержит кнопку документов и кнопку согласия."""

    keyboard = build_rules_consent_inline_keyboard()

    assert keyboard.inline_keyboard
    assert len(keyboard.inline_keyboard) == 3

    docs_row = keyboard.inline_keyboard[0]
    policy_row = keyboard.inline_keyboard[1]
    accept_row = keyboard.inline_keyboard[2]
    assert len(docs_row) == 1
    assert len(policy_row) == 1
    assert len(accept_row) == 1

    docs_button = docs_row[0]
    policy_button = policy_row[0]
    accept_button = accept_row[0]

    assert docs_button.text == PERSONAL_DATA_CONSENT_BUTTON_LABEL
    assert docs_button.url == DOCS_URL
    assert policy_button.text == PRIVACY_POLICY_BUTTON_LABEL
    assert policy_button.url == PRIVACY_POLICY_URL

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
