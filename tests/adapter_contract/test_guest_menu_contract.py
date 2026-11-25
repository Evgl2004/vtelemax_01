"""Contract tests for aligned menu behavior across Telegram, VK and MAX adapters."""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import partial
from importlib import import_module
from types import SimpleNamespace, TracebackType
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup, EditMessageText, SendMessage
from aiogram.types import Message, ReplyKeyboardRemove, Update
from maxapi import Router as MaxRouter
from maxapi.types.attachments.attachment import Attachment
from vkbottle.bot import BotLabeler
from vkbottle_types.events import GroupEventType

from vtelemax.adapters.max import MaxButton, MaxGuestMenuAdapter, MaxIdentityAdapter
from vtelemax.adapters.max.router import register_max_guest_handlers
from vtelemax.adapters.telegram import TelegramIdentityAdapter
from vtelemax.adapters.telegram.menu import build_notifications_consent_inline_keyboard
from vtelemax.adapters.telegram.router import build_telegram_identity_router
from vtelemax.adapters.vk import VkButton, VkGuestMenuAdapter, VkIdentityAdapter
from vtelemax.adapters.vk.router import register_vk_guest_handlers
from vtelemax.core import (
    GetPersonByAccountTransactionalUseCase,
    GuestMenuAction,
    IdentityRepository,
    IdentityUnitOfWork,
    InMemoryIdentityRepository,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
    build_main_menu_screen,
    build_start_rules_screen,
    build_support_menu_screen,
)
from vtelemax.core.guest_content import BUTTON_NOTIFICATIONS_NO, BUTTON_NOTIFICATIONS_YES
from vtelemax.core.loyalty_ports import LoyaltyGateway


class InMemoryIdentityUnitOfWork(IdentityUnitOfWork):
    """Test UnitOfWork over in-memory repository."""

    def __init__(self, repository: IdentityRepository) -> None:
        self.identity_repository = repository

    def __enter__(self) -> "InMemoryIdentityUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return

    def commit(self) -> None:
        return

    def rollback(self) -> None:
        return


def _build_adapters() -> tuple[TelegramIdentityAdapter, VkIdentityAdapter, MaxIdentityAdapter]:
    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    return (
        TelegramIdentityAdapter(registration_use_case, lookup_use_case),
        VkIdentityAdapter(registration_use_case, lookup_use_case),
        MaxIdentityAdapter(registration_use_case, lookup_use_case),
    )


def _flatten_rows(rows: tuple[tuple[object, ...], ...]) -> list[object]:
    return [button for row in rows for button in row]


def _complete_cross_platform_registration(
    telegram: TelegramIdentityAdapter,
    vk: VkIdentityAdapter,
    max_adapter: MaxIdentityAdapter,
) -> None:
    telegram.register_contact(telegram_user_id=1001, raw_phone="+79123456789")

    vk.handle_start(vk_user_id=2002)
    vk.handle_incoming(vk_user_id=2002, text="", payload={"cmd": GuestMenuAction.ACCEPT_RULES.value})
    vk.handle_incoming(vk_user_id=2002, text="+79123456789", payload=None)
    vk.handle_incoming(vk_user_id=2002, text="Ivan", payload=None)
    vk.handle_incoming(vk_user_id=2002, text="", payload={"cmd": GuestMenuAction.NOTIFY_YES.value})

    max_adapter.handle_start(max_user_id=3003)
    max_adapter.handle_incoming(max_user_id=3003, text="", payload=GuestMenuAction.ACCEPT_RULES.value)
    max_adapter.handle_incoming(max_user_id=3003, text="", payload=None, contact_phone="+79123456789")
    max_adapter.handle_incoming(max_user_id=3003, text="Ivan", payload=None)
    max_adapter.handle_incoming(max_user_id=3003, text="", payload=GuestMenuAction.NOTIFY_YES.value)


def test_main_menu_labels_are_identical_between_core_vk_max() -> None:
    """Main menu labels should stay aligned across core/VK/MAX."""

    core_labels = [button.label for button in build_main_menu_screen().buttons]

    vk_screen = VkGuestMenuAdapter().build_main_menu_screen(user_name="Guest")
    max_screen = MaxGuestMenuAdapter().build_main_menu_screen(user_name="Guest")
    vk_labels = [button.label for button in _flatten_rows(vk_screen.rows)]
    max_labels = [button.label for button in _flatten_rows(max_screen.rows)]

    # VK и MAX могут группировать строки платформенно (в рамках UX/ограничений SDK).
    # Контракт здесь — паритет доступных пунктов меню, а не строгий порядок.
    assert Counter(vk_labels) == Counter(core_labels)
    assert Counter(max_labels) == Counter(core_labels)


def test_support_menu_labels_are_identical_without_tickets() -> None:
    """Support menu labels should stay aligned when user has no tickets."""

    core_labels = [button.label for button in build_support_menu_screen(has_tickets=False).buttons]

    vk_screen = VkGuestMenuAdapter().build_support_menu_screen(has_tickets=False)
    max_screen = MaxGuestMenuAdapter().build_support_menu_screen(has_tickets=False)
    vk_labels = [button.label for button in _flatten_rows(vk_screen.rows)]
    max_labels = [button.label for button in _flatten_rows(max_screen.rows)]

    assert vk_labels == core_labels
    assert max_labels == core_labels


def test_profile_phone_is_consistent_for_telegram_vk_max() -> None:
    """All adapters should expose the same registered phone in profile view."""

    telegram, vk, max_adapter = _build_adapters()
    _complete_cross_platform_registration(telegram, vk, max_adapter)

    telegram_profile = telegram.handle_menu_action(telegram_user_id=1001, action_text="👤 Профиль")
    vk_profile = vk.handle_incoming(vk_user_id=2002, text="", payload={"cmd": GuestMenuAction.PROFILE.value})
    max_profile = max_adapter.handle_incoming(
        max_user_id=3003, text="", payload=GuestMenuAction.PROFILE.value
    )

    assert telegram_profile.status == "profile"
    assert vk_profile.screen is not None and vk_profile.screen.screen_id == "profile"
    assert max_profile.screen is not None and max_profile.screen.screen_id == "profile"
    assert "+79123456789" in telegram_profile.message
    assert "+79123456789" in vk_profile.text
    assert "+79123456789" in max_profile.text


def test_unknown_action_is_reported_consistently_for_registered_users() -> None:
    """Unknown action should keep users in a safe menu state on each platform."""

    telegram, vk, max_adapter = _build_adapters()
    _complete_cross_platform_registration(telegram, vk, max_adapter)

    telegram_result = telegram.handle_menu_action(telegram_user_id=1001, action_text="random_unknown_command")
    vk_result = vk.handle_incoming(vk_user_id=2002, text="random_unknown_command", payload=None)
    max_result = max_adapter.handle_incoming(max_user_id=3003, text="random_unknown_command", payload=None)

    assert telegram_result.status == "unknown_action"
    assert vk_result.screen is not None and vk_result.screen.screen_id == "main_menu"
    assert max_result.screen is not None and max_result.screen.screen_id == "main_menu"


def test_rules_screen_has_expected_inline_buttons() -> None:
    """Экран согласия сохраняет документы платформы и предлагает полные правила для чтения."""

    vk_adapter = VkGuestMenuAdapter()
    max_adapter = MaxGuestMenuAdapter()
    core_screen = build_start_rules_screen()

    vk_screen = vk_adapter.build_start_rules_screen()
    max_screen = max_adapter.build_start_rules_screen()

    assert len(core_screen.buttons) == 4
    assert "Правила программы лояльности" in core_screen.text
    assert "даёшь согласие на обработку персональных данных" in core_screen.text
    assert "подтверждаешь согласие с политикой конфиденциальности" in core_screen.text
    assert core_screen.buttons[2].action == GuestMenuAction.OPEN_DOCS
    assert core_screen.buttons[2].label == "📘 Правила лояльности"
    assert core_screen.buttons[2].url == "https://sagur.24vds.ru/loyalty-rules/"
    assert core_screen.buttons[3].action == GuestMenuAction.ACCEPT_RULES
    assert len(vk_screen.rows) == len(core_screen.buttons)
    assert len(max_screen.rows) == len(core_screen.buttons)

    for index, core_button in enumerate(core_screen.buttons):
        vk_button = vk_screen.rows[index][0]
        assert isinstance(vk_button, VkButton)
        assert vk_button.label == core_button.label
        assert vk_button.payload.get("cmd") == core_button.action.value
        if index == len(core_screen.buttons) - 1:
            assert vk_button.url is None
        else:
            assert vk_button.url == (
                "https://sagur.24vds.ru/personal-data-consent/vk/",
                "https://sagur.24vds.ru/privacy-policy/vk/",
                "https://sagur.24vds.ru/loyalty-rules/",
            )[index]

    for index, core_button in enumerate(core_screen.buttons):
        max_button = max_screen.rows[index][0]
        assert isinstance(max_button, MaxButton)
        assert max_button.label == core_button.label
        assert max_button.payload == core_button.action.value
        if index == len(core_screen.buttons) - 1:
            assert max_button.url is None
        else:
            assert max_button.url == (
                "https://sagur.24vds.ru/personal-data-consent/max/",
                "https://sagur.24vds.ru/privacy-policy/max/",
                "https://sagur.24vds.ru/loyalty-rules/",
            )[index]


def test_contact_screen_buttons_are_platform_specific() -> None:
    """VK keeps manual input, MAX keeps request_contact button."""

    vk_adapter = VkGuestMenuAdapter()
    max_adapter = MaxGuestMenuAdapter()

    vk_screen = vk_adapter.build_start_contact_screen()
    max_screen = max_adapter.build_start_contact_screen()

    assert vk_screen.rows == ()
    assert len(max_screen.rows) == 1
    assert isinstance(max_screen.rows[0][0], MaxButton)
    assert max_screen.rows[0][0].request_contact is True
    assert max_screen.rows[0][0].payload == GuestMenuAction.SHARE_CONTACT.value


def test_callback_buttons_have_no_url_or_request_contact() -> None:
    """Main menu buttons should match URL/request_contact contract from core."""

    vk_adapter = VkGuestMenuAdapter()
    max_adapter = MaxGuestMenuAdapter()
    core_screen = build_main_menu_screen()
    expected_url_by_label = {button.label: button.url for button in core_screen.buttons}

    vk_screen = vk_adapter.build_main_menu_screen()
    max_screen = max_adapter.build_main_menu_screen()

    for vk_button in _flatten_rows(vk_screen.rows):
        assert vk_button.url == expected_url_by_label[vk_button.label]

    for max_button in _flatten_rows(max_screen.rows):
        assert max_button.url == expected_url_by_label[max_button.label]
        assert max_button.request_contact is False


def test_onboarding_flow_transitions() -> None:
    """Onboarding transitions should keep expected screen order."""

    _, vk, max_adapter = _build_adapters()

    vk_start = vk.handle_start(vk_user_id=2002)
    assert vk_start.screen is not None
    assert vk_start.screen.screen_id == "start_rules"
    max_start = max_adapter.handle_start(max_user_id=3003)
    assert max_start.screen is not None
    assert max_start.screen.screen_id == "start_rules"

    vk_accept = vk.handle_incoming(
        vk_user_id=2002,
        text="",
        payload={"cmd": GuestMenuAction.ACCEPT_RULES.value},
    )
    assert vk_accept.screen is not None
    assert vk_accept.screen.screen_id == "start_contact"
    max_accept = max_adapter.handle_incoming(
        max_user_id=3003,
        text="",
        payload=GuestMenuAction.ACCEPT_RULES.value,
    )
    assert max_accept.screen is not None
    assert max_accept.screen.screen_id == "start_contact"

    vk_phone = vk.handle_incoming(vk_user_id=2002, text="+79123456789", payload=None)
    assert vk_phone.screen is None
    assert "имя" in vk_phone.text.lower()
    max_phone = max_adapter.handle_incoming(max_user_id=3003, text="", payload=None, contact_phone="+79123456789")
    assert max_phone.screen is None
    assert "имя" in max_phone.text.lower()

    vk_name = vk.handle_incoming(vk_user_id=2002, text="Ivan", payload=None)
    assert vk_name.screen is not None
    assert vk_name.screen.screen_id == "notifications_consent"
    max_name = max_adapter.handle_incoming(max_user_id=3003, text="Ivan", payload=None)
    assert max_name.screen is not None
    assert max_name.screen.screen_id == "notifications_consent"

    vk_notify = vk.handle_incoming(
        vk_user_id=2002,
        text="",
        payload={"cmd": GuestMenuAction.NOTIFY_YES.value},
    )
    assert vk_notify.screen is not None
    assert vk_notify.screen.screen_id == "main_menu"
    max_notify = max_adapter.handle_incoming(
        max_user_id=3003,
        text="",
        payload=GuestMenuAction.NOTIFY_YES.value,
    )
    assert max_notify.screen is not None
    assert max_notify.screen.screen_id == "main_menu"


def test_invalid_phone_returns_error() -> None:
    """Invalid phone should keep user on contact step and return validation error."""

    _, vk, max_adapter = _build_adapters()

    vk.handle_start(vk_user_id=2002)
    vk.handle_incoming(vk_user_id=2002, text="", payload={"cmd": GuestMenuAction.ACCEPT_RULES.value})
    max_adapter.handle_start(max_user_id=3003)
    max_adapter.handle_incoming(max_user_id=3003, text="", payload=GuestMenuAction.ACCEPT_RULES.value)

    vk_response = vk.handle_incoming(vk_user_id=2002, text="abc", payload=None)
    max_response = max_adapter.handle_incoming(max_user_id=3003, text="abc", payload=None)

    assert vk_response.screen is not None
    assert vk_response.screen.screen_id == "start_contact"
    assert max_response.screen is not None
    assert max_response.screen.screen_id == "start_contact"
    assert "+79991234567" in vk_response.text
    assert "Поделиться контактом" in max_response.text


_RULES_LABEL = "📘 Правила лояльности"
_FULL_RULES_URL = "https://sagur.24vds.ru/loyalty-rules/"
_SHORT_RULES_URL = "https://sagur.24vds.ru/loyalty-rules/short/"
_NEW_GUEST_ID = 1001
_REGISTERED_GUEST_ID = 2002
_TEST_PHONE = "+79120000001"
_CONSENT_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)
_VK_MINIAPP_URL = "https://example.org/vk-miniapp"
_PROFILE_ROUND_TRIP = (
    ("back_to_main", False),
    ("profile", True),
    ("profile_edit", False),
    ("profile_edit_first_name", False),
    ("profile_edit_cancel", True),
    ("vacancies", False),
    ("profile", True),
)


@pytest.fixture
def loyalty_screen_dependencies():
    """Гость с сохранёнными согласиями и наблюдение за записями и интеграциями."""

    repository = InMemoryIdentityRepository()
    unit_of_work = InMemoryIdentityUnitOfWork(repository)
    unit_of_work.commit = Mock()
    registration = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=lambda: unit_of_work)
    lookup = GetPersonByAccountTransactionalUseCase(unit_of_work_factory=lambda: unit_of_work)
    integrations = {
        "loyalty_gateway": Mock(spec=LoyaltyGateway),
        "enqueue_profile_sync_use_case": Mock(),
        "sagur_registration_finalization_service": Mock(),
    }
    profiles = {}

    def seed_profile(platform, notifications_allowed, *, registered=True):
        registration.execute(
            RegisterOrAttachAccountCommand(
                platform=platform,
                external_id=str(_REGISTERED_GUEST_ID),
                raw_phone=_TEST_PHONE,
                first_name_input="Ирина",
                rules_accepted=True,
                rules_accepted_at=_CONSENT_AT,
                notifications_allowed=notifications_allowed,
                notifications_allowed_at=_CONSENT_AT if registered else None,
                is_registered=registered,
            )
        )
        profiles[platform] = deepcopy(repository.get_person_by_account(platform, str(_REGISTERED_GUEST_ID)))
        unit_of_work.commit.reset_mock()

    yield registration, lookup, integrations, seed_profile

    unit_of_work.commit.assert_not_called()
    for platform, original in profiles.items():
        assert repository.get_person_by_account(platform, str(_REGISTERED_GUEST_ID)) == original
        assert repository.get_person_by_account(platform, str(_NEW_GUEST_ID)) is None
    for integration in integrations.values():
        assert integration.mock_calls == []


def _registration_rows(platform_suffix, link_type, callback_type, accept_action):
    return [
        [("📄 Согласие на ПД", link_type, f"https://sagur.24vds.ru/personal-data-consent/{platform_suffix}/")],
        [("📄 Политика конфиденциальности", link_type, f"https://sagur.24vds.ru/privacy-policy/{platform_suffix}/")],
        [(_RULES_LABEL, link_type, _FULL_RULES_URL)],
        [("✅ Согласен", callback_type, accept_action)],
    ]


def _profile_rows(notifications_allowed, link_type, callback_type, *, miniapp_action=None):
    rules_row = [(_RULES_LABEL, link_type, _SHORT_RULES_URL)]
    vacancies_row = [("💼 Вакансии", callback_type, "vacancies")]
    document_rows = (
        [rules_row + vacancies_row] if miniapp_action is not None and not notifications_allowed
        else [rules_row, vacancies_row]
    )
    rows = []
    if not notifications_allowed:
        rows.append([("✅ Получать уведомления!", callback_type, "profile_notifications_enable")])
    rows.extend([
        [("✏️ Редактировать профиль", callback_type, "profile_edit")],
        *document_rows,
        [("🔙 Назад в меню", callback_type, "back_to_main")],
    ])
    if miniapp_action is not None:
        rows.extend([
            [("🛡️ Подтвердить номер", link_type, miniapp_action)],
            [("✅ Я подтвердил номер", callback_type, "vk_phone_verification_check")],
        ])
    return rows


def _assert_registration_text(text):
    assert "Правила программы лояльности" in text
    assert "даёшь согласие на обработку персональных данных" in text
    assert "подтверждаешь согласие с политикой конфиденциальности" in text
    assert "подтвердите согласие с правилами" not in text


def _assert_profile_round_trip(rows, expected_profile, shows_profile):
    if shows_profile:
        assert rows == expected_profile
    else:
        assert not any(value in {_FULL_RULES_URL, _SHORT_RULES_URL} for row in rows for _, _, value in row)


def _telegram_rows(markup):
    rows = []
    for row in markup.inline_keyboard:
        buttons = []
        for button in row:
            if button.url is not None:
                assert button.callback_data is None
                buttons.append((button.text, "url", button.url))
            else:
                buttons.append((button.text, "callback_data", button.callback_data))
        rows.append(buttons)
    return rows


@pytest.mark.parametrize("notifications_allowed", [False, True])
@pytest.mark.asyncio
async def test_telegram_loyalty_rules_in_outgoing_keyboards(
    loyalty_screen_dependencies, notifications_allowed, monkeypatch
) -> None:
    """Команда и событие профиля проходят через диспетчер aiogram до конечной разметки."""

    registration, lookup, integrations, seed_profile = loyalty_screen_dependencies
    seed_profile("telegram", notifications_allowed)
    adapter = TelegramIdentityAdapter(registration, lookup, **integrations)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_telegram_identity_router(adapter))
    bot = Bot(token="999999:TEST")

    def user(user_id):
        return {"id": user_id, "is_bot": user_id == bot.id, "first_name": "Гость"}

    def message(chat_id, text, *, from_id, message_id=10):
        return {
            "message_id": message_id,
            "date": int(_CONSENT_AT.timestamp()),
            "chat": {"id": chat_id, "type": "private"},
            "from": user(from_id),
            "text": text,
        }

    async def respond_to_request(bot, method, timeout=None):
        if isinstance(method, SendMessage):
            return Message.model_validate(
                message(method.chat_id, method.text, from_id=bot.id, message_id=20),
                context={"bot": bot},
            )
        assert isinstance(method, (EditMessageReplyMarkup, EditMessageText, AnswerCallbackQuery))
        return True

    transport = AsyncMock(side_effect=respond_to_request)
    monkeypatch.setattr(bot.session, "make_request", transport)

    async def feed(update_id, **event):
        transport.reset_mock()
        await dispatcher.feed_update(bot, Update.model_validate({"update_id": update_id, **event}))
        return [call.args[1] for call in transport.await_args_list]

    start = message(_NEW_GUEST_ID, "/start", from_id=_NEW_GUEST_ID)
    start["entities"] = [{"type": "bot_command", "offset": 0, "length": 6}]
    expected = _registration_rows("tg", "url", "callback_data", "rules_accept")
    for update_id, incoming in enumerate(
        [start, message(_NEW_GUEST_ID, "не согласен", from_id=_NEW_GUEST_ID), start], start=1
    ):
        sent, edited = await feed(update_id, message=incoming)
        assert isinstance(sent, SendMessage) and isinstance(sent.reply_markup, ReplyKeyboardRemove)
        assert isinstance(edited, EditMessageReplyMarkup) and edited.message_id == 20
        assert _telegram_rows(edited.reply_markup) == expected
        if incoming is start:
            _assert_registration_text(sent.text)
        else:
            assert "документами о персональных данных" in sent.text

    expected_profile = _profile_rows(notifications_allowed, "url", "callback_data")
    for update_id, (action, shows_profile) in enumerate((("profile", True), *_PROFILE_ROUND_TRIP), start=4):
        answered, edited = await feed(update_id, callback_query={
            "id": str(update_id),
            "from": user(_REGISTERED_GUEST_ID),
            "chat_instance": "synthetic",
            "message": message(_REGISTERED_GUEST_ID, "Меню гостя", from_id=bot.id),
            "data": action,
        })
        assert isinstance(answered, AnswerCallbackQuery)
        assert isinstance(edited, EditMessageText)
        if shows_profile:
            assert _TEST_PHONE in edited.text
        _assert_profile_round_trip(_telegram_rows(edited.reply_markup), expected_profile, shows_profile)


def _vk_rows(keyboard):
    rows = []
    for row in json.loads(keyboard)["buttons"]:
        buttons = []
        for button in row:
            action = button["action"]
            if action["type"] == "open_link":
                assert "color" not in button
                value = action["link"]
            else:
                value = json.loads(action["payload"])["cmd"]
            buttons.append((action["label"], action["type"], value))
        rows.append(buttons)
    return rows


@pytest.mark.parametrize(("notifications_allowed", "miniapp_enabled", "edit_fails"), [
    (True, False, False),
    (False, False, False),
    (True, True, False),
    (False, True, False),
    (False, True, True),
])
@pytest.mark.asyncio
async def test_vk_loyalty_rules_in_outgoing_keyboards(
    loyalty_screen_dependencies, notifications_allowed, miniapp_enabled, edit_fails
) -> None:
    """Обработчики ВК передают конечный JSON, в том числе при сбое редактирования."""

    registration, lookup, integrations, seed_profile = loyalty_screen_dependencies
    seed_profile("vk", notifications_allowed)
    adapter = VkIdentityAdapter(
        registration,
        lookup,
        vk_phone_verification_miniapp_enabled=miniapp_enabled,
        vk_phone_verification_miniapp_url=_VK_MINIAPP_URL,
        vk_phone_verification_link_secret="test-secret",
        **integrations,
    )
    labeler = BotLabeler()
    register_vk_guest_handlers(SimpleNamespace(on=labeler), adapter)
    start, incoming = labeler.message_view.handlers
    callback, = labeler.raw_event_view.handlers[GroupEventType.MESSAGE_EVENT]
    message = SimpleNamespace(
        from_id=_NEW_GUEST_ID, text="/start", answer=AsyncMock(), get_payload_json=lambda: None
    )
    expected = _registration_rows("vk", "open_link", "callback", "accept_rules")

    await start.handle(message)
    _assert_registration_text(message.answer.await_args.args[0])
    assert _vk_rows(message.answer.await_args.kwargs["keyboard"]) == expected
    message.text = "не согласен"
    await incoming.handle(message)
    assert "документами о персональных данных" in message.answer.await_args.args[0]
    assert _vk_rows(message.answer.await_args.kwargs["keyboard"]) == expected
    await start.handle(message)
    assert _vk_rows(message.answer.await_args.kwargs["keyboard"]) == expected

    message.from_id = _NEW_GUEST_ID + 1
    await incoming.handle(message)
    _assert_registration_text(message.answer.await_args.args[0])
    assert _vk_rows(message.answer.await_args.kwargs["keyboard"]) == expected

    event = SimpleNamespace(
        user_id=_NEW_GUEST_ID + 2,
        conversation_message_id=10,
        get_payload_json=lambda: {"cmd": "profile"},
        send_empty_answer=AsyncMock(),
        edit_message=AsyncMock(),
        send_message=AsyncMock(),
    )
    await callback.handler.handle(event)
    assert "Раздел доступен после регистрации." in event.edit_message.await_args.kwargs["message"]
    _assert_registration_text(event.edit_message.await_args.kwargs["message"])
    assert _vk_rows(event.edit_message.await_args.kwargs["keyboard"]) == expected

    event.user_id = _REGISTERED_GUEST_ID
    event.edit_message.side_effect = RuntimeError("Редактирование недоступно") if edit_fails else None
    await callback.handler.handle(event)
    output = (event.send_message if edit_fails else event.edit_message).await_args.kwargs
    assert _TEST_PHONE in output["message"]
    rows = _vk_rows(output["keyboard"])
    signed_url = None
    if miniapp_enabled:
        signed_url = rows[-2][0][2]
        assert signed_url.startswith(f"{_VK_MINIAPP_URL}?")
        assert f"uid={_REGISTERED_GUEST_ID}" in signed_url
        assert "sig=" in signed_url
    expected_profile = _profile_rows(notifications_allowed, "open_link", "callback", miniapp_action=signed_url)
    assert rows == expected_profile
    assert len(rows) <= 6
    if edit_fails:
        event.send_message.assert_awaited_once()
        return

    for action, shows_profile in _PROFILE_ROUND_TRIP:
        event.get_payload_json = lambda: {"cmd": action}
        await callback.handler.handle(event)
        rows = _vk_rows(event.edit_message.await_args.kwargs["keyboard"])
        if shows_profile and miniapp_enabled:
            # Подпись зависит от времени формирования каждого сообщения.
            expected_profile = _profile_rows(
                notifications_allowed, "open_link", "callback", miniapp_action=rows[-2][0][2]
            )
        _assert_profile_round_trip(rows, expected_profile, shows_profile)


def _max_rows(attachments):
    attachment, = attachments
    assert isinstance(attachment, Attachment)
    payload = attachment.model_dump(mode="json")
    assert payload["type"] == "inline_keyboard"
    return [
        [(button["text"], button["type"], button.get("url") or button["payload"]) for button in row]
        for row in payload["payload"]["buttons"]
    ]


@pytest.mark.parametrize("notifications_allowed", [False, True])
@pytest.mark.asyncio
async def test_max_loyalty_rules_in_outgoing_keyboards(
    loyalty_screen_dependencies, notifications_allowed
) -> None:
    """Проверяет штатное вложение SDK в сообщениях старта и профиля MAX."""

    registration, lookup, integrations, seed_profile = loyalty_screen_dependencies
    seed_profile("max", notifications_allowed)
    adapter = MaxIdentityAdapter(registration, lookup, **integrations)
    router = MaxRouter()
    register_max_guest_handlers(router, adapter)
    handlers = {handler.update_type: handler.func_event for handler in router.event_handlers}
    start = handlers[router.bot_started.update_type]
    incoming = handlers[router.message_created.update_type]
    callback = handlers[router.message_callback.update_type]
    bot = SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock())
    event = SimpleNamespace(user=SimpleNamespace(user_id=_NEW_GUEST_ID), chat_id=_NEW_GUEST_ID, bot=bot)
    expected = _registration_rows("max", "link", "callback", "accept_rules")

    await start(event)
    _assert_registration_text(bot.send_message.await_args.kwargs["text"])
    assert _max_rows(bot.send_message.await_args.kwargs["attachments"]) == expected
    event.message = SimpleNamespace(body=SimpleNamespace(text="не согласен"))
    await incoming(event)
    assert "документами о персональных данных" in bot.send_message.await_args.kwargs["text"]
    assert _max_rows(bot.send_message.await_args.kwargs["attachments"]) == expected
    await start(event)
    assert _max_rows(bot.send_message.await_args.kwargs["attachments"]) == expected

    event.user.user_id = _NEW_GUEST_ID + 1
    await incoming(event)
    _assert_registration_text(bot.send_message.await_args.kwargs["text"])
    assert _max_rows(bot.send_message.await_args.kwargs["attachments"]) == expected

    event.user.user_id = _NEW_GUEST_ID + 2
    event.message.body.mid = "mid.test"
    event.callback = SimpleNamespace(payload="profile")
    event.answer = AsyncMock()
    await callback(event)
    assert "Раздел доступен после регистрации." in bot.edit_message.await_args.kwargs["text"]
    _assert_registration_text(bot.edit_message.await_args.kwargs["text"])
    assert _max_rows(bot.edit_message.await_args.kwargs["attachments"]) == expected

    event.user.user_id = _REGISTERED_GUEST_ID
    await callback(event)
    edited = bot.edit_message.await_args.kwargs
    assert edited["message_id"] == "mid.test" and _TEST_PHONE in edited["text"]
    expected_profile = _profile_rows(notifications_allowed, "link", "callback")
    assert _max_rows(edited["attachments"]) == expected_profile

    for action, shows_profile in _PROFILE_ROUND_TRIP:
        event.callback.payload = action
        await callback(event)
        rows = _max_rows(bot.edit_message.await_args.kwargs["attachments"])
        _assert_profile_round_trip(rows, expected_profile, shows_profile)


@pytest.mark.parametrize("platform", ["telegram", "vk", "max"])
@pytest.mark.parametrize("notifications_allowed", [False, True])
def test_registration_preserves_first_consent_and_separate_mailing_choice(
    platform, notifications_allowed, monkeypatch
) -> None:
    """Повтор согласия и восстановление регистрации сохраняют отдельный выбор рассылки."""

    repository = InMemoryIdentityRepository()
    unit_of_work = InMemoryIdentityUnitOfWork(repository)
    registration = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=lambda: unit_of_work)
    lookup = GetPersonByAccountTransactionalUseCase(unit_of_work_factory=lambda: unit_of_work)
    if platform == "telegram":
        adapter = TelegramIdentityAdapter(registration, lookup)
        start = partial(adapter.start_interaction, _NEW_GUEST_ID)
        reply = partial(adapter.handle_menu_action, _NEW_GUEST_ID)
        enter_phone = partial(adapter.register_contact, _NEW_GUEST_ID, _TEST_PHONE)
        accept = partial(reply, "✅ Согласен")
        choose_mailing = partial(reply, BUTTON_NOTIFICATIONS_YES if notifications_allowed else BUTTON_NOTIFICATIONS_NO)
    elif platform == "vk":
        adapter = VkIdentityAdapter(registration, lookup)
        start = partial(adapter.handle_start, _NEW_GUEST_ID)
        reply = partial(adapter.handle_incoming, _NEW_GUEST_ID, payload=None)
        enter_phone = partial(reply, _TEST_PHONE)
        accept = partial(adapter.handle_incoming, _NEW_GUEST_ID, "", {"cmd": "accept_rules"})
        choose_mailing = partial(
            adapter.handle_incoming, _NEW_GUEST_ID, "", {"cmd": "notify_yes" if notifications_allowed else "notify_no"}
        )
    else:
        adapter = MaxIdentityAdapter(registration, lookup)
        start = partial(adapter.handle_start, _NEW_GUEST_ID)
        reply = partial(adapter.handle_incoming, _NEW_GUEST_ID, payload=None)
        enter_phone = partial(reply, "", contact_phone=_TEST_PHONE)
        accept = partial(adapter.handle_incoming, _NEW_GUEST_ID, "", "accept_rules")
        choose_mailing = partial(
            adapter.handle_incoming, _NEW_GUEST_ID, "", "notify_yes" if notifications_allowed else "notify_no"
        )

    def text_of(result):
        return result.message if platform == "telegram" else result.text

    consent_clock = Mock(wraps=datetime)
    consent_clock.now.return_value = _CONSENT_AT
    monkeypatch.setattr(import_module(type(adapter).__module__), "datetime", consent_clock)
    _assert_registration_text(text_of(start()))
    first_contact = accept()
    if platform == "telegram":
        assert first_contact.status == "phone_required" and first_contact.requires_contact_keyboard
    else:
        assert first_contact.screen.screen_id == "start_contact"
    # До сохранения телефона штатный старт начинает шаг согласия заново.
    _assert_registration_text(text_of(start()))
    assert repository.get_person_by_account(platform, str(_NEW_GUEST_ID)) is None

    assert text_of(accept()) == text_of(first_contact)
    consent_clock.now.return_value = _CONSENT_AT + timedelta(minutes=1)
    repeated_contact = accept()
    if platform == "telegram":
        assert repeated_contact.status == "phone_required" and repeated_contact.requires_contact_keyboard
    else:
        assert repeated_contact.screen.screen_id == "start_contact"
    assert repository.get_person_by_account(platform, str(_NEW_GUEST_ID)) is None

    assert "имя" in text_of(enter_phone()).lower()
    person = repository.get_person_by_account(platform, str(_NEW_GUEST_ID))
    state = person.get_platform_state(platform)
    assert state.rules_accepted and state.rules_accepted_at == _CONSENT_AT
    assert state.notifications_allowed_at is None
    assert not state.is_registered
    assert "имя" in text_of(start()).lower()

    first_mailing = reply("Ирина")
    # Имя в черновике ещё не сохранено в профиле. Повторный старт возвращает к имени.
    assert "имя" in text_of(start()).lower()
    for result in (first_mailing, reply("Ирина")):
        assert "условиями получения уведомлений" in text_of(result).lower()
        if platform == "telegram":
            assert result.status == "notifications_consent_required"
            assert _telegram_rows(build_notifications_consent_inline_keyboard()) == [
                [("📄 Условия рассылки", "url", "https://sagur.24vds.ru/mailing-consent/tg/")],
                [(BUTTON_NOTIFICATIONS_YES, "callback_data", "notify_yes")],
                [(BUTTON_NOTIFICATIONS_NO, "callback_data", "notify_no")],
            ]
        else:
            assert result.screen.screen_id == "notifications_consent"
            assert [button.url for row in result.screen.rows for button in row if button.url] == [
                f"https://sagur.24vds.ru/mailing-consent/{platform}/"
            ]

    completed = choose_mailing()
    if platform == "telegram":
        assert completed.status == "menu"
    else:
        assert completed.screen.screen_id == "main_menu"
    person = repository.get_person_by_account(platform, str(_NEW_GUEST_ID))
    state = person.get_platform_state(platform)
    assert person.first_name_input == "Ирина"
    assert len(person.accounts) == 1
    assert state.is_registered
    assert state.rules_accepted and state.rules_accepted_at == _CONSENT_AT
    assert state.notifications_allowed is notifications_allowed
    assert state.notifications_allowed_at == _CONSENT_AT + timedelta(minutes=1)

    if not notifications_allowed:
        for minutes, action, expected in (
            (2, "profile_notifications_enable", True),
            (3, "profile_notifications_toggle", False),
        ):
            if not expected:
                reply("profile_edit")
                reply("profile_edit_notifications")
            fixed_at = _CONSENT_AT + timedelta(minutes=minutes)
            consent_clock.now.return_value = fixed_at
            profile = reply(action)
            if platform == "telegram":
                assert profile.status == "profile_edit_notifications_saved"
                assert profile.platform_notifications_allowed is expected
            else:
                assert profile.screen.screen_id == "profile"
                assert [button.url for row in profile.screen.rows for button in row if button.url] == [_SHORT_RULES_URL]

            updated_person = repository.get_person_by_account(platform, str(_NEW_GUEST_ID))
            updated_state = updated_person.get_platform_state(platform)
            assert updated_state.notifications_allowed is expected
            assert updated_state.notifications_allowed_at == fixed_at
            assert updated_state.rules_accepted_at == _CONSENT_AT
            assert updated_state.registered_at == _CONSENT_AT + timedelta(minutes=1)
            assert updated_person.first_name_input == "Ирина"


@pytest.mark.parametrize(("platform", "adapter_type"), [
    ("telegram", TelegramIdentityAdapter),
    ("vk", VkIdentityAdapter),
    ("max", MaxIdentityAdapter),
])
def test_registration_with_saved_name_resumes_at_mailing(platform, adapter_type, loyalty_screen_dependencies) -> None:
    """С сохранёнными именем и согласием можно продолжить с выбора рассылки."""

    registration, lookup, integrations, seed_profile = loyalty_screen_dependencies
    seed_profile(platform, None, registered=False)
    adapter = adapter_type(registration, lookup, **integrations)
    if platform == "telegram":
        result = adapter.start_interaction(_REGISTERED_GUEST_ID)
        assert result.status == "notifications_consent_required"
    else:
        result = adapter.handle_start(_REGISTERED_GUEST_ID)
        assert result.screen.screen_id == "notifications_consent"
        assert [button.url for row in result.screen.rows for button in row if button.url] == [
            f"https://sagur.24vds.ru/mailing-consent/{platform}/"
        ]
