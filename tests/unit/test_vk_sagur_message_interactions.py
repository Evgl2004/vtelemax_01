"""Тесты приёма интерактивных сообщений SAGUR во ВКонтакте."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from vkbottle.bot import Bot
from vkbottle_types.events import GroupEventType

from vtelemax.adapters.sagur_message_interactions import SagurMessageInteractionStorageError
from vtelemax.adapters.vk.identity_adapter import VkAdapterResponse
from vtelemax.adapters.vk.menu_adapter import VkButton, VkScreen
from vtelemax.adapters.vk.sagur_message_interactions import (
    VkSagurInteractionRule,
    build_vk_attachment_value,
    build_vk_bot_scope,
    build_vk_keyboard_without_rating,
    handle_vk_sagur_interaction,
    register_vk_sagur_message_interactions,
)
from vtelemax.core.sagur_message_interactions import (
    SagurMessageInteractionEvent,
    SagurMessageInteractionInsertResult,
    SagurMessageKeyboardError,
    parse_sagur_button_payload,
)


EVENT_ID = UUID("aaaaaaaa-0000-4000-8000-000000000011")


def _payload(action: str = "l", **overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {"t": "si", "v": 1, "i": 123456, "a": action}
    value.update(overrides)
    return value


def _payload_json(action: str = "l", **overrides: Any) -> str:
    return json.dumps(_payload(action, **overrides), separators=(",", ":"))


def _button(action: str, *, color: str) -> dict[str, Any]:
    return {
        "action": {
            "type": "callback",
            "label": action.upper(),
            "payload": _payload_json(action),
        },
        "color": color,
        "custom": f"preserve-{action}",
    }


def _keyboard(*, unsafe: bool = False) -> dict[str, Any]:
    rows = [
        [_button("l", color="positive"), _button("d", color="negative")],
        [_button("m", color="primary")],
    ]
    if unsafe:
        rows.pop()
    return {
        "one_time": False,
        "inline": True,
        "author_id": -236296391,
        "future_output_field": "не возвращать",
        "buttons": rows,
    }


class _DumpableKeyboard:
    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        return _keyboard()


class _InvalidDumpableKeyboard:
    def model_dump(self, **kwargs: Any) -> list[Any]:
        return []


class _FakeMessages:
    def __init__(self, event: "_FakeEvent", source_message: Any) -> None:
        self.event = event
        self.source_message = source_message
        self.fetch_response: Any = SimpleNamespace(items=[source_message])
        self.fetch_calls: list[dict[str, Any]] = []
        self.send_calls: list[dict[str, Any]] = []

    async def get_by_conversation_message_id(self, **kwargs: Any) -> Any:
        self.event.timeline.append("fetch_message")
        self.fetch_calls.append(kwargs)
        return self.fetch_response

    async def send(self, **kwargs: Any) -> int:
        self.event.timeline.append("send_message")
        if self.event.send_error is not None:
            raise self.event.send_error
        self.send_calls.append(kwargs)
        return 1


class _FakeEvent:
    def __init__(
        self,
        *,
        payload: Any,
        timeline: list[str] | None = None,
        source_message: Any | None = None,
        answer_error: Exception | None = None,
        edit_error: Exception | None = None,
        send_error: Exception | None = None,
        group_id: int | None = 236296391,
    ) -> None:
        self.timeline = timeline if timeline is not None else []
        self.event_id = "vk-event-id-000001"
        self.group_id = group_id
        self.user_id = 101
        self.peer_id = 2000000001
        self.conversation_message_id = 654588
        self._payload = payload
        self.answer_error = answer_error
        self.edit_error = edit_error
        self.send_error = send_error
        self.answers = 0
        self.snackbars: list[str] = []
        self.edits: list[dict[str, Any]] = []
        default_message = SimpleNamespace(
            text="Сообщение VK",
            keyboard=_keyboard(),
            attachments=[],
        )
        self.messages = _FakeMessages(self, source_message or default_message)
        self.ctx_api = SimpleNamespace(messages=self.messages)

    def get_payload_json(self) -> Any:
        return self._payload

    async def send_empty_answer(self) -> None:
        self.timeline.append("answer")
        if self.answer_error is not None:
            raise self.answer_error
        self.answers += 1

    async def show_snackbar(self, text: str) -> None:
        self.timeline.append("snackbar")
        if self.answer_error is not None:
            raise self.answer_error
        self.snackbars.append(text)

    async def edit_message(self, **kwargs: Any) -> None:
        self.timeline.append("edit_message")
        if self.edit_error is not None:
            raise self.edit_error
        self.edits.append(kwargs)


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

    def handle_sagur_navigation(self, user_id: int, action: str) -> VkAdapterResponse:
        self.timeline.append("navigation")
        self.calls.append((user_id, action))
        if self.error is not None:
            raise self.error
        screen = None
        if self.with_keyboard:
            screen = VkScreen(
                screen_id="sagur_navigation",
                text="Новый экран VK",
                rows=((VkButton(label="Пункт", payload={"cmd": "main_menu"}),),),
                parse_mode=self.parse_mode,
            )
        return VkAdapterResponse(
            text="Новый экран VK",
            screen=screen,
            parse_mode=self.parse_mode,
        )


def _parsed(action: str = "l") -> Any:
    result = parse_sagur_button_payload(_payload(action))
    assert result is not None
    return result


@pytest.mark.parametrize("keyboard", [_keyboard(), _DumpableKeyboard()])
def test_keyboard_removal_strips_output_fields_and_preserves_button_objects(keyboard: Any) -> None:
    source = keyboard if isinstance(keyboard, dict) else keyboard.model_dump()
    navigation = source["buttons"][1][0]

    result = build_vk_keyboard_without_rating(keyboard, clicked_payload=_parsed())

    assert set(result) == {"one_time", "inline", "buttons"}
    assert result["buttons"] == [[navigation]]
    assert result["buttons"][0][0]["custom"] == "preserve-m"


@pytest.mark.parametrize(
    "keyboard",
    [
        None,
        {"one_time": False, "inline": False, "buttons": []},
        {"one_time": False, "inline": True, "buttons": "не-ряды"},
        {"one_time": False, "inline": True, "buttons": ["не-ряд"]},
    ],
)
def test_keyboard_removal_rejects_unsafe_vk_shape(keyboard: Any) -> None:
    with pytest.raises(SagurMessageKeyboardError):
        build_vk_keyboard_without_rating(keyboard, clicked_payload=_parsed())


def test_keyboard_removal_rejects_model_with_non_mapping_dump() -> None:
    with pytest.raises(SagurMessageKeyboardError):
        build_vk_keyboard_without_rating(
            _InvalidDumpableKeyboard(),
            clicked_payload=_parsed(),
        )


def test_keyboard_removal_ignores_non_callback_button_payload() -> None:
    keyboard = _keyboard()
    keyboard["buttons"].insert(
        0,
        [
            {"action": {"type": "open_link", "payload": _payload_json("l")}},
            {"action": {"type": "callback", "payload": 123}},
            "не-кнопка",
        ],
    )

    result = build_vk_keyboard_without_rating(keyboard, clicked_payload=_parsed())

    assert result["buttons"][0] == keyboard["buttons"][0]


def test_attachment_builder_preserves_supported_types_order_and_access_key() -> None:
    attachments = [
        {"type": "photo", "photo": {"owner_id": -1, "id": 2, "access_key": "key"}},
        {"type": "wall", "wall": {"from_id": -3, "id": 4}},
    ]

    assert build_vk_attachment_value(attachments) == "photo-1_2_key,wall-3_4"
    assert build_vk_attachment_value(None) is None
    assert build_vk_attachment_value([]) is None


class _AttachmentType:
    value = "doc"


def test_attachment_builder_supports_model_fields_and_enum_type() -> None:
    attachment = SimpleNamespace(
        type=_AttachmentType(),
        doc=SimpleNamespace(owner_id=5, id=6, access_key=""),
    )

    assert build_vk_attachment_value((attachment,)) == "doc5_6"


@pytest.mark.parametrize(
    "attachments",
    [
        "photo1_2",
        [{"type": "sticker", "sticker": {"owner_id": 1, "id": 2}}],
        [{"type": "photo", "photo": {"owner_id": "1", "id": 2}}],
    ],
)
def test_attachment_builder_rejects_unrepresentable_values(attachments: Any) -> None:
    with pytest.raises(SagurMessageKeyboardError):
        build_vk_attachment_value(attachments)


def test_bot_scope_prefers_event_group_and_supports_configured_fallback() -> None:
    event = _FakeEvent(payload=_payload(), group_id=10)
    fallback = _FakeEvent(payload=_payload(), group_id=None)

    assert build_vk_bot_scope(event, configured_group_id=20) == "group_id:10"  # type: ignore[arg-type]
    assert build_vk_bot_scope(fallback, configured_group_id=20) == "group_id:20"  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="сообщества"):
        build_vk_bot_scope(fallback)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_rule_distinguishes_valid_invalid_and_foreign_payloads() -> None:
    rule = VkSagurInteractionRule()
    valid = _FakeEvent(payload=_payload("l"))
    invalid = _FakeEvent(payload=_payload("l", v=3))
    foreign = _FakeEvent(payload={"t": "other"})

    valid_result = await rule.check(valid)  # type: ignore[arg-type]
    invalid_result = await rule.check(invalid)  # type: ignore[arg-type]
    foreign_result = await rule.check(foreign)  # type: ignore[arg-type]

    assert isinstance(valid_result, dict) and "sagur_payload" in valid_result
    assert isinstance(invalid_result, dict) and "sagur_payload_error" in invalid_result
    assert foreign_result is False


@pytest.mark.asyncio
async def test_rating_order_is_record_answer_fetch_edit_and_mark() -> None:
    timeline: list[str] = []
    source_message = SimpleNamespace(
        text="Сообщение с фото",
        keyboard=_keyboard(),
        attachments=[{"type": "photo", "photo": {"owner_id": -1, "id": 2, "access_key": "key"}}],
    )
    event = _FakeEvent(payload=_payload("l"), timeline=timeline, source_message=source_message)
    service = _Service(timeline)

    await handle_vk_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed("l"),
    )

    assert timeline == [
        "record_event",
        "answer",
        "fetch_message",
        "edit_message",
        "mark_succeeded",
    ]
    assert event.answers == 1
    assert event.edits[0]["message"] == "Сообщение с фото"
    assert event.edits[0]["attachment"] == "photo-1_2_key"
    assert event.edits[0]["keep_forward_messages"] is True
    assert event.edits[0]["keep_snippets"] is True
    assert set(json.loads(event.edits[0]["keyboard"])) == {"one_time", "inline", "buttons"}
    assert service.ingress[0].bot_scope == "group_id:236296391"
    assert service.ingress[0].provider_message_id == "654588"


@pytest.mark.asyncio
async def test_fetch_supports_nested_mapping_response() -> None:
    timeline: list[str] = []
    event = _FakeEvent(payload=_payload("l"), timeline=timeline)
    event.messages.fetch_response = {"response": {"items": [event.messages.source_message]}}
    service = _Service(timeline)

    await handle_vk_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed("l"),
    )

    assert event.edits


@pytest.mark.asyncio
async def test_event_id_fallback_is_used_and_missing_id_is_rejected() -> None:
    timeline: list[str] = []
    fallback_event = _FakeEvent(payload=_payload("m"), timeline=timeline)
    del fallback_event.event_id
    fallback_event.object = SimpleNamespace(event_id="fallback-event-id")
    service = _Service(timeline)

    await handle_vk_sagur_interaction(
        fallback_event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed("m"),
    )

    assert service.ingress[0].platform_callback_id == "fallback-event-id"

    missing_event = _FakeEvent(payload=_payload("m"), timeline=[])
    del missing_event.event_id
    missing_event.object = SimpleNamespace(event_id=None)

    await handle_vk_sagur_interaction(
        missing_event,  # type: ignore[arg-type]
        service=_Service(missing_event.timeline),  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(missing_event.timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed("m"),
    )

    assert missing_event.snackbars == ["Не удалось сохранить нажатие. Повторите попытку."]


@pytest.mark.asyncio
async def test_unavailable_message_lookup_is_recorded_as_user_action_failure() -> None:
    timeline: list[str] = []
    event = _FakeEvent(payload=_payload("l"), timeline=timeline)
    event.peer_id = None
    service = _Service(timeline)

    await handle_vk_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed("l"),
    )

    assert timeline[-1] == "mark_failed"
    assert event.edits == []


@pytest.mark.asyncio
async def test_navigation_sends_new_message_with_keyboard_and_parse_mode() -> None:
    timeline: list[str] = []
    event = _FakeEvent(payload=_payload("m"), timeline=timeline)
    service = _Service(timeline)
    identity = _IdentityAdapter(timeline, parse_mode="Markdown")

    await handle_vk_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=identity,  # type: ignore[arg-type]
        sagur_payload=_parsed("m"),
    )

    assert timeline == [
        "record_event",
        "answer",
        "navigation",
        "send_message",
        "mark_succeeded",
    ]
    assert identity.calls == [(101, "m")]
    assert event.messages.send_calls[0]["peer_id"] == 2000000001
    assert event.messages.send_calls[0]["keyboard"]
    assert event.messages.send_calls[0]["parse_mode"] == "Markdown"


@pytest.mark.asyncio
async def test_navigation_without_screen_sends_no_keyboard_or_parse_mode() -> None:
    timeline: list[str] = []
    event = _FakeEvent(payload=_payload("c"), timeline=timeline)

    await handle_vk_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=_Service(timeline),  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline, with_keyboard=False),  # type: ignore[arg-type]
        sagur_payload=_parsed("c"),
    )

    assert set(event.messages.send_calls[0]) == {"peer_id", "random_id", "message"}


@pytest.mark.asyncio
async def test_invalid_payload_is_snackbar_without_database_write() -> None:
    timeline: list[str] = []
    event = _FakeEvent(payload=_payload("l", v=3), timeline=timeline)
    service = _Service(timeline)
    error = None
    try:
        parse_sagur_button_payload(event.get_payload_json())
    except Exception as caught:  # noqa: BLE001
        error = caught

    await handle_vk_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload_error=error,  # type: ignore[arg-type]
    )

    assert service.ingress == []
    assert event.snackbars == ["Кнопка содержит некорректные служебные данные."]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "record_error",
    [SagurMessageInteractionStorageError("База недоступна"), None],
)
async def test_storage_or_scope_failure_stops_action(record_error: Exception | None) -> None:
    timeline: list[str] = []
    event = _FakeEvent(
        payload=_payload("l"),
        timeline=timeline,
        group_id=None if record_error is None else 1,
    )
    service = _Service(timeline, record_error=record_error)

    await handle_vk_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed("l"),
    )

    assert event.edits == []
    assert event.snackbars == ["Не удалось сохранить нажатие. Повторите попытку."]


@pytest.mark.asyncio
@pytest.mark.parametrize("immutable_fields_match", [True, False])
async def test_duplicate_is_answered_without_repeating_user_action(
    immutable_fields_match: bool,
) -> None:
    timeline: list[str] = []
    event = _FakeEvent(payload=_payload("l"), timeline=timeline)
    service = _Service(
        timeline,
        created=False,
        immutable_fields_match=immutable_fields_match,
    )

    await handle_vk_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed("l"),
    )

    assert timeline == ["record_event", "answer"]
    assert event.edits == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unsafe_keyboard", "ambiguous_fetch", "missing_text"])
async def test_rating_platform_failures_are_recorded_and_keep_keyboard(failure: str) -> None:
    timeline: list[str] = []
    source_message = SimpleNamespace(
        text=None if failure == "missing_text" else "Сообщение",
        keyboard=_keyboard(unsafe=failure == "unsafe_keyboard"),
        attachments=[],
    )
    event = _FakeEvent(payload=_payload("l"), timeline=timeline, source_message=source_message)
    if failure == "ambiguous_fetch":
        event.messages.fetch_response = SimpleNamespace(items=[])
    service = _Service(timeline)

    await handle_vk_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=service,  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed("l"),
    )

    assert event.edits == []
    assert timeline[-1] == "mark_failed"
    assert service.failed_actions


@pytest.mark.asyncio
@pytest.mark.parametrize("platform_failure", ["answer", "edit", "send", "navigation"])
async def test_platform_failures_do_not_escape_handler(platform_failure: str) -> None:
    timeline: list[str] = []
    event = _FakeEvent(
        payload=_payload("m" if platform_failure in {"send", "navigation"} else "l"),
        timeline=timeline,
        answer_error=RuntimeError("answer") if platform_failure == "answer" else None,
        edit_error=RuntimeError("edit") if platform_failure == "edit" else None,
        send_error=RuntimeError("send") if platform_failure == "send" else None,
    )
    identity = _IdentityAdapter(
        timeline,
        error=RuntimeError("navigation") if platform_failure == "navigation" else None,
    )

    await handle_vk_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=_Service(timeline),  # type: ignore[arg-type]
        identity_adapter=identity,  # type: ignore[arg-type]
        sagur_payload=_parsed(event.get_payload_json()["a"]),
    )

    if platform_failure == "answer":
        assert timeline[-1] == "mark_succeeded"
    else:
        assert timeline[-1] == "mark_failed"


@pytest.mark.asyncio
async def test_mark_state_failure_is_contained_after_successful_edit() -> None:
    timeline: list[str] = []
    event = _FakeEvent(payload=_payload("l"), timeline=timeline)

    await handle_vk_sagur_interaction(
        event,  # type: ignore[arg-type]
        service=_Service(timeline, mark_error=RuntimeError("База недоступна")),  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        sagur_payload=_parsed("l"),
    )

    assert event.edits
    assert timeline[-1] == "mark_succeeded"


def test_registration_adds_one_blocking_filtered_raw_handler() -> None:
    bot = Bot("VK_TEST_TOKEN")
    timeline: list[str] = []

    register_vk_sagur_message_interactions(
        bot,
        service=_Service(timeline),  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
    )

    handlers = bot.on.raw_event_view.handlers[GroupEventType.MESSAGE_EVENT]
    assert len(handlers) == 1
    assert handlers[0].handler.blocking is True
    assert len(handlers[0].handler.rules) == 1
    assert isinstance(handlers[0].handler.rules[0], VkSagurInteractionRule)


@pytest.mark.asyncio
async def test_registered_raw_handler_executes_production_closure() -> None:
    bot = Bot("VK_TEST_TOKEN")
    timeline: list[str] = []
    service = _Service(timeline)
    identity = _IdentityAdapter(timeline, with_keyboard=False)
    register_vk_sagur_message_interactions(
        bot,
        service=service,  # type: ignore[arg-type]
        identity_adapter=identity,  # type: ignore[arg-type]
    )

    class _RawMessagesApi:
        async def send_message_event_answer(self, **kwargs: Any) -> int:
            timeline.append("answer")
            return 1

        async def send(self, **kwargs: Any) -> int:
            timeline.append("send_message")
            return 1

    raw_event = {
        "type": "message_event",
        "group_id": 236296391,
        "object": {
            "user_id": 101,
            "peer_id": 2000000001,
            "event_id": "raw-production-event",
            "payload": _payload("m"),
            "conversation_message_id": 654588,
        },
    }
    await bot.on.raw_event_view.handle_event(
        raw_event,
        SimpleNamespace(messages=_RawMessagesApi()),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert service.ingress[0].platform_callback_id == "raw-production-event"
    assert timeline == [
        "record_event",
        "answer",
        "navigation",
        "send_message",
        "mark_succeeded",
    ]
