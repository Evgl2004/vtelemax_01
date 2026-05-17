"""Роутер MAX-адаптера (maxapi) для гостевых сценариев."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import aiohttp
from loguru import logger

from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor
from vtelemax.core import (
    GuestMenuAction,
    PendingModeratorDelivery,
    SupportMessageAuthor,
    build_iiko_sync_pending_screen,
)
from vtelemax.infrastructure import QrGenerationError, generate_qr_png_bytes

from .identity_adapter import MaxAdapterResponse, MaxIdentityAdapter
from .keyboard_renderer import render_max_keyboard
from .menu_adapter import (
    MOD_PHONE_SHOW_PREFIX,
    MOD_REPLY_PREFIX,
    MaxGuestMenuAdapter,
)

_START_COMMANDS = {"/start", "начать"}
_GUEST_MESSAGE_CLOSE_PAYLOAD = "guest_msg_close"


_VCF_PHONE_PATTERN = re.compile(r"TEL[^:]*:([^\r\n]+)", flags=re.IGNORECASE)
_PHONE_SANITIZE_PATTERN = re.compile(r"[^0-9+]")
_MAX_CONTACT_RAW_UPDATE_ATTR = "_vtelemax_raw_update"
_MAX_CONTACT_HASH_FIELD_NAMES = (
    "hash",
    "contact_hash",
    "contactHash",
    "vcf_hash",
    "vcfHash",
    "signature",
    "sign",
)
_MAX_CONTACT_HASH_COUNTER_NAMES = (
    "hash_missing_total",
    "hash_present_total",
    "hash_verified_true_total",
    "hash_verified_false_total",
    "owner_match_true_total",
    "owner_match_false_total",
)
_MAXAPI_RAW_UPDATE_PATCHED = False


@dataclass(frozen=True, slots=True)
class _MaxContactAttachmentData:
    """Структурированные данные contact-вложения MAX."""

    phone_number: str | None
    vcf_info: str | None
    contact_hash: str | None
    max_user_id: int | None
    phone_source: str | None = None
    contact_hash_source: str | None = None
    contact_hash_present_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _MaxContactHashLookup:
    """Результат поиска hash в contact payload по известным путям."""

    value: str | None
    source: str | None
    present_paths: tuple[str, ...]


def _attach_raw_max_update(event_model: Any, raw_event: dict[str, Any]) -> None:
    """Прикрепляет сырой MAX update к pydantic-модели без изменения SDK-классов.

    В `maxapi==0.9.16` модель contact-вложения не содержит поле `payload.hash`.
    Поэтому мы сохраняем исходный JSON рядом с разобранным событием и читаем hash
    из него уже в нашем адаптере. Это локальная, обратимая прослойка: она не меняет
    сетевые вызовы SDK и не влияет на обработку событий других типов.
    """

    try:
        object.__setattr__(event_model, _MAX_CONTACT_RAW_UPDATE_ATTR, raw_event)
    except Exception:  # noqa: BLE001
        # Диагностика не должна ломать polling, если SDK изменит внутреннюю модель.
        return


def _patch_maxapi_raw_update_preservation() -> bool:
    """Включает сохранение сырого MAX update до pydantic-нормализации SDK.

    MAX присылает `attachments[].payload.hash` только для контакта, отправленного
    через `request_contact`. Текущая версия `maxapi` описывает contact payload без
    этого поля, из-за чего hash теряется при разборе. Патч заменяет только функцию
    преобразования updates внутри runtime-модуля SDK и добавляет к готовой модели
    приватный атрибут с исходным JSON.
    """

    global _MAXAPI_RAW_UPDATE_PATCHED
    if _MAXAPI_RAW_UPDATE_PATCHED:
        return True

    try:
        import logging

        import maxapi.dispatcher as maxapi_dispatcher
        from maxapi.methods.types import getted_updates
        from maxapi.types.updates import UNKNOWN_UPDATE_DISCLAIMER
    except Exception:  # noqa: BLE001
        return False

    current_processor = getattr(maxapi_dispatcher, "process_update_request", None)
    if getattr(current_processor, "_vtelemax_preserves_raw_update", False):
        _MAXAPI_RAW_UPDATE_PATCHED = True
        return True

    sdk_logger = logging.getLogger("maxapi.methods.types.getted_updates")

    async def _process_update_request_with_raw(
        events: dict[str, Any],
        bot: Any,
    ) -> list[Any]:
        """Повторяет SDK-парсинг polling updates и сохраняет raw event."""

        event_models: list[Any] = []
        for raw_event in events["updates"]:
            event_model = await getted_updates.get_update_model(raw_event, bot)
            if event_model is None:
                update_type = raw_event["update_type"]
                sdk_logger.warning(UNKNOWN_UPDATE_DISCLAIMER.format(update_type=update_type))
                continue
            _attach_raw_max_update(event_model, raw_event)
            event_models.append(event_model)
        return event_models

    async def _process_update_webhook_with_raw(event_json: dict[str, Any], bot: Any) -> Any | None:
        """Повторяет SDK-парсинг webhook update и сохраняет raw event."""

        event_model = await getted_updates.get_update_model(bot=bot, event=event_json)
        if event_model is not None:
            _attach_raw_max_update(event_model, event_json)
        return event_model

    setattr(_process_update_request_with_raw, "_vtelemax_preserves_raw_update", True)
    setattr(_process_update_webhook_with_raw, "_vtelemax_preserves_raw_update", True)
    maxapi_dispatcher.process_update_request = _process_update_request_with_raw
    maxapi_dispatcher.process_update_webhook = _process_update_webhook_with_raw
    getted_updates.process_update_request = _process_update_request_with_raw
    getted_updates.process_update_webhook = _process_update_webhook_with_raw
    _MAXAPI_RAW_UPDATE_PATCHED = True
    return True


def _is_message_not_modified_error(error: Exception) -> bool:
    """Проверяет, что ошибка редактирования вызвана отсутствием изменений."""

    text = str(error).lower()
    return "not modified" in text or "message is same" in text


def _resolve_max_upload_type_image() -> Any | None:
    """Возвращает enum `UploadType.IMAGE`, если maxapi доступен в текущем окружении."""

    try:
        from maxapi.enums.upload_type import UploadType
    except Exception:
        return None
    return UploadType.IMAGE


def _build_max_upload_attachment(*, token: str, upload_type: Any) -> Any | None:
    """Собирает attachment maxapi по токену загруженного изображения."""

    try:
        from maxapi.types.attachments.upload import AttachmentPayload, AttachmentUpload
    except Exception:
        return None
    return AttachmentUpload(type=upload_type, payload=AttachmentPayload(token=token))


def _extract_max_upload_token(upload_response: dict[str, Any]) -> str | None:
    """Извлекает токен изображения из ответа upload API MAX."""

    photos = upload_response.get("photos")
    if isinstance(photos, dict) and photos:
        first_key = next(iter(photos))
        first_item = photos.get(first_key)
        if isinstance(first_item, dict):
            token = first_item.get("token")
            if isinstance(token, str) and token:
                return token

    token = upload_response.get("token")
    if isinstance(token, str) and token:
        return token
    return None


def _build_max_moderation_notification_keyboard(ticket_id: str) -> object | None:
    """Возвращает inline-кнопку MAX для быстрого ответа модератора."""

    callback_payload = f"{MOD_REPLY_PREFIX}{ticket_id}_new_1"
    phone_callback_payload = f"{MOD_PHONE_SHOW_PREFIX}{ticket_id}_new_1"
    try:
        from maxapi.types import CallbackButton
        from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
    except Exception:
        return None

    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="✍️ Ответить", payload=callback_payload),
        CallbackButton(text="📞 Телефон гостя", payload=phone_callback_payload),
    )
    return builder.as_markup()


def _build_max_guest_message_close_keyboard() -> object | None:
    """Возвращает inline-кнопку MAX для закрытия входящего сообщения гостем."""

    try:
        from maxapi.types import CallbackButton
        from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
    except Exception:
        return None

    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="❌ Закрыть", payload=_GUEST_MESSAGE_CLOSE_PAYLOAD))
    return builder.as_markup()


def build_max_pending_delivery_sender(
    bot: Any,
) -> Callable[[PendingModeratorDelivery, str], Awaitable[None]]:
    """Строит sender-функцию для доставки pending-сообщений в MAX."""

    async def _send_message(delivery: PendingModeratorDelivery, text: str) -> None:
        kwargs: dict[str, Any] = {}
        if delivery.author == SupportMessageAuthor.SYSTEM:
            keyboard = _build_max_moderation_notification_keyboard(str(delivery.ticket_id))
            if keyboard is not None:
                kwargs["attachments"] = [keyboard]
        elif delivery.author == SupportMessageAuthor.MODERATOR:
            keyboard = _build_max_guest_message_close_keyboard()
            if keyboard is not None:
                kwargs["attachments"] = [keyboard]
        await bot.send_message(user_id=int(delivery.target_external_id), text=text, **kwargs)

    return _send_message


async def _send_virtual_card_qr_messages(*, bot: Any, chat_id: int, card_numbers: tuple[str, ...]) -> None:
    """Отправляет QR-коды карт в MAX перед итоговым текстовым ответом."""

    if not card_numbers:
        return

    qr_logger = logger.bind(platform="max", component="router", stage="virtual_card_qr", user_id=str(chat_id))
    upload_type = _resolve_max_upload_type_image()
    if upload_type is None:
        qr_logger.warning("MAX UploadType недоступен, отправка QR пропущена.")
        return

    for index, card_number in enumerate(card_numbers, start=1):
        try:
            qr_png = generate_qr_png_bytes(card_number)
        except (QrGenerationError, ValueError):
            qr_logger.warning("Не удалось сгенерировать QR для карты #{index}.", index=index)
            continue

        try:
            upload_data = await bot.get_upload_url(upload_type)
            upload_url = getattr(upload_data, "url", None)
            if not upload_url:
                qr_logger.warning("MAX не вернул upload_url для карты #{index}.", index=index)
                continue

            normalized_url = str(upload_url)
            if normalized_url.startswith("/"):
                normalized_url = f"https://botapi.max.ru{normalized_url}"

            form_data = aiohttp.FormData()
            form_data.add_field(
                "data",
                qr_png,
                filename=f"virtual_card_qr_{index}.png",
                content_type="image/png",
            )
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    normalized_url,
                    data=form_data,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    if response.status != 200:
                        qr_logger.warning(
                            "Ошибка upload QR в MAX: status={status}, карта #{index}.",
                            status=response.status,
                            index=index,
                        )
                        continue
                    upload_response = await response.json(content_type=None)

            token = _extract_max_upload_token(upload_response)
            if token is None:
                qr_logger.warning("MAX upload не вернул token для карты #{index}.", index=index)
                continue

            attachment = _build_max_upload_attachment(token=token, upload_type=upload_type)
            if attachment is None:
                qr_logger.warning("Не удалось собрать attachment MAX для карты #{index}.", index=index)
                return

            await bot.send_message(
                chat_id=chat_id,
                text=f"💳 Карта: {card_number}",
                attachments=[attachment],
            )
        except Exception:  # noqa: BLE001
            qr_logger.exception("Ошибка отправки QR в MAX для карты #{index}.", index=index)
            continue


async def _send_coupon_qr_message(*, bot: Any, chat_id: int, response: MaxAdapterResponse) -> None:
    """Отправляет QR купона в MAX отдельным сообщением перед текстовой карточкой."""

    coupon_payload = str(response.coupon_qr_payload or "").strip()
    if not coupon_payload:
        return

    qr_logger = logger.bind(platform="max", component="router", stage="coupon_qr", user_id=str(chat_id))
    upload_type = _resolve_max_upload_type_image()
    if upload_type is None:
        qr_logger.warning("MAX UploadType недоступен для купона / MAX UploadType is unavailable for coupon.")
        return

    try:
        qr_png = generate_qr_png_bytes(coupon_payload)
    except (QrGenerationError, ValueError):
        qr_logger.warning("Не удалось сгенерировать QR купона / Failed to generate coupon QR.")
        return

    try:
        upload_data = await bot.get_upload_url(upload_type)
        upload_url = getattr(upload_data, "url", None)
        if not upload_url:
            qr_logger.warning("MAX не вернул upload_url для купона / MAX did not return coupon upload_url.")
            return

        normalized_url = str(upload_url)
        if normalized_url.startswith("/"):
            normalized_url = f"https://botapi.max.ru{normalized_url}"

        form_data = aiohttp.FormData()
        form_data.add_field(
            "data",
            qr_png,
            filename="coupon_qr.png",
            content_type="image/png",
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(
                normalized_url,
                data=form_data,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as upload_response:
                if upload_response.status != 200:
                    qr_logger.warning(
                        "Ошибка upload QR купона в MAX / Coupon QR upload failed: status={status}.",
                        status=upload_response.status,
                    )
                    return
                upload_json = await upload_response.json(content_type=None)

        token = _extract_max_upload_token(upload_json)
        if token is None:
            qr_logger.warning("MAX upload не вернул token купона / MAX coupon upload did not return token.")
            return

        attachment = _build_max_upload_attachment(token=token, upload_type=upload_type)
        if attachment is None:
            qr_logger.warning("Не удалось собрать attachment купона / Failed to build coupon attachment.")
            return

        await bot.send_message(
            chat_id=chat_id,
            text=response.coupon_qr_caption or "🎟️ Купон",
            attachments=[attachment],
        )
    except Exception:  # noqa: BLE001
        qr_logger.exception("Ошибка отправки QR купона в MAX / Failed to send coupon QR in MAX.")


def register_max_guest_handlers(
    router: Any,
    adapter: MaxIdentityAdapter,
    delivery_processor: PendingModeratorDeliveryProcessor | None = None,
    delivery_lock: asyncio.Lock | None = None,
    delivery_batch_limit: int = 20,
    max_bot_token: str = "",
    max_contact_strict_hash_enabled: bool = False,
    max_contact_hash_shadow_mode_enabled: bool = True,
) -> None:
    """Регистрирует обработчики MAX-бота на переданном `router`."""

    router_logger = logger.bind(platform="max", component="router")
    raw_patch_enabled = _patch_maxapi_raw_update_preservation()
    router_logger.debug(
        "MAX raw update preservation patch status. enabled={enabled}.",
        enabled=raw_patch_enabled,
    )
    shared_delivery_lock = delivery_lock or asyncio.Lock()
    support_prompt_message_id_by_user_id: dict[int, str | int] = {}
    moderation_reply_prompt_message_id_by_user_id: dict[int, str | int] = {}
    contact_verification_counters: OrderedDict[str, int] = OrderedDict(
        (name, 0) for name in _MAX_CONTACT_HASH_COUNTER_NAMES
    )

    def _record_contact_verification_counters(
        *,
        contact_data: _MaxContactAttachmentData | None,
        hash_value_present: bool,
        hash_verified: bool | None,
        owner_match: bool | None,
    ) -> None:
        """Обновляет process-local счётчики проверки MAX-контактов."""

        if contact_data is None:
            return
        if hash_value_present:
            contact_verification_counters["hash_present_total"] += 1
        else:
            contact_verification_counters["hash_missing_total"] += 1
        if hash_verified is True:
            contact_verification_counters["hash_verified_true_total"] += 1
        elif hash_verified is False:
            contact_verification_counters["hash_verified_false_total"] += 1
        if owner_match is True:
            contact_verification_counters["owner_match_true_total"] += 1
        elif owner_match is False:
            contact_verification_counters["owner_match_false_total"] += 1

    def _remember_support_prompt(*, max_user_id: int, message_id: str | int | None) -> None:
        """Запоминает id технического экрана ввода вопроса."""

        if message_id is None:
            return
        support_prompt_message_id_by_user_id[max_user_id] = message_id

    def _remember_moderation_reply_prompt(*, max_user_id: int, message_id: str | int | None) -> None:
        """Запоминает id технического экрана ввода ответа модератора."""

        if message_id is None:
            return
        moderation_reply_prompt_message_id_by_user_id[max_user_id] = message_id

    async def _cleanup_support_prompt(*, bot: Any | None, max_user_id: int) -> None:
        """Удаляет технический экран «Введите ваш вопрос» после создания тикета."""

        message_id = support_prompt_message_id_by_user_id.pop(max_user_id, None)
        if bot is None or message_id is None:
            return
        try:
            await bot.delete_message(message_id=message_id)
        except Exception:  # noqa: BLE001
            router_logger.debug("Не удалось удалить технический экран ввода вопроса в MAX.")

    async def _cleanup_moderation_reply_prompt(
        *,
        bot: Any | None,
        max_user_id: int,
        keep_message_id: str | int | None = None,
    ) -> None:
        """Удаляет технический экран «Введите текст ответа модератора»."""

        message_id = moderation_reply_prompt_message_id_by_user_id.pop(max_user_id, None)
        if bot is None or message_id is None:
            return
        if keep_message_id is not None and str(message_id) == str(keep_message_id):
            return
        try:
            await bot.delete_message(message_id=message_id)
        except Exception:  # noqa: BLE001
            router_logger.debug("Не удалось удалить технический экран ввода ответа модератора в MAX.")

    async def _try_process_pending_deliveries(bot: Any | None) -> None:
        """Пытается доставить pending-сообщения модератора без влияния на UX пользователя."""

        delivery_logger = router_logger.bind(stage="pending_delivery")
        if delivery_processor is None or bot is None:
            return
        if shared_delivery_lock.locked():
            delivery_logger.debug("Пропуск доставки pending: предыдущий проход еще выполняется.")
            return

        async with shared_delivery_lock:
            try:
                sent_count, failed_count = await delivery_processor.process_once(
                    sender=build_max_pending_delivery_sender(bot),
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

    @router.message_created()
    async def message_handler(event: Any, context: Any = None) -> None:  # noqa: ARG001
        await _try_process_pending_deliveries(getattr(event, "bot", None))
        user_id = _extract_user_id(event)
        if user_id is None:
            return
        text = _extract_message_text(event)
        contact_data = _extract_contact_attachment_details(event)
        contact_phone = contact_data.phone_number if contact_data is not None else None
        lowered = text.strip().lower()
        event_logger = router_logger.bind(stage="message_created", user_id=str(user_id))
        contact_hash_present = bool(
            contact_data is not None and contact_data.contact_hash and contact_data.vcf_info
        )
        contact_vcf_present = bool(contact_data is not None and contact_data.vcf_info)
        contact_hash_value_present = bool(contact_data is not None and contact_data.contact_hash)
        contact_owner_id_present = bool(contact_data is not None and contact_data.max_user_id is not None)
        contact_hash_verified: bool | None = None
        contact_owner_matches_sender: bool | None = None
        strict_reject_reason: str | None = None
        if contact_data is not None:
            if contact_data.max_user_id is not None:
                contact_owner_matches_sender = contact_data.max_user_id == user_id
            if contact_hash_present:
                contact_hash_verified = _verify_max_contact_hash(
                    access_token=max_bot_token,
                    vcf_info=contact_data.vcf_info or "",
                    provided_hash=contact_data.contact_hash or "",
                )
            if max_contact_hash_shadow_mode_enabled:
                if contact_hash_present and contact_hash_verified is False:
                    event_logger.warning(
                        "MAX contact hash mismatch (shadow). phone={phone}, max_user_id={max_user_id}, sender_id={sender_id}.",
                        phone=contact_phone,
                        max_user_id=contact_data.max_user_id,
                        sender_id=user_id,
                    )
                if contact_owner_matches_sender is False:
                    event_logger.warning(
                        "MAX contact owner mismatch (shadow). phone={phone}, max_user_id={max_user_id}, sender_id={sender_id}.",
                        phone=contact_phone,
                        max_user_id=contact_data.max_user_id,
                        sender_id=user_id,
                    )
            if max_contact_strict_hash_enabled:
                if not contact_hash_present:
                    strict_reject_reason = "missing_hash"
                elif contact_hash_verified is not True:
                    strict_reject_reason = "hash_mismatch"
                elif contact_owner_matches_sender is False:
                    strict_reject_reason = "owner_mismatch"
                if strict_reject_reason is not None:
                    event_logger.warning(
                        "MAX strict contact verification rejected. reason={reason}, phone={phone}, max_user_id={max_user_id}, sender_id={sender_id}.",
                        reason=strict_reject_reason,
                        phone=contact_phone,
                        max_user_id=contact_data.max_user_id,
                        sender_id=user_id,
                    )
                    contact_phone = None
        _record_contact_verification_counters(
            contact_data=contact_data,
            hash_value_present=contact_hash_value_present,
            hash_verified=contact_hash_verified,
            owner_match=contact_owner_matches_sender,
        )
        if contact_data is not None:
            event_logger.info(
                "MAX contact verification counters / Метрики проверки MAX contact. "
                "hash_missing_total={hash_missing_total}, hash_present_total={hash_present_total}, "
                "hash_verified_true_total={hash_verified_true_total}, "
                "hash_verified_false_total={hash_verified_false_total}, "
                "owner_match_true_total={owner_match_true_total}, "
                "owner_match_false_total={owner_match_false_total}.",
                **contact_verification_counters,
            )
        event_logger.debug(
            "Получено сообщение от пользователя. text={text}, contact={contact}, hash_present={hash_present}, hash_verified={hash_verified}, owner_match={owner_match}, strict_reject_reason={strict_reject_reason}.",
            text=text,
            contact=contact_phone,
            hash_present=contact_hash_present,
            hash_verified=contact_hash_verified,
            owner_match=contact_owner_matches_sender,
            strict_reject_reason=strict_reject_reason,
        )
        event_logger.debug(
            "MAX contact payload debug. phone_source={phone_source}, vcf_present={vcf_present}, hash_value_present={hash_value_present}, hash_source={hash_source}, hash_paths={hash_paths}, owner_id_present={owner_id_present}, vcf_length={vcf_length}, hash_length={hash_length}.",
            phone_source=(contact_data.phone_source if contact_data is not None else None),
            vcf_present=contact_vcf_present,
            hash_value_present=contact_hash_value_present,
            hash_source=(
                contact_data.contact_hash_source if contact_data is not None else None
            ),
            hash_paths=(
                contact_data.contact_hash_present_paths if contact_data is not None else ()
            ),
            owner_id_present=contact_owner_id_present,
            vcf_length=(
                len(contact_data.vcf_info or "")
                if contact_data is not None and contact_data.vcf_info is not None
                else 0
            ),
            hash_length=(
                len(contact_data.contact_hash or "")
                if contact_data is not None and contact_data.contact_hash is not None
                else 0
            ),
        )
        event_logger.debug(
            "MAX contact payload structure debug / Структура contact payload. snapshot={snapshot}.",
            snapshot=_build_max_contact_payload_debug_snapshot(event, contact_data),
        )

        if lowered in _START_COMMANDS:
            support_prompt_message_id_by_user_id.pop(user_id, None)
            moderation_reply_prompt_message_id_by_user_id.pop(user_id, None)
            response = adapter.handle_start(max_user_id=user_id)
        else:
            if strict_reject_reason is not None:
                contact_screen = MaxGuestMenuAdapter().build_start_contact_screen()
                response = MaxAdapterResponse(
                    text=(
                        "🔒 Не удалось подтвердить контакт.\n\n"
                        "Отправьте номер только кнопкой «Поделиться контактом» и повторите шаг."
                    ),
                    screen=contact_screen,
                )
            else:
                response = adapter.handle_incoming(
                    max_user_id=user_id,
                    text=text,
                    payload=None,
                    contact_phone=contact_phone,
                )
            screen_id = response.screen.screen_id if response.screen is not None else None
            if screen_id == "support_question_confirmation":
                await _cleanup_support_prompt(bot=getattr(event, "bot", None), max_user_id=user_id)
            elif screen_id != "support_question":
                support_prompt_message_id_by_user_id.pop(user_id, None)
            if screen_id == "moderation_reply_cancel":
                pass
            elif screen_id is not None and screen_id.startswith("moderation_"):
                await _cleanup_moderation_reply_prompt(
                    bot=getattr(event, "bot", None),
                    max_user_id=user_id,
                )
            else:
                moderation_reply_prompt_message_id_by_user_id.pop(user_id, None)
        event_logger.info("Входящее сообщение обработано.")
        await _send_response(event, response)

    @router.bot_started()
    async def started_handler(event: Any, context: Any = None) -> None:  # noqa: ARG001
        await _try_process_pending_deliveries(getattr(event, "bot", None))
        user_id = _extract_user_id(event)
        if user_id is None:
            return
        support_prompt_message_id_by_user_id.pop(user_id, None)
        moderation_reply_prompt_message_id_by_user_id.pop(user_id, None)
        event_logger = router_logger.bind(stage="bot_started", user_id=str(user_id))
        event_logger.debug("Получено событие bot_started.")
        response = adapter.handle_start(max_user_id=user_id)
        event_logger.info("Событие bot_started обработано.")
        await _send_response(event, response)

    @router.message_callback()
    async def callback_handler(event: Any, context: Any = None) -> None:  # noqa: ARG001
        user_id = _extract_user_id(event)
        if user_id is None:
            return

        event_logger = router_logger.bind(stage="callback", user_id=str(user_id))
        callback_payload = _extract_callback_payload(event)
        event_logger.debug("Получен callback. payload={payload}.", payload=callback_payload)
        if (callback_payload or "").strip() == _GUEST_MESSAGE_CLOSE_PAYLOAD:
            if hasattr(event, "answer"):
                await event.answer("")
            callback_mid = _extract_callback_message_id(event)
            bot = getattr(event, "bot", None)
            if callback_mid is not None and bot is not None:
                try:
                    await bot.delete_message(message_id=callback_mid)
                except Exception:  # noqa: BLE001
                    event_logger.debug("Не удалось удалить сообщение гостя по кнопке закрытия в MAX.")
            return

        await _try_process_pending_deliveries(getattr(event, "bot", None))
        if hasattr(event, "answer"):
            await event.answer("")
        if callback_payload is not None and callback_payload.strip() == "noop":
            event_logger.debug("Получен noop callback пагинации, игнорируем без изменения экрана.")
            return

        normalized_payload = (callback_payload or "").strip()
        if normalized_payload in {
            GuestMenuAction.NOTIFY_YES.value,
            GuestMenuAction.NOTIFY_NO.value,
            GuestMenuAction.RETRY_IIKO_SYNC.value,
        }:
            pending_screen = build_iiko_sync_pending_screen()
            await _send_response(
                event,
                MaxAdapterResponse(text=pending_screen.text, screen=None),
            )

        response = adapter.handle_incoming(
            max_user_id=user_id,
            text="",
            payload=callback_payload,
        )
        screen_id = response.screen.screen_id if response.screen is not None else None
        callback_mid = _extract_callback_message_id(event)
        if screen_id == "support_question":
            _remember_support_prompt(max_user_id=user_id, message_id=callback_mid)
        elif normalized_payload not in {
            GuestMenuAction.SUPPORT_QUESTION.value,
            GuestMenuAction.SUPPORT_QUESTION_FROM_LIST.value,
        }:
            support_prompt_message_id_by_user_id.pop(user_id, None)
        if screen_id == "moderation_reply_cancel" and callback_mid is not None:
            _remember_moderation_reply_prompt(max_user_id=user_id, message_id=callback_mid)
        elif screen_id is not None and screen_id.startswith("moderation_"):
            await _cleanup_moderation_reply_prompt(
                bot=getattr(event, "bot", None),
                max_user_id=user_id,
                keep_message_id=callback_mid,
            )
        else:
            moderation_reply_prompt_message_id_by_user_id.pop(user_id, None)
        event_logger.info("Callback обработан.")
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

    parse_mode_key = response.parse_mode
    if parse_mode_key is None and response.screen is not None:
        parse_mode_key = response.screen.parse_mode
    if parse_mode_key == "markdown":
        markdown_parse_mode = _resolve_markdown_parse_mode()
        if markdown_parse_mode is not None:
            kwargs["parse_mode"] = markdown_parse_mode
    if parse_mode_key == "html":
        html_parse_mode = _resolve_html_parse_mode()
        if html_parse_mode is not None:
            kwargs["parse_mode"] = html_parse_mode

    callback_mid = _extract_callback_message_id(event)
    if response.virtual_card_numbers:
        if callback_mid is not None:
            try:
                await bot.delete_message(message_id=callback_mid)
            except Exception:  # noqa: BLE001
                # Не блокируем сценарий, если исходное callback-сообщение удалить не удалось.
                pass
        await _send_virtual_card_qr_messages(
            bot=bot,
            chat_id=chat_id,
            card_numbers=response.virtual_card_numbers,
        )
        await bot.send_message(chat_id=chat_id, text=response.text, **kwargs)
        return

    if response.coupon_qr_payload:
        if callback_mid is not None:
            try:
                await bot.delete_message(message_id=callback_mid)
            except Exception:  # noqa: BLE001
                # Не блокируем сценарий, если исходное callback-сообщение удалить не удалось.
                pass
        await _send_coupon_qr_message(bot=bot, chat_id=chat_id, response=response)
        await bot.send_message(chat_id=chat_id, text=response.text, **kwargs)
        return

    if callback_mid is not None:
        try:
            await bot.edit_message(message_id=callback_mid, text=response.text, **kwargs)
            return
        except Exception as error:  # noqa: BLE001
            if _is_message_not_modified_error(error):
                # Сообщение уже содержит актуальный контент.
                return
            # На некоторых типах сообщений редактирование недоступно, fallback на send_message.
            pass

    await bot.send_message(chat_id=chat_id, text=response.text, **kwargs)


def _resolve_markdown_parse_mode() -> Any | None:
    """Возвращает `ParseMode.MARKDOWN`, если maxapi доступен."""

    try:
        from maxapi.enums.parse_mode import ParseMode
    except Exception:
        return None
    return ParseMode.MARKDOWN


def _resolve_html_parse_mode() -> Any | None:
    """Возвращает `ParseMode.HTML`, если maxapi доступен."""

    try:
        from maxapi.enums.parse_mode import ParseMode
    except Exception:
        return None
    return getattr(ParseMode, "HTML", None)


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


def _extract_contact_attachment(event: Any) -> str | None:
    """Извлекает телефон из contact-вложения MAX.

    Поддерживает два формата:
    1) `event.message.body.contact.phone_number`;
    2) `event.message.body.attachments[]` с `type="contact"` и `payload.vcf_info`.
    """

    if (
        hasattr(event, "message")
        and hasattr(event.message, "body")
        and hasattr(event.message.body, "contact")
        and event.message.body.contact is not None
    ):
        contact = event.message.body.contact
        if hasattr(contact, "phone_number"):
            phone = contact.phone_number
            if phone is not None:
                return str(phone)

    if (
        hasattr(event, "message")
        and hasattr(event.message, "body")
        and hasattr(event.message.body, "attachments")
        and event.message.body.attachments is not None
    ):
        for attachment in event.message.body.attachments:
            if getattr(attachment, "type", None) != "contact":
                continue
            payload = getattr(attachment, "payload", None)
            if payload is None:
                continue

            payload_phone = getattr(payload, "phone_number", None)
            if payload_phone is not None:
                return str(payload_phone)

            vcf_info = getattr(payload, "vcf_info", None)
            if vcf_info is None:
                continue

            parsed_phone = _extract_phone_from_vcf(str(vcf_info))
            if parsed_phone is not None:
                return parsed_phone

    return None


def _read_object_field(obj: Any, field_name: str) -> Any:
    """Читает поле из dict-подобного или объектного payload."""

    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(field_name)
    value = getattr(obj, field_name, None)
    if value is not None:
        return value
    model_extra = getattr(obj, "model_extra", None)
    if isinstance(model_extra, dict):
        return model_extra.get(field_name)
    return None


def _get_raw_max_update(event: Any) -> dict[str, Any] | None:
    """Возвращает сырой MAX update, если он был сохранён до SDK-нормализации."""

    raw_update = getattr(event, _MAX_CONTACT_RAW_UPDATE_ATTR, None)
    return raw_update if isinstance(raw_update, dict) else None


def _extract_raw_contact_payloads(event: Any) -> tuple[Any, ...]:
    """Извлекает raw `attachments[].payload` для contact-вложений из исходного JSON."""

    raw_update = _get_raw_max_update(event)
    if raw_update is None:
        return ()
    raw_message = _read_object_field(raw_update, "message")
    raw_body = _read_object_field(raw_message, "body")
    raw_attachments = _read_object_field(raw_body, "attachments")
    if not isinstance(raw_attachments, list):
        return ()

    payloads: list[Any] = []
    for raw_attachment in raw_attachments:
        if _read_object_field(raw_attachment, "type") != "contact":
            continue
        payload = _read_object_field(raw_attachment, "payload")
        if payload is not None:
            payloads.append(payload)
    return tuple(payloads)


def _lookup_max_contact_hash(payload: Any, *, base_path: str) -> _MaxContactHashLookup:
    """Ищет hash контакта по официальному и legacy-набору имён полей."""

    present_paths: list[str] = []
    selected_value: str | None = None
    selected_source: str | None = None
    for field_name in _MAX_CONTACT_HASH_FIELD_NAMES:
        value = _read_object_field(payload, field_name)
        path = f"{base_path}.{field_name}"
        if value is None or not str(value).strip():
            continue
        present_paths.append(path)
        if selected_value is None:
            selected_value = str(value)
            selected_source = path
    return _MaxContactHashLookup(
        value=selected_value,
        source=selected_source,
        present_paths=tuple(present_paths),
    )


def _build_max_contact_hash_field_presence(payload: Any, *, base_path: str) -> dict[str, bool]:
    """Строит DEBUG-карту наличия каждого ожидаемого hash-поля."""

    return {
        f"{base_path}.{field_name}": bool(_read_object_field(payload, field_name))
        for field_name in _MAX_CONTACT_HASH_FIELD_NAMES
    }


def _debug_object_field_names(obj: Any) -> tuple[str, ...]:
    """Возвращает имена полей объекта без значений, чтобы безопасно видеть структуру."""

    if obj is None:
        return ()
    if isinstance(obj, dict):
        return tuple(sorted(str(key) for key in obj.keys()))

    names: set[str] = set()
    model_fields = getattr(obj, "model_fields", None)
    if isinstance(model_fields, dict):
        names.update(str(key) for key in model_fields.keys())
    model_extra = getattr(obj, "model_extra", None)
    if isinstance(model_extra, dict):
        names.update(str(key) for key in model_extra.keys())
    object_dict = getattr(obj, "__dict__", None)
    if isinstance(object_dict, dict):
        names.update(str(key) for key in object_dict.keys() if not str(key).startswith("_"))
    return tuple(sorted(names))


def _mask_phone_for_log(value: Any) -> str | None:
    """Маскирует телефон для логов, оставляя только последние четыре цифры."""

    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    if len(digits) <= 4:
        return "***"
    return f"***{digits[-4:]}"


def _build_vcf_debug_summary(vcf_info: Any) -> dict[str, object]:
    """Возвращает безопасную сводку по VCF без вывода полной визитки."""

    if vcf_info is None:
        return {"present": False, "length": 0, "tel_masked": None}
    vcf_text = str(vcf_info)
    return {
        "present": True,
        "length": len(vcf_text),
        "tel_masked": _mask_phone_for_log(_extract_phone_from_vcf(vcf_text)),
    }


def _build_max_contact_payload_debug_snapshot(
    event: Any,
    contact_data: _MaxContactAttachmentData | None,
) -> dict[str, object]:
    """Формирует безопасный DEBUG-снимок структуры contact payload.

    Снимок нужен для прод-аудита: он показывает, какие поля дошли после SDK,
    какие были в raw update, и где именно найден hash. PII не логируется:
    телефоны маскируются, `vcf_info` сворачивается до длины и TEL-маски.
    """

    body = _read_object_field(_read_object_field(event, "message"), "body")
    body_contact = _read_object_field(body, "contact")
    body_attachments = _read_object_field(body, "attachments")
    raw_payloads = _extract_raw_contact_payloads(event)

    attachments_summary: list[dict[str, object]] = []
    contact_index = 0
    if isinstance(body_attachments, list):
        for attachment in body_attachments:
            attachment_type = _read_object_field(attachment, "type")
            if attachment_type != "contact":
                continue
            payload = _read_object_field(attachment, "payload")
            raw_payload = raw_payloads[contact_index] if contact_index < len(raw_payloads) else None
            contact_index += 1
            max_info = _read_object_field(payload, "max_info")
            raw_max_info = _read_object_field(raw_payload, "max_info")
            attachments_summary.append(
                {
                    "type": attachment_type,
                    "payload_fields": _debug_object_field_names(payload),
                    "raw_payload_fields": _debug_object_field_names(raw_payload),
                    "phone_number_masked": _mask_phone_for_log(
                        _read_object_field(payload, "phone_number")
                    ),
                    "vcf_info": _build_vcf_debug_summary(
                        _read_object_field(payload, "vcf_info")
                    ),
                    "hash_field_presence": _build_max_contact_hash_field_presence(
                        payload,
                        base_path="payload",
                    ),
                    "raw_hash_field_presence": _build_max_contact_hash_field_presence(
                        raw_payload,
                        base_path="raw.payload",
                    ),
                    "max_info_user_id_present": _read_object_field(max_info, "user_id")
                    is not None,
                    "raw_max_info_user_id_present": _read_object_field(raw_max_info, "user_id")
                    is not None,
                }
            )

    return {
        "body_contact": {
            "present": body_contact is not None,
            "fields": _debug_object_field_names(body_contact),
            "phone_number_masked": _mask_phone_for_log(
                _read_object_field(body_contact, "phone_number")
            ),
        },
        "contact_attachments": attachments_summary,
        "extracted": {
            "phone_source": contact_data.phone_source if contact_data is not None else None,
            "phone_number_masked": _mask_phone_for_log(
                contact_data.phone_number if contact_data is not None else None
            ),
            "hash_source": contact_data.contact_hash_source if contact_data is not None else None,
            "hash_present_paths": (
                contact_data.contact_hash_present_paths if contact_data is not None else ()
            ),
            "owner_id_present": (
                contact_data.max_user_id is not None if contact_data is not None else False
            ),
        },
        "raw_update_attached": _get_raw_max_update(event) is not None,
    }


def _extract_max_info_user_id(max_info: Any) -> int | None:
    """Извлекает user_id из payload.max_info."""

    value = _read_object_field(max_info, "user_id")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_contact_attachment_details(event: Any) -> _MaxContactAttachmentData | None:
    """Извлекает расширенные поля contact-вложения MAX (телефон/hash/max_info.user_id)."""

    body_phone: str | None = None
    if (
        hasattr(event, "message")
        and hasattr(event.message, "body")
        and hasattr(event.message.body, "contact")
        and event.message.body.contact is not None
    ):
        contact = event.message.body.contact
        phone = _read_object_field(contact, "phone_number")
        if phone is not None:
            body_phone = str(phone)

    raw_contact_payloads = _extract_raw_contact_payloads(event)
    if (
        hasattr(event, "message")
        and hasattr(event.message, "body")
        and hasattr(event.message.body, "attachments")
        and event.message.body.attachments is not None
    ):
        contact_index = 0
        for attachment in event.message.body.attachments:
            if _read_object_field(attachment, "type") != "contact":
                continue
            payload = _read_object_field(attachment, "payload")
            if payload is None:
                continue
            raw_payload = (
                raw_contact_payloads[contact_index]
                if contact_index < len(raw_contact_payloads)
                else None
            )
            contact_index += 1

            payload_phone = _read_object_field(payload, "phone_number")
            payload_vcf_info = _read_object_field(payload, "vcf_info")
            payload_max_info = _read_object_field(payload, "max_info")
            raw_max_info = _read_object_field(raw_payload, "max_info")
            payload_max_user_id = _extract_max_info_user_id(payload_max_info)
            if payload_max_user_id is None:
                payload_max_user_id = _extract_max_info_user_id(raw_max_info)
            parsed_hash_lookup = _lookup_max_contact_hash(payload, base_path="payload")
            raw_hash_lookup = _lookup_max_contact_hash(raw_payload, base_path="raw.payload")
            payload_hash = parsed_hash_lookup.value or raw_hash_lookup.value
            payload_hash_source = parsed_hash_lookup.source or raw_hash_lookup.source
            payload_hash_present_paths = (
                parsed_hash_lookup.present_paths + raw_hash_lookup.present_paths
            )

            phone: str | None = None
            if payload_phone is not None:
                phone = str(payload_phone)
            elif payload_vcf_info is not None:
                phone = _extract_phone_from_vcf(str(payload_vcf_info))
            elif body_phone is not None:
                # В части событий MAX телефон доступен только в body.contact,
                # а hash/max_info приходят в attachments.payload.
                phone = body_phone

            if phone is None:
                continue

            return _MaxContactAttachmentData(
                phone_number=phone,
                vcf_info=str(payload_vcf_info) if payload_vcf_info is not None else None,
                contact_hash=str(payload_hash) if payload_hash is not None else None,
                max_user_id=payload_max_user_id,
                phone_source=(
                    "payload.phone_number"
                    if payload_phone is not None
                    else "payload.vcf_info"
                    if payload_vcf_info is not None
                    else "body.contact+payload.meta"
                ),
                contact_hash_source=payload_hash_source,
                contact_hash_present_paths=payload_hash_present_paths,
            )

    if body_phone is not None:
        return _MaxContactAttachmentData(
            phone_number=body_phone,
            vcf_info=None,
            contact_hash=None,
            max_user_id=None,
            phone_source="body.contact",
        )

    return None


def _verify_max_contact_hash(*, access_token: str, vcf_info: str, provided_hash: str) -> bool:
    """Проверяет hash для contact-вложения MAX через HMAC-SHA256."""

    token = access_token.strip()
    actual_hash = provided_hash.strip().lower()
    if not token or not vcf_info or not actual_hash:
        return False

    for candidate in _build_vcf_hash_candidates(vcf_info):
        expected_hash = hmac.new(
            token.encode("utf-8"),
            candidate.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().lower()
        if hmac.compare_digest(expected_hash, actual_hash):
            return True
    return False


def _build_vcf_hash_candidates(vcf_info: str) -> tuple[str, ...]:
    """Готовит варианты vcf_info для устойчивой проверки hash при разных переносах."""

    candidates: list[str] = []

    def _add(value: str) -> None:
        if value and value not in candidates:
            candidates.append(value)

    raw = vcf_info
    _add(raw)

    escaped_to_lf = raw.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    normalized_lf = escaped_to_lf.replace("\r\n", "\n").replace("\r", "\n")
    _add(normalized_lf)

    normalized_crlf = normalized_lf.replace("\n", "\r\n")
    _add(normalized_crlf)
    if not normalized_crlf.endswith("\r\n"):
        _add(normalized_crlf + "\r\n")

    return tuple(candidates)


def _extract_callback_message_id(event: Any) -> str | int | None:
    """Извлекает ID сообщения, которое можно редактировать в callback-сценарии."""

    if hasattr(event, "callback") and hasattr(event, "message"):
        message = getattr(event, "message", None)
        if message is not None and hasattr(message, "body") and hasattr(message.body, "mid"):
            mid = message.body.mid
            if mid is None:
                return None
            # В MAX встречаются строковые идентификаторы вида `mid.<hex>`, поэтому
            # сохраняем исходный тип без принудительного приведения к int.
            return mid
    return None


def _extract_phone_from_vcf(vcf_info: str) -> str | None:
    """Извлекает номер телефона из строки VCF (поле `TEL...:`)."""

    if not vcf_info:
        return None
    match = _VCF_PHONE_PATTERN.search(vcf_info)
    if match is None:
        return None
    raw_phone = match.group(1).strip()
    if not raw_phone:
        return None
    normalized_phone = _PHONE_SANITIZE_PATTERN.sub("", raw_phone)
    return normalized_phone or None
