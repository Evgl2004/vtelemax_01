"""Проверки редактирования исходного сообщения через сериализаторы SDK."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs
from uuid import uuid4

import aiohttp
import pytest
from aiogram import Bot as TelegramBot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import CallbackQuery, InaccessibleMessage
from maxapi import Bot as MaxBot
from maxapi.types.attachments.attachment import PhotoAttachmentPayload
from maxapi.types.updates.message_callback import MessageCallback
from pydantic import ValidationError
from vkbottle import API
from vkbottle.bot import MessageEvent
from vkbottle.http import AiohttpClient
from yarl import URL

from vtelemax.adapters.max.sagur_message_interactions import handle_max_sagur_interaction
from vtelemax.adapters.telegram.sagur_message_interactions import handle_telegram_sagur_interaction
from vtelemax.adapters.vk.sagur_message_interactions import handle_vk_sagur_interaction
from vtelemax.core.sagur_message_interactions import (
    SagurMessageInteractionEvent,
    SagurMessageInteractionInsertResult,
    parse_sagur_button_payload,
)

TEXT = "Сообщение для Анны\n<обычный текст> & 🎈"
CHAT_ID = 123
MESSAGE_ID = 81
VK_GLOBAL_ID = 901
MAX_MESSAGE_ID = "mid.stage61.81"
LINK = "https://example.test/menu"
PLATFORMS = ("telegram", "vk", "max")
EDIT_METHODS = ("editMessageReplyMarkup", "messages.edit", "PUT /messages")


def button_payload(version: int, action: str, navigation: str) -> str:
    value = (
        action
        if version == 1
        else {
            "l": f"ld{navigation}",
            "d": f"dl{navigation}",
            navigation: f"{navigation}ld",
        }[action]
    )
    return json.dumps({"t": "si", "v": version, "i": 913, "a": value}, separators=(",", ":"))


def keyboard_rows(platform: str, version: int, navigation: str, with_link: bool) -> list:
    def callback(action: str, label: str) -> dict:
        payload = button_payload(version, action, navigation)
        color = {"l": "positive", "d": "negative"}.get(action, "primary")
        if platform == "telegram":
            style = {"positive": "success", "negative": "danger", "primary": "primary"}[color]
            return {"text": label, "callback_data": payload, "style": style}
        if platform == "vk":
            return {
                "action": {"type": "callback", "label": label, "payload": payload},
                "color": color,
            }
        return {
            "type": "callback",
            "text": label,
            "payload": payload,
            "intent": color if action in {"l", "d"} else "default",
        }

    rows = [[callback("l", "Нравится"), callback("d", "Не нравится")]]
    if with_link:
        if platform == "vk":
            link = {"action": {"type": "open_link", "label": "Ссылка", "link": LINK}}
        elif platform == "max":
            link = {"type": "link", "text": "Ссылка", "url": LINK}
        else:
            link = {"text": "Ссылка", "url": LINK, "style": "primary"}
        rows.append([link])
    rows.append([callback(navigation, "Меню" if navigation == "m" else "В купоны")])
    return rows


def max_user(user_id: int) -> dict:
    return {
        "user_id": user_id,
        "first_name": "Проверка",
        "is_bot": user_id == 999,
        "last_activity_time": 1,
    }


def max_message(attachments: list) -> dict:
    return {
        "sender": max_user(999),
        "recipient": {"chat_id": CHAT_ID, "chat_type": "chat"},
        "timestamp": 1,
        "body": {
            "mid": MAX_MESSAGE_ID,
            "seq": 1,
            "text": TEXT,
            "attachments": attachments,
        },
    }


def telegram_message() -> dict:
    return {
        "message_id": MESSAGE_ID,
        "date": 1,
        "chat": {"id": CHAT_ID, "type": "private"},
        "text": TEXT,
    }


def vk_message(rows: list, count: int) -> dict:
    return {
        "id": VK_GLOBAL_ID,
        "conversation_message_id": MESSAGE_ID,
        "peer_id": CHAT_ID,
        "date": 1,
        "from_id": -999,
        "out": 1,
        "version": 1,
        "text": TEXT,
        "keyboard": {"inline": True, "one_time": False, "author_id": -999, "buttons": rows},
        "attachments": [
            {
                "type": "photo",
                "photo": {
                    "id": 500 + index,
                    "owner_id": -999,
                    "album_id": 1,
                    "date": 1,
                    "has_tags": False,
                    **({"access_key": f"key_{index}"} if index % 2 == 0 else {}),
                },
            }
            for index in range(count)
        ],
    }


class RecordingService:
    def __init__(self) -> None:
        self.events = {}
        self.succeeded = []
        self.failed = {}

    def record_event(self, ingress):
        callback_id = ingress.platform_callback_id
        previous = self.events.get(callback_id)
        if previous is not None:
            return SagurMessageInteractionInsertResult(previous, False, True)
        event = SagurMessageInteractionEvent(
            event_id=uuid4(),
            platform=ingress.platform,
            bot_scope=ingress.bot_scope,
            platform_callback_id=callback_id,
            interaction_id=ingress.interaction_id,
            action=ingress.action,
            occurred_at=datetime(2026, 11, 4, tzinfo=timezone.utc),
            provider_message_id=ingress.provider_message_id,
        )
        self.events[callback_id] = event
        return SagurMessageInteractionInsertResult(event, True, True)

    def mark_user_action_succeeded(self, event_id, **kwargs):
        self.succeeded.append(event_id)

    def mark_user_action_failed(self, event_id, *, error_code, **kwargs):
        self.failed[event_id] = error_code


class SerializedBody:
    def __init__(self) -> None:
        self.chunks = []

    async def write(self, chunk: bytes) -> None:
        self.chunks.append(chunk)


class FakeResponse:
    status = 200
    ok = True

    def __init__(self, data: dict) -> None:
        self.data = data

    async def json(self, **kwargs) -> dict:
        return self.data

    async def text(self, **kwargs) -> str:
        return json.dumps(self.data, ensure_ascii=False)

    async def read(self) -> bytes:
        return (await self.text()).encode()


class PendingResponse:
    def __init__(self, response) -> None:
        self.response = response

    def __await__(self):
        return self.response.__await__()

    async def __aenter__(self):
        return await self.response

    async def __aexit__(self, *args):
        return None


class Wire:
    """Подменяет сессию после формирования параметров и кодирует тело через aiohttp."""

    closed = True

    def __init__(self, source: dict) -> None:
        self.source = source
        self.requests = []
        self.edit_failure = None

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def request(self, method, url, **kwargs):
        return PendingResponse(self._respond(method, url, **kwargs))

    async def _respond(self, method, url, *, data=None, params=None, **kwargs):
        path = URL(url).path
        endpoint = (
            path.rsplit("/", maxsplit=1)[-1] if URL(url).is_absolute() else f"{method} {path}"
        )
        json_data = kwargs.get("json")
        if json_data is not None:
            payload = aiohttp.payload.JsonPayload(json_data)
        elif isinstance(data, aiohttp.FormData):
            payload = data()
        else:
            payload = aiohttp.FormData(data or {})()
        writer = SerializedBody()
        await payload.write(writer)
        encoded = b"".join(writer.chunks).decode()
        if json_data is not None:
            body = json.loads(encoded)
        else:
            body = {
                key: values[0] for key, values in parse_qs(encoded, keep_blank_values=True).items()
            }
        self.requests.append((endpoint, dict(params or {}), body))
        if endpoint in EDIT_METHODS and self.edit_failure == "transport":
            raise aiohttp.ClientConnectionError("Учебный сетевой отказ")
        success = not (endpoint in EDIT_METHODS and self.edit_failure == "logical")
        if endpoint == "messages.getByConversationMessageId":
            result = {"response": {"count": 1, "items": [self.source]}}
        elif endpoint.startswith("messages."):
            result = {"response": int(success)}
        elif endpoint == "POST /messages":
            result = {"message": max_message([])}
        elif endpoint.startswith(("POST ", "PUT ")):
            result = {"success": success}
        else:
            result = {
                "ok": True,
                "result": telegram_message() if endpoint == "sendMessage" else success,
            }
        return FakeResponse(result)


def make_event(platform, wire, rows, count, payload, callback_id, *, damage=None):
    if platform == "telegram":
        sdk_session = AiohttpSession()

        async def create_session():
            return wire

        sdk_session.create_session = create_session
        bot = TelegramBot("123456:synthetic-token", session=sdk_session)
        message = telegram_message()
        message["reply_markup"] = {"inline_keyboard": rows}
        if count:
            photos = [
                {
                    "type": "photo",
                    "photo": [
                        {
                            "file_id": f"telegram-{index}",
                            "file_unique_id": f"unique-{index}",
                            "width": 32,
                            "height": 16,
                        }
                    ],
                }
                for index in range(count)
            ]
            message.pop("text")
            message["rich_message"] = {
                "blocks": [
                    {"type": "paragraph", "text": TEXT},
                    photos[0] if count == 1 else {"type": "collage", "blocks": photos},
                ]
            }
        if damage == "inaccessible":
            message = {"message_id": MESSAGE_ID, "date": 0, "chat": message["chat"]}
        return CallbackQuery.model_validate(
            {
                "id": callback_id,
                "chat_instance": "chat-123",
                "data": payload,
                "from": {"id": CHAT_ID, "is_bot": False, "first_name": "Анна"},
                "message": message,
            },
            context={"bot": bot},
        )
    if platform == "vk":
        api = API("synthetic-token", http_client=AiohttpClient(session=wire))
        return MessageEvent.model_validate(
            {
                "type": "message_event",
                "group_id": 999,
                "unprepared_ctx_api": api,
                "object": {
                    "user_id": CHAT_ID,
                    "peer_id": CHAT_ID,
                    "conversation_message_id": MESSAGE_ID,
                    "event_id": callback_id,
                    "payload": json.loads(payload),
                },
            }
        )

    attachments = [
        {
            "type": "image",
            "payload": {
                "photo_id": index + 1,
                "token": f"max-photo-{index}",
                "url": f"https://example.test/{index}",
            },
        }
        for index in range(count)
    ]
    if damage == "missing":
        attachments[-1]["payload"].pop("token")
    elif damage == "empty":
        attachments[-1]["payload"]["token"] = ""
    elif damage == "unsupported":
        attachments[-1]["type"] = "unknown"
    attachments.insert(count // 2, {"type": "inline_keyboard", "payload": {"buttons": rows}})
    message = max_message(attachments)
    if damage == "markup":
        message["body"]["markup"] = [{"type": "strong", "from": 0, "length": 2}]
    event = MessageCallback.model_validate(
        {
            "update_type": "message_callback",
            "timestamp": 1,
            "message": message,
            "callback": {
                "timestamp": 1,
                "callback_id": callback_id,
                "payload": payload,
                "user": max_user(CHAT_ID),
            },
        }
    )
    bot = MaxBot("synthetic-token", auto_requests=False)
    bot.session = wire
    event.bot = bot
    event.message.bot = bot
    return event


async def handle(platform, event, payload, service):
    parsed = parse_sagur_button_payload(payload)
    identity = SimpleNamespace(
        handle_sagur_navigation=lambda user_id, action: SimpleNamespace(
            status="menu" if action == "m" else "coupons_root",
            message="Открыт раздел",
            text="Открыт раздел",
            coupon_scope_buttons=(),
            parse_mode=None,
            screen=None,
        )
    )
    kwargs = {"sagur_payload": parsed, "service": service, "identity_adapter": identity}
    if platform == "telegram":
        await handle_telegram_sagur_interaction(event, bot_scope="bot_id:123456", **kwargs)
    elif platform == "vk":
        await handle_vk_sagur_interaction(event, **kwargs)
    else:
        await handle_max_sagur_interaction(event, **kwargs)


@pytest.fixture(autouse=True)
def no_external_connections(monkeypatch):
    async def deny(*args, **kwargs):
        raise AssertionError("Внешняя сеть запрещена.")

    monkeypatch.setattr(aiohttp.TCPConnector, "connect", deny)


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize(
    ("count", "version", "action", "navigation", "with_link"),
    [
        (0, 1, "l", "m", False),
        (0, 2, "d", "c", False),
        (1, 1, "d", "c", False),
        (1, 2, "l", "m", True),
        (9, 1, "l", "m", True),
        (9, 2, "d", "m", True),
    ],
)
async def test_rating_sdk_edits_original_and_preserves_content(
    platform,
    count,
    version,
    action,
    navigation,
    with_link,
):
    rows = keyboard_rows(platform, version, navigation, with_link)
    source = vk_message(rows, count)
    wire, service = Wire(source), RecordingService()
    payload = button_payload(version, action, navigation)
    event = make_event(platform, wire, rows, count, payload, "rating")
    if platform == "telegram":
        before = event.message.model_dump()
        if count:
            assert event.message.rich_message["blocks"][0]["text"] == TEXT
    elif platform == "max":
        before = event.message.model_dump()
        assert all(
            isinstance(item.payload, PhotoAttachmentPayload)
            for item in event.message.body.attachments
            if item.type == "image"
        )
    else:
        before = deepcopy(source)
    await handle(platform, event, payload, service)
    assert service.succeeded == [service.events["rating"].event_id] and not service.failed
    endpoint, query, body = wire.requests[-1]
    assert service.events["rating"].provider_message_id == (
        MAX_MESSAGE_ID if platform == "max" else str(MESSAGE_ID)
    )
    if platform == "telegram":
        assert endpoint == "editMessageReplyMarkup" and len(wire.requests) == 2
        assert body == {
            "chat_id": str(CHAT_ID),
            "message_id": str(MESSAGE_ID),
            "reply_markup": body["reply_markup"],
        }
        assert json.loads(body["reply_markup"]) == {"inline_keyboard": rows[1:]}
        assert event.message.model_dump() == before
    elif platform == "vk":
        assert endpoint == "messages.edit" and len(wire.requests) == 3
        assert wire.requests[1][0] == "messages.getByConversationMessageId"
        assert wire.requests[1][2]["conversation_message_ids"] == str(MESSAGE_ID)
        assert body["peer_id"] == str(CHAT_ID) and body["cmid"] == str(MESSAGE_ID)
        assert "message_id" not in body and "conversation_message_id" not in body
        assert body["message"] == TEXT
        assert body["keep_forward_messages"] == body["keep_snippets"] == "1"
        assert json.loads(body["keyboard"]) == {
            "inline": True,
            "one_time": False,
            "buttons": rows[1:],
        }
        assert body.get("attachment") == (
            ",".join(
                f"photo-999_{500 + index}" + (f"_key_{index}" if index % 2 == 0 else "")
                for index in range(count)
            )
            if count
            else None
        )
        assert source == before
    else:
        assert wire.requests[0] == (
            "POST /answers",
            {"callback_id": "rating"},
            {"notification": "Нажатие принято."},
        )
        assert (endpoint, query) == ("PUT /messages", {"message_id": MAX_MESSAGE_ID})
        attachments = [
            {"type": "image", "payload": {"token": f"max-photo-{index}"}} for index in range(count)
        ]
        attachments.insert(
            count // 2, {"type": "inline_keyboard", "payload": {"buttons": rows[1:]}}
        )
        assert body == {"text": TEXT, "attachments": attachments, "notify": False}
        assert event.message.model_dump() == before

    await handle(platform, event, payload, service)
    assert len(service.events) == len(service.succeeded) == 1
    assert sum(request[0] in EDIT_METHODS for request in wire.requests) == 1
    if platform == "max":
        assert wire.requests[-1][2] == {"notification": "Нажатие принято."}
    nav_payload = button_payload(version, navigation, navigation)
    nav = make_event(platform, wire, rows[1:], count, nav_payload, "navigation")
    await handle(platform, nav, nav_payload, service)
    assert service.succeeded[-1] == service.events["navigation"].event_id
    assert len(service.events) == len(service.succeeded) == 2 and not service.failed
    assert (
        wire.requests[-1][0]
        == {"telegram": "sendMessage", "vk": "messages.send", "max": "POST /messages"}[platform]
    )


@pytest.mark.parametrize(
    ("platform", "damage"),
    [
        ("telegram", "inaccessible"),
        ("vk", "missing"),
        ("vk", "unsupported"),
        ("vk", "zero_id"),
        ("vk", "wrong_message"),
        ("vk", "cropped"),
        ("max", "missing"),
        ("max", "empty"),
        ("max", "markup"),
    ],
)
async def test_local_rejection_preserves_source_and_later_valid_callback_can_edit(platform, damage):
    rows = keyboard_rows(platform, 2, "m", True)
    source = vk_message(rows, 9)
    wire, service = Wire(source), RecordingService()
    payload = button_payload(2, "d", "m")
    if platform == "vk":
        wire.source = deepcopy(source)
        if damage in {"missing", "unsupported"}:
            wire.source["attachments"][-1] = {"type": "photo" if damage == "missing" else "link"}
        elif damage == "zero_id":
            wire.source["attachments"][-1]["photo"]["id"] = 0
        elif damage == "wrong_message":
            wire.source["conversation_message_id"] += 1
        else:
            wire.source["is_cropped"] = True
    event = make_event(platform, wire, rows, 9, payload, "invalid", damage=damage)
    before = event.message.model_dump() if platform != "vk" else deepcopy(wire.source)
    if platform == "telegram":
        assert isinstance(event.message, InaccessibleMessage)
    await handle(platform, event, payload, service)
    assert not service.succeeded and service.events["invalid"].event_id in service.failed
    assert not any(request[0] in EDIT_METHODS for request in wire.requests)
    assert (event.message.model_dump() if platform != "vk" else wire.source) == before

    wire.source = source
    event = make_event(platform, wire, rows, 9, payload, "valid")
    await handle(platform, event, payload, service)
    assert service.succeeded == [service.events["valid"].event_id]
    assert sum(request[0] in EDIT_METHODS for request in wire.requests) == 1


def test_max_sdk_rejects_unknown_attachment_in_callback():
    wire = Wire({})
    with pytest.raises(ValidationError):
        make_event(
            "max",
            wire,
            keyboard_rows("max", 2, "m", False),
            1,
            button_payload(2, "l", "m"),
            "invalid",
            damage="unsupported",
        )
    assert not wire.requests


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize("failure", ["transport", "logical"])
async def test_platform_rejection_is_recorded_once_without_repeating_edit(platform, failure):
    rows = keyboard_rows(platform, 2, "m", True)
    wire, service = Wire(vk_message(rows, 9)), RecordingService()
    wire.edit_failure = failure
    payload = button_payload(2, "l", "m")
    event = make_event(platform, wire, rows, 9, payload, "rating")
    await handle(platform, event, payload, service)
    await handle(platform, event, payload, service)
    assert not service.succeeded and list(service.failed) == [service.events["rating"].event_id]
    assert sum(request[0] in EDIT_METHODS for request in wire.requests) == 1
