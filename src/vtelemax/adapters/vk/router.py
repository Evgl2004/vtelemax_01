"""Роутер VK-адаптера (vkbottle) для гостевых сценариев."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger
from vkbottle.bot import MessageEvent
from vkbottle_types.events import GroupEventType

from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor

from .identity_adapter import VkAdapterResponse, VkIdentityAdapter
from .keyboard_renderer import render_vk_keyboard
from .payloads import resolve_action_from_vk_payload


def _normalize_vk_message(
    text: str,
    parse_mode: str | None,
) -> tuple[str, str | None]:
    """Нормализует сообщение перед отправкой в VK.

    VK API не гарантирует единообразную интерпретацию markdown-разметки в сообщениях
    с клавиатурами, поэтому при markdown-режиме отправляем плоский текст без маркеров.
    """

    if parse_mode is None:
        return text, None
    normalized_mode = parse_mode.lower()
    if normalized_mode != "markdown":
        return text, parse_mode

    plain_text = text.replace("`", "").replace("*", "")
    return plain_text, None


def _is_message_not_modified_error(error: Exception) -> bool:
    """Проверяет, что ошибка редактирования связана с отсутствием изменений."""

    text = str(error).lower()
    return "not modified" in text or "message is same" in text


def register_vk_guest_handlers(
    bot: Any,
    adapter: VkIdentityAdapter,
    delivery_processor: PendingModeratorDeliveryProcessor | None = None,
) -> None:
    """Регистрирует обработчики команд/кнопок VK-бота."""

    router_logger = logger.bind(platform="vk", component="router")
    delivery_lock = asyncio.Lock()

    async def _try_process_pending_deliveries() -> None:
        """Пытается доставить pending-сообщения модератора без влияния на UX пользователя."""

        delivery_logger = router_logger.bind(stage="pending_delivery")
        if delivery_processor is None:
            return
        if delivery_lock.locked():
            delivery_logger.debug("Пропуск доставки pending: предыдущий проход еще выполняется.")
            return

        async with delivery_lock:
            async def _send_message(target_external_id: str, text: str) -> None:
                await bot.api.messages.send(
                    user_id=int(target_external_id),
                    random_id=0,
                    message=text,
                )

            try:
                sent_count, failed_count = await delivery_processor.process_once(sender=_send_message, limit=20)
                delivery_logger.debug(
                    "Доставка pending завершена. sent={sent}, failed={failed}.",
                    sent=sent_count,
                    failed=failed_count,
                )
            except Exception:  # noqa: BLE001
                # На MVP-этапе не прерываем пользовательский сценарий из-за сбоя доставки.
                delivery_logger.exception("Ошибка при обработке pending-сообщений модератора.")
                return

    @bot.on.private_message(text=["/start", "start", "Start", "начать", "Начать"])
    async def start_handler(message: Any) -> None:
        event_logger = router_logger.bind(stage="start_command", user_id=str(message.from_id))
        event_logger.debug("Получена стартовая команда.")
        await _try_process_pending_deliveries()
        response = adapter.handle_start(vk_user_id=int(message.from_id))
        event_logger.info("Стартовый ответ сформирован.")
        await _send_response(message, response)

    @bot.on.private_message(text=["/menu", "menu", "Меню", "меню", "Главное меню"])
    async def menu_handler(message: Any) -> None:
        event_logger = router_logger.bind(stage="menu_command", user_id=str(message.from_id))
        event_logger.debug("Получена команда меню.")
        await _try_process_pending_deliveries()
        response = adapter.handle_incoming(
            vk_user_id=int(message.from_id),
            text="/menu",
            payload=None,
        )
        event_logger.info("Команда меню обработана.")
        await _send_response(message, response)

    @bot.on.private_message(text=["/legacy", "legacy", "Legacy", "обновить профиль"])
    async def legacy_handler(message: Any) -> None:
        event_logger = router_logger.bind(stage="legacy_command", user_id=str(message.from_id))
        event_logger.debug("Получена команда legacy.")
        await _try_process_pending_deliveries()
        response = adapter.handle_legacy_start(vk_user_id=int(message.from_id))
        event_logger.info("Legacy-команда обработана.")
        await _send_response(message, response)

    @bot.on.private_message()
    async def generic_handler(message: Any) -> None:
        event_logger = router_logger.bind(stage="text_input", user_id=str(message.from_id))
        await _try_process_pending_deliveries()
        payload = message.get_payload_json() or {}
        text = message.text or ""
        event_logger.debug("Получено входящее сообщение. text={text}.", text=text)

        # Защищаемся от дублирования start/menu обработчиков.
        lowered = text.strip().lower()
        if lowered in {
            "/start",
            "start",
            "начать",
            "/menu",
            "menu",
            "меню",
            "главное меню",
            "/legacy",
            "legacy",
            "обновить профиль",
        }:
            return

        # Если пришёл payload с командой меню, отдаем приоритет payload.
        parsed_payload = payload if resolve_action_from_vk_payload(payload) is not None else None
        response = adapter.handle_incoming(
            vk_user_id=int(message.from_id),
            text=text,
            payload=parsed_payload,
        )
        event_logger.info("Входящее сообщение обработано.")
        await _send_response(message, response)

    @bot.on.raw_event(GroupEventType.MESSAGE_EVENT, dataclass=MessageEvent, blocking=False)
    async def callback_handler(event: MessageEvent) -> None:
        """Обрабатывает inline-callback VK и перерисовывает текущее сообщение."""

        event_logger = router_logger.bind(stage="callback", user_id=str(event.user_id))
        await _try_process_pending_deliveries()
        payload = event.get_payload_json() or {}
        action = resolve_action_from_vk_payload(payload if isinstance(payload, dict) else None)
        if action is None:
            return

        response = adapter.handle_incoming(
            vk_user_id=int(event.user_id),
            text="",
            payload=payload,
        )
        event_logger.info("Callback обработан. action={action}.", action=action.value)

        await event.send_empty_answer()
        await _send_event_response(event, response)


async def _send_response(message: Any, response: VkAdapterResponse) -> None:
    """Отправляет ответ адаптера в чат VK."""

    keyboard_json = render_vk_keyboard(response.screen)
    parse_mode = response.parse_mode
    if parse_mode is None and response.screen is not None:
        parse_mode = response.screen.parse_mode
    message_text, parse_mode = _normalize_vk_message(response.text, parse_mode)
    kwargs: dict[str, Any] = {}
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    if keyboard_json is None:
        await message.answer(message_text, **kwargs)
        return
    await message.answer(message_text, keyboard=keyboard_json, **kwargs)


async def _send_event_response(event: MessageEvent, response: VkAdapterResponse) -> None:
    """Пытается обновить исходное callback-сообщение, иначе отправляет новое."""

    keyboard_json = render_vk_keyboard(response.screen)
    parse_mode = response.parse_mode
    if parse_mode is None and response.screen is not None:
        parse_mode = response.screen.parse_mode
    message_text, parse_mode = _normalize_vk_message(response.text, parse_mode)
    kwargs: dict[str, Any] = {}
    if keyboard_json is not None:
        kwargs["keyboard"] = keyboard_json
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode

    try:
        if event.conversation_message_id is not None:
            await event.edit_message(message=message_text, **kwargs)
            return
    except Exception as error:  # noqa: BLE001
        if _is_message_not_modified_error(error):
            # Сообщение уже в актуальном состоянии — дополнительная отправка не нужна.
            return
        # Фолбэк на отправку нового сообщения, если редактирование невозможно.
        pass

    await event.send_message(message=message_text, **kwargs)
