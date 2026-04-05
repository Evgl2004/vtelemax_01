"""Роутер VK-адаптера (vkbottle) для гостевых сценариев."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp
from loguru import logger
from vkbottle.bot import MessageEvent
from vkbottle_types.events import GroupEventType

from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor
from vtelemax.infrastructure import QrGenerationError, generate_qr_png_bytes

from .identity_adapter import VkAdapterResponse, VkIdentityAdapter
from .keyboard_renderer import render_vk_keyboard
from .payloads import resolve_action_from_vk_payload

_VK_REMOVE_KEYBOARD_JSON = json.dumps(
    {
        "buttons": [],
        "one_time": True,
    },
    ensure_ascii=False,
)


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


def _extract_field(source: Any, field: str) -> Any:
    """Безопасно извлекает поле из dict/объекта VK API."""

    if isinstance(source, dict):
        return source.get(field)
    return getattr(source, field, None)


def _build_vk_photo_attachment(photo: Any) -> str | None:
    """Собирает attachment-строку `photo<owner_id>_<id>[_access_key]`."""

    owner_id = _extract_field(photo, "owner_id")
    photo_id = _extract_field(photo, "id")
    access_key = _extract_field(photo, "access_key")
    if owner_id is None or photo_id is None:
        return None

    attachment = f"photo{owner_id}_{photo_id}"
    if access_key:
        attachment = f"{attachment}_{access_key}"
    return attachment


async def _upload_vk_png_for_messages(*, ctx_api: Any, peer_id: int, image_bytes: bytes) -> str | None:
    """Загружает PNG в VK и возвращает attachment для отправки в личные сообщения."""

    upload_info = await ctx_api.photos.get_messages_upload_server(peer_id=peer_id)
    upload_url = _extract_field(upload_info, "upload_url")
    if not upload_url:
        return None

    form = aiohttp.FormData()
    form.add_field(
        "photo",
        image_bytes,
        filename="virtual_card_qr.png",
        content_type="image/png",
    )
    async with aiohttp.ClientSession() as session:
        async with session.post(
            upload_url,
            data=form,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            if response.status != 200:
                return None
            upload_result = await response.json(content_type=None)

    photo_value = upload_result.get("photo")
    server_value = upload_result.get("server")
    hash_value = upload_result.get("hash")
    if not photo_value or server_value is None or not hash_value:
        return None

    saved_photos = await ctx_api.photos.save_messages_photo(
        photo=photo_value,
        server=server_value,
        hash=hash_value,
    )
    if not saved_photos:
        return None
    return _build_vk_photo_attachment(saved_photos[0])


async def _send_virtual_card_qr_messages(*, ctx_api: Any, peer_id: int, card_numbers: tuple[str, ...]) -> None:
    """Отправляет QR-коды карт в VK перед итоговым текстовым ответом.

    Для лучшего UX отправляем картинку и текст отдельными сообщениями:
    1) сообщение только с изображением QR;
    2) отдельное сообщение с номером карты.
    """

    if not card_numbers:
        return

    qr_logger = logger.bind(platform="vk", component="router", stage="virtual_card_qr", user_id=str(peer_id))
    for index, card_number in enumerate(card_numbers, start=1):
        try:
            qr_png = generate_qr_png_bytes(card_number)
            attachment = await _upload_vk_png_for_messages(
                ctx_api=ctx_api,
                peer_id=peer_id,
                image_bytes=qr_png,
            )
        except (QrGenerationError, ValueError):
            qr_logger.warning("Не удалось сгенерировать QR для карты #{index}.", index=index)
            continue
        except Exception:  # noqa: BLE001
            qr_logger.exception("Ошибка отправки QR в VK для карты #{index}.", index=index)
            continue

        if attachment is None:
            qr_logger.warning("Не удалось загрузить QR в VK для карты #{index}.", index=index)
            continue

        try:
            await ctx_api.messages.send(
                peer_id=peer_id,
                random_id=0,
                message="",
                attachment=attachment,
            )
            await ctx_api.messages.send(
                peer_id=peer_id,
                random_id=0,
                message=f"💳 Карта: {card_number}",
            )
        except Exception:  # noqa: BLE001
            qr_logger.exception(
                "Ошибка отправки раздельного контента QR в VK для карты #{index}. Пробуем fallback-комбинацию.",
                index=index,
            )
            await ctx_api.messages.send(
                peer_id=peer_id,
                random_id=0,
                message=f"💳 Карта: {card_number}",
                attachment=attachment,
            )


def _extract_vk_peer_id(event: MessageEvent) -> int | None:
    """Извлекает peer_id из callback-события VK."""

    peer_id = getattr(event, "peer_id", None)
    if peer_id is not None:
        return int(peer_id)
    user_id = getattr(event, "user_id", None)
    if user_id is not None:
        return int(user_id)
    return None


async def _try_delete_callback_message(event: MessageEvent) -> None:
    """Пытается удалить исходное callback-сообщение перед отправкой нового контента."""

    ctx_api = getattr(event, "ctx_api", None)
    peer_id = _extract_vk_peer_id(event)
    cmid = getattr(event, "conversation_message_id", None)
    if ctx_api is None or peer_id is None or cmid is None:
        return

    delete_variants: tuple[dict[str, object], ...] = (
        {"peer_id": peer_id, "conversation_message_ids": [int(cmid)], "delete_for_all": 1},
        {"peer_id": peer_id, "conversation_message_ids": str(int(cmid)), "delete_for_all": 1},
        {"peer_id": peer_id, "cmids": [int(cmid)], "delete_for_all": 1},
        {"peer_id": peer_id, "cmids": str(int(cmid)), "delete_for_all": 1},
    )
    for payload in delete_variants:
        try:
            if hasattr(ctx_api, "request"):
                await ctx_api.request("messages.delete", payload)
            else:
                await ctx_api.messages.delete(**payload)
            return
        except Exception:  # noqa: BLE001
            continue


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
            # Для no-op и неизвестных payload обязательно подтверждаем callback,
            # чтобы у клиента не зависал индикатор ожидания.
            await event.send_empty_answer()
            if cmd == "noop":
                event_logger.debug("Получен noop callback пагинации, игнорируем без изменений.")
            else:
                event_logger.debug("Неизвестный callback payload, ответ отправлен без сценарного перехода.")
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

    if response.virtual_card_numbers:
        ctx_api = getattr(message, "ctx_api", None)
        peer_id = getattr(message, "peer_id", None)
        if ctx_api is not None and peer_id is not None:
            await _send_virtual_card_qr_messages(
                ctx_api=ctx_api,
                peer_id=int(peer_id),
                card_numbers=response.virtual_card_numbers,
            )

    keyboard_json = render_vk_keyboard(response.screen)
    parse_mode = response.parse_mode
    if parse_mode is None and response.screen is not None:
        parse_mode = response.screen.parse_mode
    message_text, parse_mode = _normalize_vk_message(response.text, parse_mode)
    kwargs: dict[str, Any] = {}
    if parse_mode is not None:
        kwargs["parse_mode"] = parse_mode
    kwargs["keyboard"] = keyboard_json if keyboard_json is not None else _VK_REMOVE_KEYBOARD_JSON
    await message.answer(message_text, **kwargs)


async def _send_event_response(event: MessageEvent, response: VkAdapterResponse) -> None:
    """Пытается обновить исходное callback-сообщение, иначе отправляет новое."""

    ctx_api = getattr(event, "ctx_api", None)
    peer_id = _extract_vk_peer_id(event)
    if response.virtual_card_numbers:
        await _try_delete_callback_message(event)
        if ctx_api is not None and peer_id is not None:
            await _send_virtual_card_qr_messages(
                ctx_api=ctx_api,
                peer_id=int(peer_id),
                card_numbers=response.virtual_card_numbers,
            )
        keyboard_json = render_vk_keyboard(response.screen)
        parse_mode = response.parse_mode
        if parse_mode is None and response.screen is not None:
            parse_mode = response.screen.parse_mode
        message_text, parse_mode = _normalize_vk_message(response.text, parse_mode)
        kwargs: dict[str, Any] = {}
        kwargs["keyboard"] = keyboard_json if keyboard_json is not None else _VK_REMOVE_KEYBOARD_JSON
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        await event.send_message(message=message_text, **kwargs)
        return

    keyboard_json = render_vk_keyboard(response.screen)
    parse_mode = response.parse_mode
    if parse_mode is None and response.screen is not None:
        parse_mode = response.screen.parse_mode
    message_text, parse_mode = _normalize_vk_message(response.text, parse_mode)
    kwargs: dict[str, Any] = {}
    kwargs["keyboard"] = keyboard_json if keyboard_json is not None else _VK_REMOVE_KEYBOARD_JSON
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
