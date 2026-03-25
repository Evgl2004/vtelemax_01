"""Роутер MAX-адаптера (maxapi) для гостевых сценариев."""

from __future__ import annotations

import asyncio
from typing import Any

from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor

from .identity_adapter import MaxAdapterResponse, MaxIdentityAdapter
from .keyboard_renderer import render_max_keyboard

_START_COMMANDS = {"/start", "start", "начать"}
_LEGACY_COMMANDS = {"/legacy", "legacy", "обновить профиль"}


def register_max_guest_handlers(
    router: Any,
    adapter: MaxIdentityAdapter,
    delivery_processor: PendingModeratorDeliveryProcessor | None = None,
) -> None:
    """Регистрирует обработчики MAX-бота на переданном `router`."""

    delivery_lock = asyncio.Lock()

    async def _try_process_pending_deliveries(bot: Any | None) -> None:
        """Пытается доставить pending-сообщения модератора без влияния на UX пользователя."""

        if delivery_processor is None or bot is None:
            return
        if delivery_lock.locked():
            return

        async with delivery_lock:
            async def _send_message(target_external_id: str, text: str) -> None:
                await bot.send_message(user_id=int(target_external_id), text=text)

            try:
                await delivery_processor.process_once(sender=_send_message, limit=20)
            except Exception:  # noqa: BLE001
                # На MVP-этапе не прерываем пользовательский сценарий из-за сбоя доставки.
                return

    @router.message_created()
    async def message_handler(event: Any, context: Any = None) -> None:  # noqa: ARG001
        await _try_process_pending_deliveries(getattr(event, "bot", None))
        user_id = _extract_user_id(event)
        if user_id is None:
            return
        text = _extract_message_text(event)
        lowered = text.strip().lower()

        if lowered in _START_COMMANDS:
            response = adapter.handle_start(max_user_id=user_id)
        elif lowered in _LEGACY_COMMANDS:
            response = adapter.handle_legacy_start(max_user_id=user_id)
        else:
            response = adapter.handle_incoming(max_user_id=user_id, text=text, payload=None)
        await _send_response(event, response)

    @router.bot_started()
    async def started_handler(event: Any, context: Any = None) -> None:  # noqa: ARG001
        await _try_process_pending_deliveries(getattr(event, "bot", None))
        user_id = _extract_user_id(event)
        if user_id is None:
            return
        response = adapter.handle_start(max_user_id=user_id)
        await _send_response(event, response)

    @router.message_callback()
    async def callback_handler(event: Any, context: Any = None) -> None:  # noqa: ARG001
        await _try_process_pending_deliveries(getattr(event, "bot", None))
        user_id = _extract_user_id(event)
        if user_id is None:
            return

        callback_payload = _extract_callback_payload(event)
        if hasattr(event, "answer"):
            await event.answer("")

        response = adapter.handle_incoming(
            max_user_id=user_id,
            text="",
            payload=callback_payload,
        )
        await _send_response(event, response)


async def _send_response(event: Any, response: MaxAdapterResponse) -> None:
    """Отправляет ответ адаптера в чат MAX."""

    bot = getattr(event, "bot", None)
    chat_id = _extract_chat_id(event)
    if bot is None or chat_id is None:
        return

    kwargs: dict[str, object] = {}
    keyboard = render_max_keyboard(response.screen)
    if keyboard is not None:
        kwargs["attachments"] = [keyboard]

    if response.screen is not None and response.screen.parse_mode == "markdown":
        parse_mode = _resolve_markdown_parse_mode()
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode

    await bot.send_message(chat_id=chat_id, text=response.text, **kwargs)


def _resolve_markdown_parse_mode() -> Any | None:
    """Возвращает `ParseMode.MARKDOWN`, если maxapi доступен."""

    try:
        from maxapi.enums.parse_mode import ParseMode
    except Exception:
        return None
    return ParseMode.MARKDOWN


def _extract_user_id(event: Any) -> int | None:
    """Извлекает user_id из разных типов MAX-событий."""

    if hasattr(event, "from_user") and hasattr(event.from_user, "user_id"):
        return int(event.from_user.user_id)
    if hasattr(event, "user") and hasattr(event.user, "user_id"):
        return int(event.user.user_id)
    return None


def _extract_chat_id(event: Any) -> int | None:
    """Извлекает chat_id из разных типов MAX-событий."""

    if hasattr(event, "chat_id"):
        return int(event.chat_id)
    if hasattr(event, "chat") and hasattr(event.chat, "chat_id"):
        return int(event.chat.chat_id)
    if (
        hasattr(event, "message")
        and hasattr(event.message, "recipient")
        and hasattr(event.message.recipient, "chat_id")
    ):
        return int(event.message.recipient.chat_id)
    return None


def _extract_message_text(event: Any) -> str:
    """Возвращает текст входящего сообщения MAX."""

    if (
        hasattr(event, "message")
        and hasattr(event.message, "body")
        and hasattr(event.message.body, "text")
        and event.message.body.text is not None
    ):
        return str(event.message.body.text)
    return ""


def _extract_callback_payload(event: Any) -> str | None:
    """Возвращает payload callback-кнопки MAX."""

    if hasattr(event, "callback") and hasattr(event.callback, "payload"):
        payload = event.callback.payload
        if payload is None:
            return None
        return str(payload)
    return None
