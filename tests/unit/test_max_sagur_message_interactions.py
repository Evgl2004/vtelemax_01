"""Тесты приёма интерактивных сообщений SAGUR в MAX."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from maxapi import Dispatcher, Router
from maxapi.types import CallbackButton
from maxapi.types.attachments.buttons.attachment_button import AttachmentButton
from maxapi.types.updates.message_callback import MessageCallback

from vtelemax.adapters.max.identity_adapter import MaxAdapterResponse
from vtelemax.adapters.max.menu_adapter import MaxButton, MaxScreen
from vtelemax.adapters.max.sagur_message_interactions import (
    MaxSagurInteractionFilter,
    build_max_attachments_without_rating,
    build_max_bot_scope,
    build_max_sagur_interaction_router,
    handle_max_sagur_interaction,
)
from vtelemax.adapters.sagur_message_interactions import SagurMessageInteractionStorageError
from vtelemax.core.sagur_message_interactions import (
    SagurMessageInteractionEvent,
    SagurMessageInteractionInsertResult,
    SagurMessageKeyboardError,
    parse_sagur_button_payload,
)

EVENT_ID = UUID("aaaaaaaa-0000-4000-8000-000000000021")


def _payload(action: str = "l", **overrides: Any) -> str:
    value: dict[str, Any] = {"t": "si", "v": 1, "i": 123456, "a": action}
    value.update(overrides)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _button(action: str, *, intent: str = "default") -> CallbackButton:
    return CallbackButton(text=action.upper(), payload=_payload(action), intent=intent)


def _keyboard(*, navigation_action: str = "m", unsafe: bool = False) -> AttachmentButton:
    rows = [
        [_button("l", intent="positive"), _button("d", intent="negative")],
        [_button(navigation_action)],
    ]
    if unsafe:
        rows.pop()
    return AttachmentButton.model_validate(
        {
            "type": "inline_keyboard",
            "payload": {"buttons": rows},
        }
    )


class _UncopyableKeyboard:
    type = "inline_keyboard"

    def __init__(self) -> None:
        self.payload = SimpleNamespace(
            buttons=[
                [_button("l"), _button("d")],
                [_button("m")],
            ]
        )


class _FakeMessage:
    def __init__(
        self,
        timeline: list[str],
        *,
        attachments: Any = None,
        markup: Any = None,
        edit_error: Exception | None = None,
        with_edit: bool = True,
        chat_id: int | None = 77,
        sender: Any = None,
    ) -> None:
        self.timeline = timeline
        self.body = SimpleNamespace(
            mid="mid.test.000001",
            text="Сообщение MAX",
            attachments=[_keyboard()] if attachments is None else attachments,
            markup=[] if markup is None else markup,
        )
        self.recipient = SimpleNamespace(chat_id=chat_id)
        self.sender = sender
        self.edit_error = edit_error
        self.edits: list[dict[str, Any]] = []
        if with_edit:
            self.edit = self._edit

    async def _edit(self, **kwargs: Any) -> None:
        self.timeline.append("edit_message")
        if self.edit_error is not None:
            raise self.edit_error
        self.edits.append(kwargs)


class _FakeBot:
    def __init__(
        self,
        timeline: list[str],
        *,
        bot_user_id: int | None = 999,
        answer_error: Exception | None = None,
        send_error: Exception | None = None,
    ) -> None:
        self.timeline = timeline
        self.me = SimpleNamespace(user_id=bot_user_id) if bot_user_id is not None else None
        self.answer_error = answer_error
        self.send_error = send_error
        self.callback_calls: list[dict[str, Any]] = []
        self.send_calls: list[dict[str, Any]] = []

    async def send_callback(self, **kwargs: Any) -> None:
        self.timeline.append("answer")
        if self.answer_error is not None:
            raise self.answer_error
        self.callback_calls.append(kwargs)

    async def send_message(self, **kwargs: Any) -> None:
        self.timeline.append("send_message")
        if self.send_error is not None:
            raise self.send_error
        self.send_calls.append(kwargs)


class _FakeEvent:
    def __init__(
        self,
        *,
        payload: str | None = None,
        timeline: list[str] | None = None,
        message: _FakeMessage | None = None,
        bot: _FakeBot | None = None,
        callback_id: str = "max.callback.id.000001",
        user_id: int | None = 101,
    ) -> None:
        self.timeline = timeline if timeline is not None else []
        user = SimpleNamespace(user_id=user_id) if user_id is not None else None
        self.callback = SimpleNamespace(
            callback_id=callback_id,
            payload=payload or _payload(),
            user=user,
        )
        self.message = message or _FakeMessage(self.timeline)
        self.bot = bot or _FakeBot(self.timeline)

    async def answer(self, notification: str = "") -> None:
        self.timeline.append("answer")
        if self.bot.answer_error is not None:
            raise self.bot.answer_error
        self.bot.callback_calls.append({"notification": notification})


@dataclass
class _Service:
    timeline: list[str]
    created: bool = True
    immutable_fields_match: bool = True
    record_error: Exception | None = None
    mark_error: Exception | None = None
    ingress: list[Any] = field(default_factory=list)
    failed_actions: list[dict[str, str]] = field(default_factory=list)

    def record_event(self, ingress: Any) -> SagurMessageInteractionInsertResult:
        self.timeline.append("record_event")
        self.ingress.append(ingress)
        if self.record_error is not None:
            raise self.record_error
        return SagurMessageInteractionInsertResult(
            event=SagurMessageInteractionEvent(
                event_id=EVENT_ID,
                platform=ingress.platform,
                bot_scope=ingress.bot_scope,
                platform_callback_id=ingress.platform_callback_id,
                interaction_id=ingress.interaction_id,
                action=ingress.action,
                occurred_at=datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
                provider_message_id=ingress.provider_message_id,
            ),
            created=self.created,
            immutable_fields_match=self.immutable_fields_match,
        )

    def mark_user_action_succeeded(self, event_id: UUID, *, attempted_at: datetime) -> None:
        self.timeline.append("mark_succeeded")
        if self.mark_error is not None:
            raise self.mark_error

    def mark_user_action_failed(
        self,
        event_id: UUID,
        *,
        attempted_at: datetime,
        error_code: str,
        error_text: str,
    ) -> None:
        self.timeline.append("mark_failed")
        self.failed_actions.append({"error_code": error_code, "error_text": error_text})
        if self.mark_error is not None:
            raise self.mark_error


@dataclass
class _IdentityAdapter:
    timeline: list[str]
    error: Exception | None = None
    parse_mode: str | None = None
    with_keyboard: bool = True
    calls: list[tuple[int, str]] = field(default_factory=list)

    def handle_sagur_navigation(self, user_id: int, action: str) -> MaxAdapterResponse:
        self.timeline.append("navigation")
        self.calls.append((user_id, action))
        if self.error is not None:
            raise self.error
        screen = None
        if self.with_keyboard:
            screen = MaxScreen(
                screen_id="sagur_navigation",
                text="Новый экран MAX",
                rows=((MaxButton(label="Пункт", payload="main_menu"),),),
                parse_mode=self.parse_mode,
            )
        return MaxAdapterResponse(
            text="Новый экран MAX",
            screen=screen,
            parse_mode=self.parse_mode,
        )


def _parsed(action: str = "l") -> Any:
    result = parse_sagur_button_payload(_payload(action))
    assert result is not None
    return result


def _callback_event(payload: str) -> MessageCallback:
    return MessageCallback.model_validate(
        {
            "update_type": "message_callback",
            "timestamp": 1,
            "message": {
                "sender": {
                    "user_id": 999,
                    "first_name": "Бот",
                    "is_bot": True,
                    "last_activity_time": 1,
                },
                "recipient": {
                    "chat_id": 77,
                    "chat_type": "chat",
                },
                "timestamp": 1,
                "body": {
                    "mid": "mid.test.000001",
                    "seq": 1,
                    "text": "Сообщение MAX",
                    "attachments": [_keyboard().model_dump()],
                    "markup": [],
                },
            },
            "callback": {
                "timestamp": 1,
                "callback_id": "max.callback.id.000001",
                "payload": payload,
                "user": {
                    "user_id": 101,
                    "first_name": "Проверка",
                    "is_bot": False,
                    "last_activity_time": 1,
                },
            },
        }
    )


def test_keyboard_removal_preserves_navigation_other_attachments_and_original() -> None:
    unrelated = {"type": "contact", "payload": {"vcf_info": "BEGIN:VCARD"}}
    keyboard = _keyboard()
    navigation = keyboard.payload.buttons[1][0]

    result = build_max_attachments_without_rating(
        [unrelated, keyboard],
        clicked_payload=_parsed(),
    )

    assert result[0] is unrelated
    assert result[1].payload.buttons == [[navigation]]
    assert result[1].payload.buttons[0][0].intent == "default"
    assert len(keyboard.payload.buttons) == 2


def test_keyboard_removal_supports_plain_mapping_from_max_api() -> None:
    """Проверяет безопасное копирование словарного представления MAX."""

    keyboard = _keyboard().model_dump()

    result = build_max_attachments_without_rating([keyboard], clicked_payload=_parsed())

    assert len(result[0]["payload"]["buttons"]) == 1
    assert len(keyboard["payload"]["buttons"]) == 2


@pytest.mark.parametrize(
    "attachments",
    [
        None,
        [],
        [_keyboard(), _keyboard()],
        [_keyboard(unsafe=True)],
        [{"type": "inline_keyboard", "payload": {"buttons": "не-ряды"}}],
        [{"type": "inline_keyboard", "payload": {"buttons": ["не-ряд"]}}],
        [_UncopyableKeyboard()],
    ],
)
def test_keyboard_removal_rejects_unsafe_shapes(attachments: Any) -> None:
    with pytest.raises(SagurMessageKeyboardError):
        build_max_attachments_without_rating(attachments, clicked_payload=_parsed())


def test_keyboard_removal_ignores_foreign_buttons() -> None:
    keyboard = _keyboard()
    keyboard.payload.buttons.insert(
        0,
        [
            {"type": "link", "payload": _payload("l")},
            {"type": "callback", "payload": 123},
        ],
    )

    result = build_max_attachments_without_rating([keyboard], clicked_payload=_parsed())

    assert result[0].payload.buttons[0] == keyboard.payload.buttons[0]


def test_bot_scope_uses_bot_profile_sender_or_username_in_order() -> None:
    event = _FakeEvent()
    assert build_max_bot_scope(event) == "bot_id:999"  # type: ignore[arg-type]

    event.bot.me = None
    event.message.sender = SimpleNamespace(user_id=777, is_bot=True)
    assert build_max_bot_scope(event) == "bot_id:777"  # type: ignore[arg-type]

    event.message.sender = SimpleNamespace(user_id=777, is_bot=False)
    assert build_max_bot_scope(event, configured_username="@Sa_Bal_Bot") == (
        "username:sa_bal_bot"
    )  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="область"):
        build_max_bot_scope(event)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_filter_distinguishes_valid_invalid_foreign_and_wrong_event() -> None:
    interaction_filter = MaxSagurInteractionFilter()
    valid = await interaction_filter(_callback_event(_payload("l")))
    invalid = await interaction_filter(_callback_event(_payload("l", v=3)))
    foreign = await interaction_filter(_callback_event(json.dumps({"t": "other"})))

    assert isinstance(valid, dict) and "sagur_payload" in valid
    assert isinstance(invalid, dict) and "sagur_payload_error" in invalid
    assert foreign is False
    assert await interaction_filter(SimpleNamespace()) is False


@pytest.mark.asyncio
async def test_rating_order_is_record_answer_edit_and_mark() -> None:
    timeline: list[str] = []
    message = _FakeMessage(
        timeline,
        attachments=[{"type": "contact", "payload": {}}, _keyboard()],
    )
    event = _FakeEvent(timeline=timeline, message=message)
    service = _Service(timeline)

    await handle_max_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed("l"),
    )

    assert timeline == ["record_event", "answer", "edit_message", "mark_succeeded"]
    assert message.edits[0]["text"] == "Сообщение MAX"
    assert message.edits[0]["notify"] is False
    assert len(message.edits[0]["attachments"][1].payload.buttons) == 1
    assert service.ingress[0].platform == "max"
    assert service.ingress[0].bot_scope == "bot_id:999"
    assert service.ingress[0].provider_message_id == "mid.test.000001"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "parse_mode", "chat_id"),
    [("m", "markdown", 77), ("c", "html", None), ("m", "неизвестно", 77)],
)
async def test_navigation_sends_new_message_after_answer(
    action: str,
    parse_mode: str,
    chat_id: int | None,
) -> None:
    timeline: list[str] = []
    message = _FakeMessage(timeline, chat_id=chat_id)
    event = _FakeEvent(timeline=timeline, message=message, payload=_payload(action))
    service = _Service(timeline)
    identity = _IdentityAdapter(timeline, parse_mode=parse_mode)

    await handle_max_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=identity,  # type: ignore[arg-type]
        sagur_payload=_parsed(action),
    )

    assert timeline == [
        "record_event",
        "answer",
        "navigation",
        "send_message",
        "mark_succeeded",
    ]
    sent = event.bot.send_calls[0]
    assert identity.calls == [(101, action)]
    assert sent.get("chat_id") == chat_id
    assert sent.get("user_id") == (101 if chat_id is None else None)
    assert sent["attachments"]
    assert ("parse_mode" in sent) is (parse_mode in {"markdown", "html"})


@pytest.mark.asyncio
async def test_navigation_without_screen_sends_no_keyboard_or_parse_mode() -> None:
    timeline: list[str] = []
    event = _FakeEvent(timeline=timeline, payload=_payload("m"))

    await handle_max_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=_Service(timeline),  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline, with_keyboard=False),  # type: ignore[arg-type]
        sagur_payload=_parsed("m"),
    )

    assert set(event.bot.send_calls[0]) == {"chat_id", "text"}


@pytest.mark.asyncio
async def test_invalid_payload_is_answered_without_database_write() -> None:
    timeline: list[str] = []
    event = _FakeEvent(timeline=timeline, payload=_payload("l", v=3))
    service = _Service(timeline)
    error = None
    try:
        parse_sagur_button_payload(event.callback.payload)
    except Exception as caught:  # noqa: BLE001
        error = caught

    await handle_max_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload_error=error,  # type: ignore[arg-type]
    )

    assert service.ingress == []
    assert event.bot.callback_calls == [
        {"notification": "Кнопка содержит некорректные служебные данные."}
    ]


@pytest.mark.asyncio
async def test_database_failure_preserves_keyboard_and_stops_action() -> None:
    timeline: list[str] = []
    message = _FakeMessage(timeline)
    event = _FakeEvent(timeline=timeline, message=message)
    service = _Service(
        timeline,
        record_error=SagurMessageInteractionStorageError("База недоступна"),
    )

    await handle_max_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed(),
    )

    assert timeline == ["record_event", "answer"]
    assert message.edits == []
    assert event.bot.callback_calls[-1]["notification"] == (
        "Не удалось сохранить нажатие. Повторите попытку."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("immutable_fields_match", [True, False])
async def test_duplicate_is_answered_without_repeating_action(
    immutable_fields_match: bool,
) -> None:
    timeline: list[str] = []
    event = _FakeEvent(timeline=timeline)

    await handle_max_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=_Service(
            timeline,
            created=False,
            immutable_fields_match=immutable_fields_match,
        ),  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed(),
    )

    assert timeline == ["record_event", "answer"]
    assert event.message.edits == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        None,
        _FakeMessage([], markup=[{"type": "strong"}]),
        _FakeMessage([], attachments=[_keyboard(unsafe=True)]),
        _FakeMessage([], with_edit=False),
    ],
)
async def test_uneditable_rating_is_recorded_as_failed_action(message: Any) -> None:
    timeline: list[str] = []
    selected_message = message
    if selected_message is not None:
        selected_message.timeline = timeline
    event = _FakeEvent(timeline=timeline, message=selected_message)
    if message is None:
        event.message = None
    service = _Service(timeline)

    await handle_max_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        configured_username="max_bot",
        sagur_payload=_parsed(),
    )

    assert timeline[-1] == "mark_failed"
    assert service.failed_actions


@pytest.mark.asyncio
async def test_answer_failure_does_not_cancel_recorded_action() -> None:
    timeline: list[str] = []
    bot = _FakeBot(timeline, answer_error=RuntimeError("MAX answer failed"))
    event = _FakeEvent(timeline=timeline, bot=bot)

    await handle_max_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=_Service(timeline),  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed(),
    )

    assert timeline == ["record_event", "answer", "edit_message", "mark_succeeded"]


@pytest.mark.asyncio
async def test_missing_answer_method_is_contained_and_action_continues() -> None:
    """Проверяет отсутствие метода подтверждения у нетипичного события MAX."""

    timeline: list[str] = []
    event = _FakeEvent(timeline=timeline)
    event.answer = None  # type: ignore[method-assign]

    await handle_max_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=_Service(timeline),  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed(),
    )

    assert timeline == ["record_event", "edit_message", "mark_succeeded"]


@pytest.mark.asyncio
async def test_navigation_send_failure_and_state_write_failure_are_contained() -> None:
    timeline: list[str] = []
    bot = _FakeBot(timeline, send_error=RuntimeError("MAX send failed"))
    event = _FakeEvent(timeline=timeline, bot=bot, payload=_payload("m"))
    service = _Service(timeline, mark_error=RuntimeError("state write failed"))

    await handle_max_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed("m"),
    )

    assert timeline[-1] == "mark_failed"
    assert service.failed_actions[0]["error_code"] == "RuntimeError"


@pytest.mark.asyncio
async def test_missing_send_method_is_recorded_as_failed_navigation() -> None:
    """Проверяет защиту от неполного объекта бота MAX."""

    timeline: list[str] = []
    event = _FakeEvent(timeline=timeline, payload=_payload("m"))
    event.bot.send_message = None  # type: ignore[method-assign]
    service = _Service(timeline)

    await handle_max_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed("m"),
    )

    assert timeline[-1] == "mark_failed"
    assert service.failed_actions[0]["error_code"] == "ValueError"


@pytest.mark.asyncio
async def test_success_state_write_failure_is_contained() -> None:
    timeline: list[str] = []
    event = _FakeEvent(timeline=timeline)

    await handle_max_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=_Service(timeline, mark_error=RuntimeError("state write failed")),  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed(),
    )

    assert timeline[-1] == "mark_succeeded"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("callback_id", "user_id", "bot_user_id"),
    [("", 101, 999), (None, 101, 999), ("valid", None, 999), ("valid", 101, None)],
)
async def test_missing_ingress_identity_is_reported_as_storage_failure(
    callback_id: str | None,
    user_id: int | None,
    bot_user_id: int | None,
) -> None:
    timeline: list[str] = []
    bot = _FakeBot(timeline, bot_user_id=bot_user_id)
    event = _FakeEvent(
        timeline=timeline,
        bot=bot,
        callback_id=callback_id,  # type: ignore[arg-type]
        user_id=user_id,
    )

    await handle_max_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=_Service(timeline),  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed(),
    )

    assert "edit_message" not in timeline
    assert bot.callback_calls[-1]["notification"] == (
        "Не удалось сохранить нажатие. Повторите попытку."
    )


def test_router_contains_one_filtered_handler() -> None:
    timeline: list[str] = []
    router = build_max_sagur_interaction_router(
        service=_Service(timeline),  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
    )

    assert router.router_id == "max_sagur_message_interactions"
    assert len(router.event_handlers) == 1
    assert isinstance(router.event_handlers[0].base_filters[0], MaxSagurInteractionFilter)


@pytest.mark.asyncio
async def test_dispatcher_stops_on_sagur_and_passes_foreign_callback() -> None:
    timeline: list[str] = []
    dispatcher = Dispatcher()
    sagur_router = build_max_sagur_interaction_router(
        service=_Service(timeline),  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
    )
    fallback_router = Router(router_id="fallback")
    fallback_payloads: list[str | None] = []

    @fallback_router.message_callback()
    async def fallback_handler(event: MessageCallback, context: Any = None) -> None:  # noqa: ARG001
        fallback_payloads.append(event.callback.payload)

    dispatcher.include_routers(sagur_router, fallback_router)

    matching = _callback_event(_payload("m"))
    matching.bot = _FakeBot(timeline)
    await dispatcher.handle(matching)
    assert fallback_payloads == []

    foreign = _callback_event(json.dumps({"t": "other"}))
    foreign.bot = _FakeBot(timeline)
    await dispatcher.handle(foreign)
    assert fallback_payloads == [foreign.callback.payload]
