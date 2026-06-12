"""Роутер VK-адаптера (vkbottle) для гостевых сценариев."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlparse

import aiohttp
from loguru import logger
from vkbottle.bot import MessageEvent
from vkbottle_types.events import GroupEventType

from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor
from vtelemax.core import (
    GuestMenuAction,
    PendingModeratorDelivery,
    SupportMessageAuthor,
    build_iiko_sync_pending_screen,
    is_coupon_delivery_text,
)
from vtelemax.infrastructure import QrGenerationError, generate_qr_png_bytes

from .identity_adapter import (
    USER_TICKETS_NEXT_PAGE_PREFIX,
    USER_TICKETS_PREV_PAGE_PREFIX,
    USER_TICKET_DETAILS_PREFIX,
    USER_TICKET_REPLY_PREFIX,
    VkAdapterResponse,
    VkIdentityAdapter,
)
from .menu_adapter import COUPON_SCOPE_PREFIX, COUPON_SHOW_PREFIX, MOD_PHONE_SHOW_PREFIX, MOD_REPLY_PREFIX
from .keyboard_renderer import render_vk_keyboard
from .payloads import resolve_action_from_vk_payload

_VK_REMOVE_KEYBOARD_JSON = json.dumps(
    {
        "buttons": [],
        "one_time": True,
    },
    ensure_ascii=False,
)
_VK_QR_UPLOAD_TIMEOUT = aiohttp.ClientTimeout(total=8, connect=4, sock_read=6)
_VK_QR_UPLOAD_ATTEMPTS = 3
_VK_QR_UPLOAD_RETRY_DELAY_SECONDS = 0.75


@dataclass(frozen=True, slots=True)
class _VirtualCardQrDeliveryResult:
    """Итог доставки QR виртуальных карт в VK.

    Нужен, чтобы финальное сообщение не обещало пользователю QR-коды,
    если upload изображения в VK завис или отвалился по таймауту.
    """

    total: int
    sent: int
    failed: int
_GUEST_MESSAGE_CLOSE_CMD = "guest_msg_close"


def _build_vk_moderation_notification_keyboard_json(ticket_id: str) -> str:
    """Возвращает inline-клавиатуру VK с кнопкой быстрого ответа модератора."""

    reply_payload = {"cmd": f"{MOD_REPLY_PREFIX}{ticket_id}_new_1"}
    phone_payload = {"cmd": f"{MOD_PHONE_SHOW_PREFIX}{ticket_id}_new_1"}
    return json.dumps(
        {
            "one_time": False,
            "inline": True,
            "buttons": [
                [
                    {
                        "action": {
                            "type": "callback",
                            "label": "✍️ Ответить",
                            "payload": json.dumps(reply_payload, ensure_ascii=False),
                        },
                        "color": "primary",
                    },
                    {
                        "action": {
                            "type": "callback",
                            "label": "📞 Телефон гостя",
                            "payload": json.dumps(phone_payload, ensure_ascii=False),
                        },
                        "color": "secondary",
                    },
                ]
            ],
        },
        ensure_ascii=False,
    )


def _build_vk_guest_message_close_keyboard_json() -> str:
    """Возвращает inline-клавиатуру VK с кнопкой закрытия входящего сообщения."""

    payload = {"cmd": _GUEST_MESSAGE_CLOSE_CMD}
    return json.dumps(
        {
            "one_time": False,
            "inline": True,
            "buttons": [
                [
                    {
                        "action": {
                            "type": "callback",
                            "label": "❌ Закрыть",
                            "payload": json.dumps(payload, ensure_ascii=False),
                        },
                        "color": "secondary",
                    }
                ]
            ],
        },
        ensure_ascii=False,
    )


def _build_vk_coupon_delivery_keyboard_json() -> str:
    """Возвращает inline-кнопку VK для перехода из рассылки в меню купонов."""

    payload = {"cmd": GuestMenuAction.COUPONS.value}
    return json.dumps(
        {
            "one_time": False,
            "inline": True,
            "buttons": [
                [
                    {
                        "action": {
                            "type": "callback",
                            "label": "🎟️ Перейти к купонам",
                            "payload": json.dumps(payload, ensure_ascii=False),
                        },
                        "color": "primary",
                    }
                ]
            ],
        },
        ensure_ascii=False,
    )


def build_vk_pending_delivery_sender(
    bot: Any,
) -> Callable[[PendingModeratorDelivery, str], Awaitable[None]]:
    """Строит sender-функцию для доставки pending-сообщений в VK."""

    async def _send_message(delivery: PendingModeratorDelivery, text: str) -> None:
        kwargs: dict[str, Any] = {}
        if is_coupon_delivery_text(text):
            kwargs["keyboard"] = _build_vk_coupon_delivery_keyboard_json()
        elif delivery.author == SupportMessageAuthor.SYSTEM:
            kwargs["keyboard"] = _build_vk_moderation_notification_keyboard_json(str(delivery.ticket_id))
        elif delivery.author == SupportMessageAuthor.MODERATOR:
            kwargs["keyboard"] = _build_vk_guest_message_close_keyboard_json()
        await bot.api.messages.send(
            user_id=int(delivery.target_external_id),
            random_id=0,
            message=text,
            **kwargs,
        )

    return _send_message


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


def _build_vk_png_upload_form(image_bytes: bytes) -> aiohttp.FormData:
    """Создает свежую multipart-форму для одной попытки upload в VK."""

    form = aiohttp.FormData()
    form.add_field(
        "photo",
        image_bytes,
        filename="virtual_card_qr.png",
        content_type="image/png",
    )
    return form


def _safe_upload_host(upload_url: str) -> str:
    """Возвращает host upload URL без path/query, чтобы не писать секреты в лог."""

    try:
        return urlparse(upload_url).netloc or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


async def _upload_vk_png_for_messages(*, ctx_api: Any, peer_id: int, image_bytes: bytes) -> str | None:
    """Загружает PNG в VK и возвращает attachment для отправки в личные сообщения."""

    upload_logger = logger.bind(
        platform="vk",
        component="router",
        stage="vk_qr_upload",
        user_id=str(peer_id),
    )
    upload_info = await ctx_api.photos.get_messages_upload_server(peer_id=peer_id)
    upload_url = _extract_field(upload_info, "upload_url")
    if not upload_url:
        upload_logger.warning("VK не вернул upload_url для QR / VK did not return QR upload_url.")
        return None

    upload_host = _safe_upload_host(str(upload_url))
    upload_result: dict[str, Any] | None = None
    for attempt in range(1, _VK_QR_UPLOAD_ATTEMPTS + 1):
        started_at = time.monotonic()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    str(upload_url),
                    data=_build_vk_png_upload_form(image_bytes),
                    timeout=_VK_QR_UPLOAD_TIMEOUT,
                ) as response:
                    duration_ms = int((time.monotonic() - started_at) * 1000)
                    if response.status != 200:
                        upload_logger.warning(
                            "VK QR upload failed / Ошибка upload QR в VK. "
                            "host={host}, attempt={attempt}/{attempts}, status={status}, duration_ms={duration_ms}.",
                            host=upload_host,
                            attempt=attempt,
                            attempts=_VK_QR_UPLOAD_ATTEMPTS,
                            status=response.status,
                            duration_ms=duration_ms,
                        )
                    else:
                        upload_result = await response.json(content_type=None)
                        upload_logger.info(
                            "VK QR upload completed / Upload QR в VK завершен. "
                            "host={host}, attempt={attempt}/{attempts}, duration_ms={duration_ms}.",
                            host=upload_host,
                            attempt=attempt,
                            attempts=_VK_QR_UPLOAD_ATTEMPTS,
                            duration_ms=duration_ms,
                        )
                        break
        except (TimeoutError, aiohttp.ClientError) as error:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            upload_logger.warning(
                "VK QR upload retryable failure / Временная ошибка upload QR в VK. "
                "host={host}, attempt={attempt}/{attempts}, duration_ms={duration_ms}, error={error}.",
                host=upload_host,
                attempt=attempt,
                attempts=_VK_QR_UPLOAD_ATTEMPTS,
                duration_ms=duration_ms,
                error=str(error) or type(error).__name__,
            )

        if upload_result is not None:
            break
        if attempt < _VK_QR_UPLOAD_ATTEMPTS:
            await asyncio.sleep(_VK_QR_UPLOAD_RETRY_DELAY_SECONDS)

    if upload_result is None:
        upload_logger.warning(
            "VK QR upload exhausted / Исчерпаны попытки upload QR в VK. host={host}, attempts={attempts}.",
            host=upload_host,
            attempts=_VK_QR_UPLOAD_ATTEMPTS,
        )
        return None

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


async def _send_virtual_card_text_fallback(
    *,
    ctx_api: Any,
    peer_id: int,
    card_number: str,
    reason: str,
) -> None:
    """Отправляет номер карты текстом, если QR-картинку не удалось доставить."""

    try:
        await ctx_api.messages.send(
            peer_id=peer_id,
            random_id=0,
            message=(
                "⚠️ QR-код карты временно не удалось отправить.\n"
                f"Причина: {reason}\n"
                f"💳 Номер карты: {card_number}"
            ),
        )
    except Exception:  # noqa: BLE001
        logger.bind(
            platform="vk",
            component="router",
            stage="virtual_card_qr",
            user_id=str(peer_id),
        ).exception("Не удалось отправить текстовый fallback номера карты в VK.")


async def _send_virtual_card_qr_messages(
    *,
    ctx_api: Any,
    peer_id: int,
    card_numbers: tuple[str, ...],
) -> _VirtualCardQrDeliveryResult:
    """Отправляет QR-коды карт в VK перед итоговым текстовым ответом.

    Для лучшего UX отправляем картинку и текст отдельными сообщениями:
    1) сообщение только с изображением QR;
    2) отдельное сообщение с номером карты.
    """

    if not card_numbers:
        return _VirtualCardQrDeliveryResult(total=0, sent=0, failed=0)

    qr_logger = logger.bind(platform="vk", component="router", stage="virtual_card_qr", user_id=str(peer_id))
    sent_count = 0
    failed_count = 0
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
            failed_count += 1
            await _send_virtual_card_text_fallback(
                ctx_api=ctx_api,
                peer_id=peer_id,
                card_number=card_number,
                reason="ошибка генерации QR",
            )
            continue
        except Exception:  # noqa: BLE001
            qr_logger.exception("Ошибка отправки QR в VK для карты #{index}.", index=index)
            failed_count += 1
            await _send_virtual_card_text_fallback(
                ctx_api=ctx_api,
                peer_id=peer_id,
                card_number=card_number,
                reason="таймаут или ошибка загрузки изображения",
            )
            continue

        if attachment is None:
            qr_logger.warning("Не удалось загрузить QR в VK для карты #{index}.", index=index)
            failed_count += 1
            await _send_virtual_card_text_fallback(
                ctx_api=ctx_api,
                peer_id=peer_id,
                card_number=card_number,
                reason="VK не принял изображение QR",
            )
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
            sent_count += 1
        except Exception:  # noqa: BLE001
            qr_logger.exception(
                "Ошибка отправки раздельного контента QR в VK для карты #{index}. Пробуем fallback-комбинацию.",
                index=index,
            )
            try:
                await ctx_api.messages.send(
                    peer_id=peer_id,
                    random_id=0,
                    message=f"💳 Карта: {card_number}",
                    attachment=attachment,
                )
                sent_count += 1
            except Exception:  # noqa: BLE001
                failed_count += 1
                qr_logger.exception(
                    "Fallback-отправка QR в VK тоже не удалась для карты #{index}.",
                    index=index,
                )
                await _send_virtual_card_text_fallback(
                    ctx_api=ctx_api,
                    peer_id=peer_id,
                    card_number=card_number,
                    reason="ошибка отправки сообщения с QR",
                )

    return _VirtualCardQrDeliveryResult(
        total=len(card_numbers),
        sent=sent_count,
        failed=failed_count,
    )


def _with_virtual_card_delivery_notice(
    response: VkAdapterResponse,
    result: _VirtualCardQrDeliveryResult,
) -> VkAdapterResponse:
    """Уточняет финальный текст, если VK не принял QR-картинку карты."""

    if result.total == 0 or result.failed == 0:
        return response

    if result.sent == 0:
        notice = (
            "⚠️ QR-код карты временно не удалось отправить. "
            "Номер карты отправлен отдельным сообщением выше."
        )
    else:
        notice = (
            "⚠️ Часть QR-кодов карт временно не удалось отправить. "
            "Номера таких карт отправлены отдельными сообщениями выше."
        )

    text = response.text
    inaccurate_phrases = (
        "🪪 Выше представлены QR-коды ваших карт.",
        "🪪 Список виртуальных карт и QR-коды отправлены выше.",
    )
    for phrase in inaccurate_phrases:
        if phrase in text:
            return replace(response, text=text.replace(phrase, notice, 1))
    return replace(response, text=f"{notice}\n\n{text}")


async def _send_coupon_qr_message(*, ctx_api: Any, peer_id: int, response: VkAdapterResponse) -> None:
    """Отправляет QR купона в VK отдельным сообщением перед текстовой карточкой."""

    coupon_payload = str(response.coupon_qr_payload or "").strip()
    if not coupon_payload:
        return

    qr_logger = logger.bind(platform="vk", component="router", stage="coupon_qr", user_id=str(peer_id))
    try:
        qr_png = generate_qr_png_bytes(coupon_payload)
        attachment = await _upload_vk_png_for_messages(
            ctx_api=ctx_api,
            peer_id=peer_id,
            image_bytes=qr_png,
        )
    except (QrGenerationError, ValueError):
        qr_logger.warning("Не удалось сгенерировать QR купона / Failed to generate coupon QR.")
        return
    except Exception:  # noqa: BLE001
        qr_logger.exception("Ошибка отправки QR купона в VK / Failed to send coupon QR in VK.")
        return

    if attachment is None:
        qr_logger.warning("Не удалось загрузить QR купона в VK / Failed to upload coupon QR to VK.")
        return

    try:
        await ctx_api.messages.send(
            peer_id=peer_id,
            random_id=0,
            message=response.coupon_qr_caption or "🎟️ Купон",
            attachment=attachment,
        )
    except Exception:  # noqa: BLE001
        qr_logger.exception(
            "Не удалось отправить QR купона вложением в VK / Failed to send coupon QR attachment in VK."
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

    await _try_delete_message_by_cmid(
        ctx_api=ctx_api,
        peer_id=int(peer_id),
        cmid=int(cmid),
    )


async def _try_delete_message_by_cmid(*, ctx_api: Any, peer_id: int, cmid: int) -> bool:
    """Пытается удалить конкретное сообщение VK по `conversation_message_id`."""

    delete_variants: tuple[dict[str, object], ...] = (
        {"peer_id": peer_id, "conversation_message_ids": [cmid], "delete_for_all": 1},
        {"peer_id": peer_id, "conversation_message_ids": str(cmid), "delete_for_all": 1},
        {"peer_id": peer_id, "cmids": [cmid], "delete_for_all": 1},
        {"peer_id": peer_id, "cmids": str(cmid), "delete_for_all": 1},
    )
    for payload in delete_variants:
        try:
            if hasattr(ctx_api, "request"):
                await ctx_api.request("messages.delete", payload)
            else:
                await ctx_api.messages.delete(**payload)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def register_vk_guest_handlers(
    bot: Any,
    adapter: VkIdentityAdapter,
    delivery_processor: PendingModeratorDeliveryProcessor | None = None,
    delivery_lock: asyncio.Lock | None = None,
    delivery_batch_limit: int = 20,
) -> None:
    """Регистрирует обработчики команд/кнопок VK-бота."""

    router_logger = logger.bind(platform="vk", component="router")
    shared_delivery_lock = delivery_lock or asyncio.Lock()
    support_prompt_cmid_by_user_id: dict[int, int] = {}
    moderation_reply_prompt_cmid_by_user_id: dict[int, int] = {}

    def _remember_support_prompt(*, vk_user_id: int, cmid: int | None) -> None:
        """Запоминает cmid технического экрана ввода вопроса."""

        if cmid is None:
            return
        support_prompt_cmid_by_user_id[vk_user_id] = int(cmid)

    def _remember_moderation_reply_prompt(*, vk_user_id: int, cmid: int | None) -> None:
        """Запоминает cmid технического экрана ввода ответа модератора."""

        if cmid is None:
            return
        moderation_reply_prompt_cmid_by_user_id[vk_user_id] = int(cmid)

    async def _cleanup_support_prompt(
        *,
        vk_user_id: int,
        ctx_api: Any | None,
        peer_id: int | None,
    ) -> None:
        """Удаляет технический экран «Введите ваш вопрос» после создания тикета."""

        cmid = support_prompt_cmid_by_user_id.pop(vk_user_id, None)
        if cmid is None or ctx_api is None or peer_id is None:
            return
        await _try_delete_message_by_cmid(ctx_api=ctx_api, peer_id=int(peer_id), cmid=cmid)

    async def _cleanup_moderation_reply_prompt(
        *,
        vk_user_id: int,
        ctx_api: Any | None,
        peer_id: int | None,
        keep_cmid: int | None = None,
    ) -> None:
        """Удаляет технический экран ввода ответа модератора."""

        cmid = moderation_reply_prompt_cmid_by_user_id.pop(vk_user_id, None)
        if cmid is None or ctx_api is None or peer_id is None:
            return
        if keep_cmid is not None and int(cmid) == int(keep_cmid):
            return
        await _try_delete_message_by_cmid(ctx_api=ctx_api, peer_id=int(peer_id), cmid=cmid)

    async def _try_process_pending_deliveries() -> None:
        """Пытается доставить pending-сообщения модератора без влияния на UX пользователя."""

        delivery_logger = router_logger.bind(stage="pending_delivery")
        if delivery_processor is None:
            return
        if shared_delivery_lock.locked():
            delivery_logger.debug("Пропуск доставки pending: предыдущий проход еще выполняется.")
            return

        async with shared_delivery_lock:
            try:
                sent_count, failed_count = await delivery_processor.process_once(
                    sender=build_vk_pending_delivery_sender(bot),
                    limit=delivery_batch_limit,
                )
                delivery_logger.debug(
                    "Доставка pending завершена. sent={sent}, failed={failed}.",
                    sent=sent_count,
                    failed=failed_count,
                )
            except Exception:  # noqa: BLE001
                # На MVP-этапе не прерываем пользовательский сценарий из-за сбоя доставки.
                delivery_logger.exception("Ошибка при обработке pending-сообщений модератора.")
                return

    @bot.on.private_message(text=["/start", "/Start", "начать", "Начать"])
    async def start_handler(message: Any) -> None:
        event_logger = router_logger.bind(stage="start_command", user_id=str(message.from_id))
        event_logger.debug("Получена стартовая команда.")
        await _try_process_pending_deliveries()
        support_prompt_cmid_by_user_id.pop(int(message.from_id), None)
        moderation_reply_prompt_cmid_by_user_id.pop(int(message.from_id), None)
        response = adapter.handle_start(vk_user_id=int(message.from_id))
        event_logger.info("Стартовый ответ сформирован.")
        await _send_response(message, response)

    @bot.on.private_message()
    async def generic_handler(message: Any) -> None:
        event_logger = router_logger.bind(stage="text_input", user_id=str(message.from_id))
        await _try_process_pending_deliveries()
        payload = message.get_payload_json() or {}
        text = message.text or ""
        event_logger.debug("Получено входящее сообщение. text={text}.", text=text)

        # Защищаемся от дублирования start-обработчика.
        lowered = text.strip().lower()
        if lowered in {
            "/start",
            "начать",
        }:
            return

        # Если пришёл payload с командой меню, отдаем приоритет payload.
        parsed_payload = payload if resolve_action_from_vk_payload(payload) is not None else None
        response = adapter.handle_incoming(
            vk_user_id=int(message.from_id),
            text=text,
            payload=parsed_payload,
        )
        screen_id = response.screen.screen_id if response.screen is not None else None
        if screen_id == "support_question_confirmation":
            await _cleanup_support_prompt(
                vk_user_id=int(message.from_id),
                ctx_api=getattr(message, "ctx_api", None),
                peer_id=getattr(message, "peer_id", None),
            )
        elif screen_id != "support_question":
            support_prompt_cmid_by_user_id.pop(int(message.from_id), None)
        if screen_id == "moderation_reply_cancel":
            pass
        elif screen_id is not None and screen_id.startswith("moderation_"):
            await _cleanup_moderation_reply_prompt(
                vk_user_id=int(message.from_id),
                ctx_api=getattr(message, "ctx_api", None),
                peer_id=getattr(message, "peer_id", None),
            )
        else:
            moderation_reply_prompt_cmid_by_user_id.pop(int(message.from_id), None)
        event_logger.info("Входящее сообщение обработано.")
        await _send_response(message, response)

    @bot.on.raw_event(GroupEventType.MESSAGE_EVENT, dataclass=MessageEvent, blocking=False)
    async def callback_handler(event: MessageEvent) -> None:
        """Обрабатывает inline-callback VK и перерисовывает текущее сообщение."""

        event_logger = router_logger.bind(stage="callback", user_id=str(event.user_id))
        payload = event.get_payload_json() or {}

        # Проверка префиксов тикетов
        cmd = ""
        if isinstance(payload, dict):
            cmd = str(payload.get("cmd", "")).strip()
        if cmd == _GUEST_MESSAGE_CLOSE_CMD:
            await event.send_empty_answer()
            await _try_delete_callback_message(event)
            event_logger.info("Callback закрытия сообщения гостя обработан.")
            return

        await _try_process_pending_deliveries()
        if (
            cmd.startswith(USER_TICKET_DETAILS_PREFIX)
            or cmd.startswith(USER_TICKET_REPLY_PREFIX)
            or cmd.startswith(USER_TICKETS_PREV_PAGE_PREFIX)
            or cmd.startswith(USER_TICKETS_NEXT_PAGE_PREFIX)
            or cmd.startswith("mod_")
            or cmd.startswith(COUPON_SCOPE_PREFIX)
            or cmd.startswith(COUPON_SHOW_PREFIX)
        ):
            # Обрабатываем через адаптер
            response = adapter.handle_incoming(
                vk_user_id=int(event.user_id),
                text="",
                payload=payload,
            )
            screen_id = response.screen.screen_id if response.screen is not None else None
            if screen_id == "support_question" and event.conversation_message_id is not None:
                _remember_support_prompt(
                    vk_user_id=int(event.user_id),
                    cmid=int(event.conversation_message_id),
                )
            elif cmd != GuestMenuAction.SUPPORT_QUESTION_FROM_LIST.value:
                support_prompt_cmid_by_user_id.pop(int(event.user_id), None)
            current_cmid = int(event.conversation_message_id) if event.conversation_message_id is not None else None
            if screen_id == "moderation_reply_cancel" and current_cmid is not None:
                _remember_moderation_reply_prompt(
                    vk_user_id=int(event.user_id),
                    cmid=current_cmid,
                )
            elif screen_id is not None and screen_id.startswith("moderation_"):
                await _cleanup_moderation_reply_prompt(
                    vk_user_id=int(event.user_id),
                    ctx_api=getattr(event, "ctx_api", None),
                    peer_id=_extract_vk_peer_id(event),
                    keep_cmid=current_cmid,
                )
            else:
                moderation_reply_prompt_cmid_by_user_id.pop(int(event.user_id), None)
            event_logger.info("Callback тикета обработан. cmd={cmd}.", cmd=cmd)
            await event.send_empty_answer()
            await _send_event_response(event, response)
            return
        
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

        await event.send_empty_answer()
        if action in {
            GuestMenuAction.NOTIFY_YES,
            GuestMenuAction.NOTIFY_NO,
            GuestMenuAction.RETRY_IIKO_SYNC,
        }:
            pending_screen = build_iiko_sync_pending_screen()
            await _send_event_response(
                event,
                VkAdapterResponse(text=pending_screen.text, screen=None),
            )

        response = adapter.handle_incoming(
            vk_user_id=int(event.user_id),
            text="",
            payload=payload,
        )
        screen_id = response.screen.screen_id if response.screen is not None else None
        if screen_id == "support_question" and event.conversation_message_id is not None:
            _remember_support_prompt(
                vk_user_id=int(event.user_id),
                cmid=int(event.conversation_message_id),
            )
        elif action not in {GuestMenuAction.SUPPORT_QUESTION, GuestMenuAction.SUPPORT_QUESTION_FROM_LIST}:
            support_prompt_cmid_by_user_id.pop(int(event.user_id), None)
        current_cmid = int(event.conversation_message_id) if event.conversation_message_id is not None else None
        if screen_id == "moderation_reply_cancel" and current_cmid is not None:
            _remember_moderation_reply_prompt(
                vk_user_id=int(event.user_id),
                cmid=current_cmid,
            )
        elif screen_id is not None and screen_id.startswith("moderation_"):
            await _cleanup_moderation_reply_prompt(
                vk_user_id=int(event.user_id),
                ctx_api=getattr(event, "ctx_api", None),
                peer_id=_extract_vk_peer_id(event),
                keep_cmid=current_cmid,
            )
        else:
            moderation_reply_prompt_cmid_by_user_id.pop(int(event.user_id), None)
        event_logger.info("Callback обработан. action={action}.", action=action.value)
        await _send_event_response(event, response)


async def _send_response(message: Any, response: VkAdapterResponse) -> None:
    """Отправляет ответ адаптера в чат VK."""

    if response.virtual_card_numbers:
        ctx_api = getattr(message, "ctx_api", None)
        peer_id = getattr(message, "peer_id", None)
        if ctx_api is not None and peer_id is not None:
            delivery_result = await _send_virtual_card_qr_messages(
                ctx_api=ctx_api,
                peer_id=int(peer_id),
                card_numbers=response.virtual_card_numbers,
            )
        else:
            delivery_result = _VirtualCardQrDeliveryResult(
                total=len(response.virtual_card_numbers),
                sent=0,
                failed=len(response.virtual_card_numbers),
            )
        response = _with_virtual_card_delivery_notice(response, delivery_result)
    if response.coupon_qr_payload:
        ctx_api = getattr(message, "ctx_api", None)
        peer_id = getattr(message, "peer_id", None)
        if ctx_api is not None and peer_id is not None:
            await _send_coupon_qr_message(ctx_api=ctx_api, peer_id=int(peer_id), response=response)

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
            delivery_result = await _send_virtual_card_qr_messages(
                ctx_api=ctx_api,
                peer_id=int(peer_id),
                card_numbers=response.virtual_card_numbers,
            )
        else:
            delivery_result = _VirtualCardQrDeliveryResult(
                total=len(response.virtual_card_numbers),
                sent=0,
                failed=len(response.virtual_card_numbers),
            )
        response = _with_virtual_card_delivery_notice(response, delivery_result)
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

    if response.coupon_qr_payload:
        await _try_delete_callback_message(event)
        if ctx_api is not None and peer_id is not None:
            await _send_coupon_qr_message(ctx_api=ctx_api, peer_id=int(peer_id), response=response)
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
