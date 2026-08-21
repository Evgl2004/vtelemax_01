"""Тесты приёма интерактивных сообщений SAGUR в Telegram."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator
from uuid import UUID

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Update

from vtelemax.adapters.sagur_message_interactions import SagurMessageInteractionStorageError
from vtelemax.adapters.telegram.identity_adapter import TelegramMenuActionResult
from vtelemax.adapters.telegram.sagur_message_interactions import (
    TelegramSagurInteractionFilter,
    build_telegram_bot_scope,
    build_telegram_sagur_interaction_router,
)
from vtelemax.core.sagur_message_interactions import (
    SagurMessageInteractionEvent,
    SagurMessageInteractionInsertResult,
)


EVENT_ID = UUID("aaaaaaaa-0000-4000-8000-000000000001")


def _payload(action: str = "l", **overrides: Any) -> str:
    value: dict[str, Any] = {"t": "si", "v": 1, "i": 123456, "a": action}
    value.update(overrides)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _keyboard(*, unsafe: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="👍 Нравится", callback_data=_payload("l")),
            InlineKeyboardButton(text="👎 Не нравится", callback_data=_payload("d")),
        ],
        [InlineKeyboardButton(text="☰ Меню", callback_data=_payload("m"))],
    ]
    if unsafe:
        rows.pop()
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _update(
    *,
    callback_data: str,
    keyboard: InlineKeyboardMarkup | None = None,
    with_message: bool = True,
) -> Update:
    callback_query: dict[str, Any] = {
        "id": "987654321",
        "from": {"id": 101, "is_bot": False, "first_name": "Проверка"},
        "chat_instance": "test-chat-instance",
        "data": callback_data,
    }
    if with_message:
        callback_query["message"] = {
            "message_id": 202,
            "date": 0,
            "chat": {"id": 101, "type": "private"},
            "reply_markup": (keyboard or _keyboard()).model_dump(exclude_none=True),
        }
    else:
        callback_query["inline_message_id"] = "inline-message"
    return Update.model_validate({"update_id": 303, "callback_query": callback_query})


class _RecordingSession(BaseSession):
    """Имитирует Telegram API и сохраняет порядок запросов без сети."""

    def __init__(
        self,
        timeline: list[str],
        *,
        fail_method: type[TelegramMethod[Any]] | None = None,
    ) -> None:
        super().__init__()
        self.timeline = timeline
        self.requests: list[TelegramMethod[Any]] = []
        self.fail_method = fail_method

    async def close(self) -> None:
        return

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,
    ) -> Any:
        self.requests.append(method)
        self.timeline.append(type(method).__name__)
        if self.fail_method is not None and isinstance(method, self.fail_method):
            raise RuntimeError("Telegram API отклонил запрос")
        return True

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        if False:  # pragma: no cover - обязательная часть интерфейса BaseSession.
            yield b""


@dataclass
class _Service:
    timeline: list[str]
    created: bool = True
    immutable_fields_match: bool = True
    record_error: Exception | None = None
    mark_error: Exception | None = None
    ingress: list[Any] = field(default_factory=list)
    failed_actions: list[dict[str, Any]] = field(default_factory=list)

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
    status: str | None = None
    calls: list[tuple[int, str]] = field(default_factory=list)

    def handle_sagur_navigation(self, user_id: int, action: str) -> TelegramMenuActionResult:
        self.timeline.append("navigation")
        self.calls.append((user_id, action))
        if self.error is not None:
            raise self.error
        status = self.status or ("menu" if action == "m" else "coupons_root")
        return TelegramMenuActionResult(
            status=status,
            message=f"Экран {status}",
            coupon_scope_buttons=(("coupon_scope:all", "Все купоны"),),
        )


async def _feed(
    *,
    update: Update,
    service: _Service,
    identity_adapter: _IdentityAdapter,
    session: _RecordingSession,
    fallback: list[str] | None = None,
) -> list[TelegramMethod[Any]]:
    bot = Bot(token="123456:TEST_TOKEN_FOR_LOCAL_UNIT_TEST", session=session)
    dispatcher = Dispatcher()
    dispatcher.include_router(
        build_telegram_sagur_interaction_router(
            service=service,  # type: ignore[arg-type]
            identity_adapter=identity_adapter,  # type: ignore[arg-type]
            bot_scope="bot_id:123456",
        )
    )
    if fallback is not None:
        fallback_router = Router(name="fallback")

        async def fallback_handler(callback: CallbackQuery) -> None:
            fallback.append(callback.data or "")

        fallback_router.callback_query.register(fallback_handler)
        dispatcher.include_router(fallback_router)
    await dispatcher.feed_update(bot, update)
    return session.requests


@pytest.mark.parametrize(
    ("token", "username", "scope"),
    [
        ("123456:secret", "ignored_bot", "bot_id:123456"),
        ("не-токен", "@Sa_Bal_Bot", "username:sa_bal_bot"),
    ],
)
def test_bot_scope_uses_numeric_id_or_normalized_username(
    token: str,
    username: str,
    scope: str,
) -> None:
    assert build_telegram_bot_scope(token=token, username=username) == scope


def test_bot_scope_rejects_missing_stable_identifier() -> None:
    with pytest.raises(ValueError, match="область"):
        build_telegram_bot_scope(token="не-токен")


@pytest.mark.asyncio
async def test_filter_distinguishes_valid_invalid_and_foreign_payloads() -> None:
    valid = CallbackQuery.model_validate(
        _update(callback_data=_payload("l")).callback_query.model_dump(by_alias=True)
    )
    invalid = CallbackQuery.model_validate(
        _update(callback_data=_payload("l", v=3)).callback_query.model_dump(by_alias=True)
    )
    foreign = CallbackQuery.model_validate(
        _update(callback_data=json.dumps({"t": "other"})).callback_query.model_dump(by_alias=True)
    )
    interaction_filter = TelegramSagurInteractionFilter()

    valid_result = await interaction_filter(valid)
    invalid_result = await interaction_filter(invalid)
    foreign_result = await interaction_filter(foreign)

    assert isinstance(valid_result, dict) and "sagur_payload" in valid_result
    assert isinstance(invalid_result, dict) and "sagur_payload_error" in invalid_result
    assert foreign_result is False


@pytest.mark.asyncio
async def test_rating_is_recorded_answered_edited_and_marked_in_exact_order() -> None:
    timeline: list[str] = []
    service = _Service(timeline)
    identity = _IdentityAdapter(timeline)
    session = _RecordingSession(timeline)

    requests = await _feed(
        update=_update(callback_data=_payload("l")),
        service=service,
        identity_adapter=identity,
        session=session,
    )

    assert timeline == [
        "record_event",
        "AnswerCallbackQuery",
        "EditMessageReplyMarkup",
        "mark_succeeded",
    ]
    assert [type(request) for request in requests] == [AnswerCallbackQuery, EditMessageReplyMarkup]
    edit = requests[1]
    assert isinstance(edit, EditMessageReplyMarkup)
    assert len(edit.reply_markup.inline_keyboard) == 1
    assert edit.reply_markup.inline_keyboard[0][0].text == "☰ Меню"
    assert service.ingress[0].provider_message_id == "202"
    assert service.ingress[0].platform_callback_id == "987654321"


@pytest.mark.asyncio
async def test_navigation_sends_new_menu_after_durable_insert_and_answer() -> None:
    timeline: list[str] = []
    service = _Service(timeline)
    identity = _IdentityAdapter(timeline)
    session = _RecordingSession(timeline)

    requests = await _feed(
        update=_update(callback_data=_payload("m")),
        service=service,
        identity_adapter=identity,
        session=session,
    )

    assert timeline == [
        "record_event",
        "AnswerCallbackQuery",
        "navigation",
        "SendMessage",
        "mark_succeeded",
    ]
    assert identity.calls == [(101, "m")]
    sent = requests[1]
    assert isinstance(sent, SendMessage)
    assert sent.chat_id == 101
    assert sent.reply_markup is not None


@pytest.mark.asyncio
async def test_coupon_navigation_builds_coupon_keyboard() -> None:
    timeline: list[str] = []
    service = _Service(timeline)
    identity = _IdentityAdapter(timeline)
    session = _RecordingSession(timeline)

    requests = await _feed(
        update=_update(callback_data=_payload("c")),
        service=service,
        identity_adapter=identity,
        session=session,
    )

    sent = requests[1]
    assert isinstance(sent, SendMessage)
    assert sent.reply_markup.inline_keyboard[0][0].text == "Все купоны"


@pytest.mark.asyncio
async def test_navigation_unknown_result_is_sent_without_keyboard() -> None:
    timeline: list[str] = []
    service = _Service(timeline)
    identity = _IdentityAdapter(timeline, status="not_registered")
    session = _RecordingSession(timeline)

    requests = await _feed(
        update=_update(callback_data=_payload("c")),
        service=service,
        identity_adapter=identity,
        session=session,
    )

    sent = requests[1]
    assert isinstance(sent, SendMessage)
    assert sent.reply_markup is None


@pytest.mark.asyncio
async def test_invalid_declared_payload_is_alerted_without_database_write() -> None:
    timeline: list[str] = []
    service = _Service(timeline)
    session = _RecordingSession(timeline)

    requests = await _feed(
        update=_update(callback_data=_payload("l", v=3)),
        service=service,
        identity_adapter=_IdentityAdapter(timeline),
        session=session,
    )

    assert service.ingress == []
    assert [type(request) for request in requests] == [AnswerCallbackQuery]
    assert requests[0].show_alert is True


@pytest.mark.asyncio
async def test_foreign_payload_reaches_following_router() -> None:
    timeline: list[str] = []
    service = _Service(timeline)
    session = _RecordingSession(timeline)
    fallback: list[str] = []
    foreign_payload = json.dumps({"t": "other"})

    requests = await _feed(
        update=_update(callback_data=foreign_payload),
        service=service,
        identity_adapter=_IdentityAdapter(timeline),
        session=session,
        fallback=fallback,
    )

    assert fallback == [foreign_payload]
    assert service.ingress == []
    assert requests == []


@pytest.mark.asyncio
async def test_database_failure_preserves_keyboard_and_stops_user_action() -> None:
    timeline: list[str] = []
    service = _Service(
        timeline,
        record_error=SagurMessageInteractionStorageError("База недоступна"),
    )
    session = _RecordingSession(timeline)

    requests = await _feed(
        update=_update(callback_data=_payload("l")),
        service=service,
        identity_adapter=_IdentityAdapter(timeline),
        session=session,
    )

    assert timeline == ["record_event", "AnswerCallbackQuery"]
    assert [type(request) for request in requests] == [AnswerCallbackQuery]
    assert requests[0].show_alert is True


@pytest.mark.asyncio
@pytest.mark.parametrize("immutable_fields_match", [True, False])
async def test_duplicate_platform_event_is_answered_without_repeating_action(
    immutable_fields_match: bool,
) -> None:
    timeline: list[str] = []
    service = _Service(
        timeline,
        created=False,
        immutable_fields_match=immutable_fields_match,
    )
    session = _RecordingSession(timeline)

    requests = await _feed(
        update=_update(callback_data=_payload("l")),
        service=service,
        identity_adapter=_IdentityAdapter(timeline),
        session=session,
    )

    assert timeline == ["record_event", "AnswerCallbackQuery"]
    assert [type(request) for request in requests] == [AnswerCallbackQuery]


@pytest.mark.asyncio
@pytest.mark.parametrize("with_message", [True, False])
async def test_uneditable_rating_is_recorded_as_failed_user_action(with_message: bool) -> None:
    timeline: list[str] = []
    service = _Service(timeline)
    session = _RecordingSession(timeline)

    await _feed(
        update=_update(
            callback_data=_payload("l"),
            keyboard=_keyboard(unsafe=True),
            with_message=with_message,
        ),
        service=service,
        identity_adapter=_IdentityAdapter(timeline),
        session=session,
    )

    assert timeline == ["record_event", "AnswerCallbackQuery", "mark_failed"]
    assert service.failed_actions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failed_method", [AnswerCallbackQuery, EditMessageReplyMarkup, SendMessage]
)
async def test_platform_errors_do_not_escape_handler_and_are_recorded(
    failed_method: type[TelegramMethod[Any]],
) -> None:
    timeline: list[str] = []
    service = _Service(timeline)
    session = _RecordingSession(timeline, fail_method=failed_method)
    action = "m" if failed_method is SendMessage else "l"

    await _feed(
        update=_update(callback_data=_payload(action)),
        service=service,
        identity_adapter=_IdentityAdapter(timeline),
        session=session,
    )

    if failed_method is AnswerCallbackQuery:
        assert timeline[-1] == "mark_succeeded"
    else:
        assert timeline[-1] == "mark_failed"


@pytest.mark.asyncio
async def test_navigation_adapter_error_is_recorded_without_new_message() -> None:
    timeline: list[str] = []
    service = _Service(timeline)
    session = _RecordingSession(timeline)

    requests = await _feed(
        update=_update(callback_data=_payload("m")),
        service=service,
        identity_adapter=_IdentityAdapter(timeline, error=RuntimeError("Меню недоступно")),
        session=session,
    )

    assert [type(request) for request in requests] == [AnswerCallbackQuery]
    assert timeline[-1] == "mark_failed"


@pytest.mark.asyncio
async def test_state_mark_failure_is_contained_after_successful_platform_action() -> None:
    timeline: list[str] = []
    service = _Service(timeline, mark_error=RuntimeError("База недоступна"))
    session = _RecordingSession(timeline)

    requests = await _feed(
        update=_update(callback_data=_payload("l")),
        service=service,
        identity_adapter=_IdentityAdapter(timeline),
        session=session,
    )

    assert [type(request) for request in requests] == [AnswerCallbackQuery, EditMessageReplyMarkup]
    assert timeline[-1] == "mark_succeeded"


def test_router_contains_one_priority_callback_handler() -> None:
    timeline: list[str] = []
    router = build_telegram_sagur_interaction_router(
        service=_Service(timeline),  # type: ignore[arg-type]
        identity_adapter=_IdentityAdapter(timeline),  # type: ignore[arg-type]
        bot_scope="bot_id:123456",
    )

    assert router.name == "telegram_sagur_message_interactions"
    assert len(router.callback_query.handlers) == 1
