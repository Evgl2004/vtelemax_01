"""Роутер VK-адаптера (vkbottle) для гостевых сценариев."""

from __future__ import annotations

import asyncio
from typing import Any

from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor

from .identity_adapter import VkAdapterResponse, VkIdentityAdapter
from .keyboard_renderer import render_vk_keyboard
from .payloads import resolve_action_from_vk_payload


def register_vk_guest_handlers(
    bot: Any,
    adapter: VkIdentityAdapter,
    delivery_processor: PendingModeratorDeliveryProcessor | None = None,
) -> None:
    """Регистрирует обработчики команд/кнопок VK-бота."""

    delivery_lock = asyncio.Lock()

    async def _try_process_pending_deliveries() -> None:
        """Пытается доставить pending-сообщения модератора без влияния на UX пользователя."""

        if delivery_processor is None:
            return
        if delivery_lock.locked():
            return

        async with delivery_lock:
            async def _send_message(target_external_id: str, text: str) -> None:
                await bot.api.messages.send(
                    user_id=int(target_external_id),
                    random_id=0,
                    message=text,
                )

            try:
                await delivery_processor.process_once(sender=_send_message, limit=20)
            except Exception:  # noqa: BLE001
                # На MVP-этапе не прерываем пользовательский сценарий из-за сбоя доставки.
                return

    @bot.on.private_message(text=["/start", "start", "Start", "начать", "Начать"])
    async def start_handler(message: Any) -> None:
        await _try_process_pending_deliveries()
        response = adapter.handle_start(vk_user_id=int(message.from_id))
        await _send_response(message, response)

    @bot.on.private_message(text=["/menu", "menu", "Меню", "меню", "Главное меню"])
    async def menu_handler(message: Any) -> None:
        await _try_process_pending_deliveries()
        response = adapter.handle_incoming(
            vk_user_id=int(message.from_id),
            text="/menu",
            payload=None,
        )
        await _send_response(message, response)

    @bot.on.private_message(text=["/legacy", "legacy", "Legacy", "обновить профиль"])
    async def legacy_handler(message: Any) -> None:
        await _try_process_pending_deliveries()
        response = adapter.handle_legacy_start(vk_user_id=int(message.from_id))
        await _send_response(message, response)

    @bot.on.private_message()
    async def generic_handler(message: Any) -> None:
        await _try_process_pending_deliveries()
        payload = message.get_payload_json() or {}
        text = message.text or ""

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
        await _send_response(message, response)


async def _send_response(message: Any, response: VkAdapterResponse) -> None:
    """Отправляет ответ адаптера в чат VK."""

    keyboard_json = render_vk_keyboard(response.screen)
    if keyboard_json is None:
        await message.answer(response.text)
        return
    await message.answer(response.text, keyboard=keyboard_json)
