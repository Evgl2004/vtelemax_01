"""Aiogram-router для сценария строгой идентификации в Telegram."""

from __future__ import annotations

import asyncio
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from loguru import logger

from vtelemax.core import (
    BUTTON_ACCEPT_RULES,
    GuestMenuAction,
    PendingModeratorDelivery,
    SupportMessageAuthor,
    build_iiko_sync_pending_screen,
)
from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor
from vtelemax.infrastructure import QrGenerationError, generate_qr_png_bytes

from .identity_adapter import TelegramIdentityAdapter, TelegramMenuActionResult
from .menu import (
    MOD_CLOSE_PREFIX,
    MOD_LIST_PREFIX,
    MOD_MAIN_CALLBACK,
    MOD_PAGE_PREFIX,
    MOD_REPLY_PREFIX,
    MOD_TAKE_PREFIX,
    MOD_TICKET_PREFIX,
    NOTIFY_NO_CALLBACK,
    NOTIFY_YES_CALLBACK,
    RULES_ACCEPT_CALLBACK,
    USER_TICKETS_PAGE_PREFIX,
    USER_TICKETS_PREV_PAGE_PREFIX,
    USER_TICKETS_NEXT_PAGE_PREFIX,
    USER_TICKET_DETAILS_PREFIX,
    USER_TICKET_REPLY_PREFIX,
    BUTTON_BACK_TO_MAIN,
    BUTTON_BACK_TO_SUPPORT,
    BUTTON_BALANCE,
    BUTTON_BUSINESS_LUNCH,
    BUTTON_DELIVERY,
    BUTTON_PROFILE,
    BUTTON_PROFILE_EDIT,
    BUTTON_PROFILE_EDIT_BIRTH_DATE,
    BUTTON_PROFILE_EDIT_CANCEL,
    BUTTON_PROFILE_EDIT_EMAIL,
    BUTTON_PROFILE_EDIT_FIRST_NAME,
    BUTTON_PROFILE_EDIT_GENDER,
    BUTTON_PROFILE_EDIT_GENDER_FEMALE,
    BUTTON_PROFILE_EDIT_GENDER_MALE,
    BUTTON_PROFILE_EDIT_LAST_NAME,
    BUTTON_RETRY_IIKO_SYNC,
    BUTTON_SUPPORT,
    BUTTON_SUPPORT_CONTACTS,
    BUTTON_SUPPORT_FEEDBACK,
    BUTTON_SUPPORT_QUESTION,
    BUTTON_TABLE_BOOKING,
    BUTTON_MY_TICKETS,
    BUTTON_VACANCIES,
    BUTTON_VIRTUAL_CARD,
    build_back_to_main_inline_keyboard,
    build_back_to_tickets_list_inline_keyboard,
    build_contact_request_keyboard,
    build_delivery_inline_keyboard,
    build_business_lunch_inline_keyboard,
    build_table_booking_inline_keyboard,
    build_iiko_sync_retry_inline_keyboard,
    build_main_menu_inline_keyboard,
    build_moderation_main_inline_keyboard,
    build_moderation_notification_inline_keyboard,
    build_moderation_reply_cancel_inline_keyboard,
    build_moderation_ticket_details_inline_keyboard,
    build_moderation_tickets_inline_keyboard,
    build_notifications_consent_inline_keyboard,
    build_profile_edit_inline_keyboard,
    build_profile_gender_inline_keyboard,
    build_profile_inline_keyboard,
    build_rules_consent_inline_keyboard,
    build_support_feedback_inline_keyboard,
    build_support_menu_inline_keyboard,
    build_ticket_details_inline_keyboard,
    build_user_tickets_pagination_keyboard,
)


def _is_message_not_modified_error(error: Exception) -> bool:
    """Проверяет, что ошибка редактирования связана только с отсутствием изменений."""

    if isinstance(error, TelegramBadRequest):
        text = str(error).lower()
        return "message is not modified" in text or "message_not_modified" in text
    text = str(error).lower()
    return "message is not modified" in text or "message_not_modified" in text


def _is_button_data_invalid_error(error: Exception) -> bool:
    """Проверяет, что ошибка связана с невалидным callback_data в inline-кнопке."""

    if isinstance(error, TelegramBadRequest):
        text = str(error).lower()
        return "button_data_invalid" in text
    return "button_data_invalid" in str(error).lower()


def _is_message_cant_be_edited_error(error: Exception) -> bool:
    """Проверяет, что Telegram запретил редактирование сообщения."""

    if isinstance(error, TelegramBadRequest):
        text = str(error).lower()
        return "message can't be edited" in text or "message cant be edited" in text
    text = str(error).lower()
    return "message can't be edited" in text or "message cant be edited" in text


def build_telegram_identity_router(
    identity_adapter: TelegramIdentityAdapter,
    delivery_processor: PendingModeratorDeliveryProcessor | None = None,
) -> Router:
    """Создает router Telegram с обработчиками регистрации по телефону."""

    router = Router(name="telegram_identity")
    router_logger = logger.bind(platform="telegram", component="router")
    main_menu_inline_keyboard = build_main_menu_inline_keyboard()
    back_to_main_keyboard = build_back_to_main_inline_keyboard()
    profile_keyboard = build_profile_inline_keyboard()
    delivery_lock = asyncio.Lock()
    support_prompt_message_id_by_user_id: dict[int, int] = {}

    def _with_reply_keyboard_cleanup(
        reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None,
    ) -> InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove:
        """Гарантированно убирает legacy reply-клавиатуру, когда новая клавиатура не передана."""

        if reply_markup is None:
            return ReplyKeyboardRemove()
        return reply_markup

    async def _send_virtual_card_qr(
        *,
        bot: Bot,
        chat_id: int,
        result: Any,
    ) -> None:
        """Отправляет QR-коды виртуальных карт отдельными сообщениями перед итоговым текстом."""

        card_numbers = getattr(result, "virtual_card_numbers", ())
        if not card_numbers:
            return

        qr_logger = router_logger.bind(stage="virtual_card_qr", user_id=str(chat_id))
        for index, card_number in enumerate(card_numbers, start=1):
            try:
                qr_png = generate_qr_png_bytes(card_number)
            except (ValueError, QrGenerationError) as error:
                qr_logger.warning(
                    "Не удалось сгенерировать QR-код для карты #{index}. Причина: {error}.",
                    index=index,
                    error=error,
                )
                return

            await bot.send_photo(
                chat_id=chat_id,
                photo=BufferedInputFile(qr_png, filename=f"virtual_card_qr_{index}.png"),
                caption=f"💳 Карта: {card_number}",
            )

    def _remember_support_prompt_message(*, user_id: int | None, message_id: int | None) -> None:
        """Запоминает id последнего технического экрана ввода вопроса в Telegram."""

        if user_id is None or message_id is None:
            return
        support_prompt_message_id_by_user_id[user_id] = message_id

    async def _cleanup_support_prompt_message(
        *,
        bot: Bot,
        chat_id: int,
        user_id: int | None,
    ) -> None:
        """Удаляет ранее показанный экран «Введите ваш вопрос», чтобы не дублировать меню."""

        if user_id is None:
            return
        message_id = support_prompt_message_id_by_user_id.pop(user_id, None)
        if message_id is None:
            return
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:  # noqa: BLE001
            router_logger.debug("Не удалось удалить техническое сообщение ввода вопроса.")

    async def _answer_with_result(
        *,
        message: Message,
        result: Any,
        reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None,
    ) -> None:
        """Отправляет результат адаптера для message-handler, включая QR при необходимости."""

        await _send_virtual_card_qr(bot=message.bot, chat_id=message.chat.id, result=result)
        if isinstance(reply_markup, InlineKeyboardMarkup):
            # Telegram не умеет одновременно поставить inline-клавиатуру и снять reply-клавиатуру.
            # Поэтому сначала принудительно убираем reply-кнопки, затем добавляем inline на то же сообщение.
            sent_message = await message.answer(
                result.message,
                parse_mode=getattr(result, "parse_mode", None),
                reply_markup=ReplyKeyboardRemove(),
            )
            try:
                await sent_message.edit_reply_markup(reply_markup=reply_markup)
            except TelegramBadRequest as error:
                if _is_button_data_invalid_error(error):
                    router_logger.warning(
                        "Невалидная callback-кнопка в reply_markup. Оставляем сообщение без inline-клавиатуры."
                    )
                    return
                if _is_message_cant_be_edited_error(error):
                    router_logger.info(
                        "Telegram не дал отредактировать сообщение для inline-клавиатуры. Применяем fallback отправкой нового сообщения."
                    )
                    try:
                        await sent_message.delete()
                    except Exception:  # noqa: BLE001
                        router_logger.debug("Не удалось удалить промежуточное сообщение fallback.")
                    try:
                        await message.answer(
                            result.message,
                            parse_mode=getattr(result, "parse_mode", None),
                            reply_markup=reply_markup,
                        )
                    except TelegramBadRequest as fallback_error:
                        if not _is_button_data_invalid_error(fallback_error):
                            raise
                        router_logger.warning(
                            "Невалидная callback-кнопка в fallback reply_markup. Отправляем сообщение без inline-клавиатуры."
                        )
                        await message.answer(
                            result.message,
                            parse_mode=getattr(result, "parse_mode", None),
                            reply_markup=ReplyKeyboardRemove(),
                        )
                    return
                raise
            return
        try:
            await message.answer(
                result.message,
                parse_mode=getattr(result, "parse_mode", None),
                reply_markup=_with_reply_keyboard_cleanup(reply_markup),
            )
        except TelegramBadRequest as error:
            if not _is_button_data_invalid_error(error):
                raise
            router_logger.warning(
                "Невалидная callback-кнопка в reply_markup. Повторяем отправку без клавиатуры."
            )
            await message.answer(
                result.message,
                parse_mode=getattr(result, "parse_mode", None),
                reply_markup=ReplyKeyboardRemove(),
            )

    async def _send_to_chat_with_result(
        *,
        bot: Bot,
        chat_id: int,
        result: Any,
        reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None,
    ) -> None:
        """Отправляет результат адаптера напрямую в чат, включая QR при необходимости."""

        await _send_virtual_card_qr(bot=bot, chat_id=chat_id, result=result)
        if isinstance(reply_markup, InlineKeyboardMarkup):
            # Аналогично _answer_with_result: снимаем reply-клавиатуру отдельным сообщением,
            # после чего добавляем inline-кнопки на отправленный текст.
            sent_message = await bot.send_message(
                chat_id=chat_id,
                text=result.message,
                parse_mode=getattr(result, "parse_mode", None),
                reply_markup=ReplyKeyboardRemove(),
            )
            try:
                await bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=sent_message.message_id,
                    reply_markup=reply_markup,
                )
            except TelegramBadRequest as error:
                if _is_button_data_invalid_error(error):
                    router_logger.warning(
                        "Невалидная callback-кнопка в reply_markup. Оставляем сообщение без inline-клавиатуры."
                    )
                    return
                if _is_message_cant_be_edited_error(error):
                    router_logger.info(
                        "Telegram не дал отредактировать сообщение для inline-клавиатуры (send_to_chat). Применяем fallback отправкой нового сообщения."
                    )
                    try:
                        await bot.delete_message(chat_id=chat_id, message_id=sent_message.message_id)
                    except Exception:  # noqa: BLE001
                        router_logger.debug("Не удалось удалить промежуточное сообщение fallback (send_to_chat).")
                    try:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=result.message,
                            parse_mode=getattr(result, "parse_mode", None),
                            reply_markup=reply_markup,
                        )
                    except TelegramBadRequest as fallback_error:
                        if not _is_button_data_invalid_error(fallback_error):
                            raise
                        router_logger.warning(
                            "Невалидная callback-кнопка в fallback reply_markup (send_to_chat). Отправляем сообщение без inline-клавиатуры."
                        )
                        await bot.send_message(
                            chat_id=chat_id,
                            text=result.message,
                            parse_mode=getattr(result, "parse_mode", None),
                            reply_markup=ReplyKeyboardRemove(),
                        )
                    return
                raise
            return
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=result.message,
                parse_mode=getattr(result, "parse_mode", None),
                reply_markup=_with_reply_keyboard_cleanup(reply_markup),
            )
        except TelegramBadRequest as error:
            if not _is_button_data_invalid_error(error):
                raise
            router_logger.warning(
                "Невалидная callback-кнопка в reply_markup. Повторяем отправку без клавиатуры."
            )
            await bot.send_message(
                chat_id=chat_id,
                text=result.message,
                parse_mode=getattr(result, "parse_mode", None),
                reply_markup=ReplyKeyboardRemove(),
            )

    def _choose_reply_markup(result: TelegramMenuActionResult) -> InlineKeyboardMarkup | ReplyKeyboardMarkup | None:
        """Выбирает клавиатуру для ответа на основе результата адаптера."""
        if result.status in {"rules_consent_required", "rules_consent_pending"}:
            return build_rules_consent_inline_keyboard()
        if result.requires_contact_keyboard:
            return build_contact_request_keyboard()
        if result.status in {"phone_required", "phone_validation_error"}:
            return None
        if result.status in {"notifications_consent_required", "notifications_consent_pending"}:
            return build_notifications_consent_inline_keyboard()
        if result.status in {"iiko_sync_retry", "iiko_sync_retry_pending"}:
            return build_iiko_sync_retry_inline_keyboard()
        if result.status in {"moderation_menu", "moderation_menu_unknown"}:
            return build_moderation_main_inline_keyboard()
        if (
            result.status == "moderation_tickets_page"
            and result.moderation_filter is not None
            and result.moderation_page is not None
            and result.moderation_total_pages is not None
        ):
            return build_moderation_tickets_inline_keyboard(
                filter_key=result.moderation_filter,
                current_page=result.moderation_page,
                total_pages=result.moderation_total_pages,
                tickets=result.moderation_tickets,
            )
        if (
            result.status in {"moderation_ticket_details", "moderation_details_error"}
            and result.moderation_ticket_id is not None
            and result.moderation_filter is not None
            and result.moderation_page is not None
        ):
            return build_moderation_ticket_details_inline_keyboard(
                ticket_id=str(result.moderation_ticket_id),
                filter_key=result.moderation_filter,
                page=result.moderation_page,
                status_value=result.moderation_ticket_status or "",
            )
        if result.status in {
            "moderation_tickets",
            "moderation_tickets_in_progress",
            "moderation_tickets_closed",
            "moderation_details",
            "moderation_routed",
            "moderation_status_updated",
            "moderation_wait_ticket_for_reply",
            "moderation_wait_ticket_for_details",
            "moderation_wait_ticket_for_close",
            "moderation_wait_ticket_for_in_progress",
        }:
            return build_moderation_main_inline_keyboard()
        if result.status in {"moderation_wait_reply_text", "moderation_empty_reply", "moderation_bad_platform"}:
            return build_moderation_reply_cancel_inline_keyboard()
        if result.status == "tickets_list" and result.current_page is not None and result.total_pages is not None:
            # Показываем пагинацию для списка тикетов
            return build_user_tickets_pagination_keyboard(
                current_page=result.current_page,
                total_pages=result.total_pages,
                tickets=result.tickets,
                has_tickets=result.has_support_tickets,
            )
        if result.status in {"support", "tickets_empty"}:
            return build_support_menu_inline_keyboard(has_tickets=result.has_support_tickets)
        if result.status == "support_feedback":
            return build_support_feedback_inline_keyboard()
        if result.status in {"support_question", "support_question_empty", "support_question_unavailable", "support_question_input"}:
            if result.has_support_tickets:
                return build_back_to_tickets_list_inline_keyboard()
            return back_to_main_keyboard
        if result.status in {"support_reply_input", "support_reply_empty", "support_reply_error"}:
            return build_back_to_tickets_list_inline_keyboard()
        if result.status == "support_contacts":
            return back_to_main_keyboard
        if result.status == "ticket_details" and result.ticket_id is not None:
            return build_ticket_details_inline_keyboard(
                ticket_id=str(result.ticket_id),
                can_reply=(result.ticket_status or "") != "closed",
            )
        if result.status == "ticket_details_error":
            return build_back_to_tickets_list_inline_keyboard()
        if result.status == "delivery":
            return build_delivery_inline_keyboard()
        if result.status == "business_lunch":
            return build_business_lunch_inline_keyboard()
        if result.status == "table_booking":
            return build_table_booking_inline_keyboard()
        if result.status in {
            "balance",
            "balance_unavailable",
            "virtual_card",
            "virtual_card_error",
            "virtual_card_unavailable",
            "vacancies",
            "about",
            "support_question_submitted",
            "support_question_error",
            "support_reply_submitted",
            "support_reply_closed",
        }:
            return back_to_main_keyboard
        if result.status in {"profile", "profile_edit_first_name_saved", "profile_edit_last_name_saved", "profile_edit_gender_saved", "profile_edit_birth_date_saved", "profile_edit_email_saved"}:
            return profile_keyboard
        if result.status in {"profile_edit", "profile_edit_invalid_choice"}:
            return build_profile_edit_inline_keyboard(
                can_edit_birth_date=True if result.can_edit_birth_date is None else result.can_edit_birth_date
            )
        if result.status == "profile_edit_gender":
            return build_profile_gender_inline_keyboard()
        if result.status == "menu":
            return main_menu_inline_keyboard
        return None

    async def _try_process_pending_deliveries(bot: Bot) -> None:
        """Пытается доставить pending-сообщения модератора без влияния на UX пользователя."""

        delivery_logger = router_logger.bind(stage="pending_delivery")
        if delivery_processor is None:
            return
        if delivery_lock.locked():
            delivery_logger.debug("Пропуск доставки pending: предыдущий проход еще выполняется.")
            return

        async with delivery_lock:
            async def _send_message(delivery: PendingModeratorDelivery, text: str) -> None:
                reply_markup = None
                if delivery.author == SupportMessageAuthor.SYSTEM:
                    reply_markup = build_moderation_notification_inline_keyboard(str(delivery.ticket_id))
                await bot.send_message(
                    chat_id=int(delivery.target_external_id),
                    text=text,
                    reply_markup=reply_markup,
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

    @router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        """Обработчик команды `/start`."""

        event_logger = router_logger.bind(
            stage="start_command",
            user_id=str(message.from_user.id) if message.from_user else "-",
        )
        event_logger.debug("Получена команда /start.")
        await _try_process_pending_deliveries(message.bot)
        if message.from_user is None:
            event_logger.warning("Не удалось определить пользователя Telegram в /start.")
            await message.answer("Не удалось определить ваш Telegram-аккаунт. Повторите попытку.")
            return

        result = identity_adapter.start_interaction(telegram_user_id=message.from_user.id)
        support_prompt_message_id_by_user_id.pop(message.from_user.id, None)
        event_logger.info("Ответ /start сформирован. status={status}.", status=result.status)
        reply_markup = _choose_reply_markup(result)
        await _answer_with_result(message=message, result=result, reply_markup=reply_markup)

    @router.message(F.contact)
    async def contact_handler(message: Message) -> None:
        """Обработчик сообщения с контактом от пользователя."""

        event_logger = router_logger.bind(
            stage="contact_input",
            user_id=str(message.from_user.id) if message.from_user else "-",
        )
        event_logger.debug("Получен контакт пользователя.")
        await _try_process_pending_deliveries(message.bot)
        if message.contact is None or not message.contact.phone_number:
            event_logger.warning("Контакт не содержит номер телефона.")
            await message.answer("Не удалось прочитать контакт. Попробуйте отправить номер еще раз.")
            return

        if message.from_user is None:
            event_logger.warning("Не удалось определить пользователя Telegram для контакта.")
            await message.answer("Не удалось определить ваш Telegram-аккаунт. Повторите попытку.")
            return

        if message.contact.user_id and message.contact.user_id != message.from_user.id:
            event_logger.warning("Пользователь отправил чужой контакт.")
            await message.answer(
                "Для безопасности отправьте, пожалуйста, только свой собственный контакт."
            )
            return

        if not identity_adapter.expects_contact_input(message.from_user.id):
            event_logger.warning(
                "Контакт получен вне ожидаемого шага onboarding. Игнорируем контакт и возвращаем пользователя в актуальный экран."
            )
            menu_result = identity_adapter.start_interaction(telegram_user_id=message.from_user.id)
            reply_markup = _choose_reply_markup(menu_result)
            await _answer_with_result(message=message, result=menu_result, reply_markup=reply_markup)
            return

        result = identity_adapter.register_contact(
            telegram_user_id=message.from_user.id,
            raw_phone=message.contact.phone_number,
        )
        event_logger.info("Обработка контакта завершена. status={status}.", status=result.status)
        if result.status == "first_name_required":
            reply_markup = None
        elif result.status in {"notifications_consent_required", "notifications_consent_pending"}:
            reply_markup = build_notifications_consent_inline_keyboard()
        elif result.status in {"iiko_sync_retry", "iiko_sync_retry_pending"}:
            reply_markup = build_iiko_sync_retry_inline_keyboard()
        elif result.is_success:
            reply_markup = main_menu_inline_keyboard
        else:
            reply_markup = None
        await _answer_with_result(message=message, result=result, reply_markup=reply_markup)

    @router.message(F.text)
    async def text_menu_handler(message: Message) -> None:
        """Обработчик текстовых кнопок и команд меню."""

        event_logger = router_logger.bind(
            stage="text_input",
            user_id=str(message.from_user.id) if message.from_user else "-",
        )
        await _try_process_pending_deliveries(message.bot)
        if message.text is None:
            event_logger.debug("Пустое текстовое сообщение пропущено.")
            return
        event_logger.debug("Получен текстовый ввод: {text}.", text=message.text)
        if message.from_user is None:
            event_logger.warning("Не удалось определить пользователя Telegram для текстового ввода.")
            await message.answer("Не удалось определить ваш Telegram-аккаунт. Повторите попытку.")
            return

        normalized_text = message.text.strip().lower()
        if normalized_text == "начать":
            result = identity_adapter.start_interaction(telegram_user_id=message.from_user.id)
            support_prompt_message_id_by_user_id.pop(message.from_user.id, None)
            event_logger.info("Текстовая команда 'Начать' обработана. status={status}.", status=result.status)
            reply_markup = _choose_reply_markup(result)
            await _answer_with_result(message=message, result=result, reply_markup=reply_markup)
            return

        result = identity_adapter.handle_menu_action(
            telegram_user_id=message.from_user.id,
            action_text=message.text,
        )
        if result.status in {"support_question_submitted", "support_question_error"}:
            await _cleanup_support_prompt_message(
                bot=message.bot,
                chat_id=message.chat.id,
                user_id=message.from_user.id,
            )
        elif result.status != "support_question_input":
            support_prompt_message_id_by_user_id.pop(message.from_user.id, None)
        event_logger.info("Текстовый ввод обработан. status={status}.", status=result.status)
        reply_markup = _choose_reply_markup(result)
        await _answer_with_result(message=message, result=result, reply_markup=reply_markup)

    @router.message()
    async def non_text_menu_handler(message: Message) -> None:
        """Обрабатывает не-текстовые сообщения в рамках общего FSM-сценария."""

        # Команда/текст и контакт обрабатываются специализированными хендлерами выше.
        if message.text is not None or message.contact is not None:
            return

        event_logger = router_logger.bind(
            stage="non_text_input",
            user_id=str(message.from_user.id) if message.from_user else "-",
        )
        await _try_process_pending_deliveries(message.bot)
        if message.from_user is None:
            event_logger.warning("Не удалось определить пользователя Telegram для нетекстового ввода.")
            await message.answer("Не удалось определить ваш Telegram-аккаунт. Повторите попытку.")
            return

        result = identity_adapter.handle_menu_action(
            telegram_user_id=message.from_user.id,
            action_text="",
        )
        event_logger.info("Нетекстовый ввод обработан. status={status}.", status=result.status)
        reply_markup = _choose_reply_markup(result)
        await _answer_with_result(message=message, result=result, reply_markup=reply_markup)

    @router.callback_query(F.data == RULES_ACCEPT_CALLBACK)
    async def rules_accept_callback_handler(callback: CallbackQuery) -> None:
        """Обработчик inline-кнопки согласия с правилами."""

        event_logger = router_logger.bind(
            stage="rules_accept_callback",
            user_id=str(callback.from_user.id) if callback.from_user else "-",
        )
        await _try_process_pending_deliveries(callback.bot)

        if callback.from_user is None:
            event_logger.warning("Не удалось определить пользователя Telegram в callback согласия.")
            await callback.answer("Не удалось определить пользователя. Повторите /start.", show_alert=True)
            return

        result = identity_adapter.handle_menu_action(
            telegram_user_id=callback.from_user.id,
            action_text=BUTTON_ACCEPT_RULES,
        )
        event_logger.info("Callback согласия обработан. status={status}.", status=result.status)

        reply_markup = _choose_reply_markup(result)

        await callback.answer()
        if callback.message is not None:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception as error:  # noqa: BLE001
                if _is_message_not_modified_error(error):
                    event_logger.debug("Inline-клавиатура уже очищена после callback согласия.")
                else:
                    # Не блокируем сценарий, если исходную клавиатуру уже нельзя изменить.
                    event_logger.debug("Не удалось убрать старую inline-клавиатуру после callback.")
            await _answer_with_result(message=callback.message, result=result, reply_markup=reply_markup)
            return

        await _send_to_chat_with_result(
            bot=callback.bot,
            chat_id=callback.from_user.id,
            result=result,
            reply_markup=reply_markup,
        )

    @router.callback_query(F.data.in_([NOTIFY_YES_CALLBACK, NOTIFY_NO_CALLBACK]))
    async def notifications_consent_callback_handler(callback: CallbackQuery) -> None:
        """Обработчик inline-кнопок согласия/отказа по уведомлениям."""

        event_logger = router_logger.bind(
            stage="notifications_callback",
            user_id=str(callback.from_user.id) if callback.from_user else "-",
        )
        await _try_process_pending_deliveries(callback.bot)

        if callback.from_user is None:
            event_logger.warning("Не удалось определить пользователя Telegram в callback уведомлений.")
            await callback.answer("Не удалось определить пользователя. Повторите /start.", show_alert=True)
            return

        await callback.answer()
        pending_screen = build_iiko_sync_pending_screen()
        pending_result = TelegramMenuActionResult(
            status="iiko_sync_pending",
            message=pending_screen.text,
        )
        if callback.message is not None:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception as error:  # noqa: BLE001
                if _is_message_not_modified_error(error):
                    event_logger.debug("Inline-клавиатура уже очищена после callback уведомлений.")
                else:
                    event_logger.debug("Не удалось убрать старую inline-клавиатуру после callback уведомлений.")
            await _answer_with_result(message=callback.message, result=pending_result, reply_markup=None)
        else:
            await _send_to_chat_with_result(
                bot=callback.bot,
                chat_id=callback.from_user.id,
                result=pending_result,
                reply_markup=None,
            )

        result = identity_adapter.handle_menu_action(
            telegram_user_id=callback.from_user.id,
            action_text=callback.data or "",
        )
        event_logger.info("Callback уведомлений обработан. status={status}.", status=result.status)

        reply_markup = _choose_reply_markup(result)
        await _send_to_chat_with_result(
            bot=callback.bot,
            chat_id=callback.from_user.id,
            result=result,
            reply_markup=reply_markup,
        )

    @router.callback_query(F.data == "noop")
    async def noop_callback_handler(callback: CallbackQuery) -> None:
        """Подтверждает no-op callback пагинации без изменения сообщения."""

        event_logger = router_logger.bind(
            stage="noop_callback",
            user_id=str(callback.from_user.id) if callback.from_user else "-",
        )
        await _try_process_pending_deliveries(callback.bot)
        await callback.answer()
        event_logger.debug("No-op callback подтвержден без сценарного перехода.")

    @router.callback_query(
        F.data.startswith(USER_TICKET_DETAILS_PREFIX) |
        F.data.startswith(USER_TICKET_REPLY_PREFIX) |
        F.data.startswith(USER_TICKETS_PREV_PAGE_PREFIX) |
        F.data.startswith(USER_TICKETS_NEXT_PAGE_PREFIX) |
        F.data.startswith(USER_TICKETS_PAGE_PREFIX) |
        (F.data == MOD_MAIN_CALLBACK) |
        F.data.startswith(MOD_LIST_PREFIX) |
        F.data.startswith(MOD_PAGE_PREFIX) |
        F.data.startswith(MOD_TICKET_PREFIX) |
        F.data.startswith(MOD_REPLY_PREFIX) |
        F.data.startswith(MOD_TAKE_PREFIX) |
        F.data.startswith(MOD_CLOSE_PREFIX)
    )
    async def ticket_pagination_callback_handler(callback: CallbackQuery) -> None:
        """Обработчик inline-кнопок деталей тикета и пагинации списка обращений."""

        event_logger = router_logger.bind(
            stage="ticket_pagination_callback",
            user_id=str(callback.from_user.id) if callback.from_user else "-",
        )
        await _try_process_pending_deliveries(callback.bot)

        if callback.from_user is None:
            event_logger.warning("Не удалось определить пользователя Telegram в callback пагинации тикетов.")
            await callback.answer("Не удалось определить пользователя. Повторите /start.", show_alert=True)
            return

        result = identity_adapter.handle_menu_action(
            telegram_user_id=callback.from_user.id,
            action_text=callback.data,
        )
        event_logger.info("Callback пагинации тикетов обработан. status={status}.", status=result.status)

        reply_markup = _choose_reply_markup(result)

        await callback.answer()
        if callback.message is not None:
            if not isinstance(reply_markup, InlineKeyboardMarkup):
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                except Exception as error:  # noqa: BLE001
                    if _is_message_not_modified_error(error):
                        event_logger.debug("Inline-клавиатура уже очищена перед текстовым ответом.")
                    else:
                        event_logger.debug("Не удалось убрать inline-клавиатуру перед отправкой текстового ответа.")
                await _answer_with_result(message=callback.message, result=result, reply_markup=reply_markup)
                return
            try:
                await callback.message.edit_text(
                    result.message,
                    parse_mode=result.parse_mode,
                    reply_markup=reply_markup if isinstance(reply_markup, InlineKeyboardMarkup) else None,
                )
                return
            except Exception as error:  # noqa: BLE001
                if _is_message_not_modified_error(error):
                    event_logger.debug("Редактирование callback-сообщения не требуется: контент не изменился.")
                    return
                event_logger.debug("Не удалось перерисовать сообщение по callback, отправляем новое.")
                try:
                    await callback.message.delete()
                except Exception:  # noqa: BLE001
                    event_logger.debug("Не удалось удалить callback-сообщение перед fallback-отправкой.")

        await _send_to_chat_with_result(
            bot=callback.bot,
            chat_id=callback.from_user.id,
            result=result,
            reply_markup=reply_markup,
        )

    @router.callback_query(
        F.data.in_(
            [
                GuestMenuAction.BALANCE.value,
                GuestMenuAction.VIRTUAL_CARD.value,
                GuestMenuAction.DELIVERY.value,
                GuestMenuAction.BUSINESS_LUNCH.value,
                GuestMenuAction.TABLE_BOOKING.value,
                GuestMenuAction.SUPPORT.value,
                GuestMenuAction.VACANCIES.value,
                GuestMenuAction.PROFILE.value,
                GuestMenuAction.SUPPORT_FEEDBACK.value,
                GuestMenuAction.SUPPORT_QUESTION.value,
                GuestMenuAction.SUPPORT_QUESTION_FROM_LIST.value,
                GuestMenuAction.SUPPORT_CONTACTS.value,
                GuestMenuAction.MY_TICKETS.value,
                GuestMenuAction.BACK_TO_MAIN.value,
                GuestMenuAction.BACK_TO_SUPPORT.value,
                GuestMenuAction.PROFILE_EDIT.value,
                GuestMenuAction.PROFILE_EDIT_FIRST_NAME.value,
                GuestMenuAction.PROFILE_EDIT_LAST_NAME.value,
                GuestMenuAction.PROFILE_EDIT_GENDER.value,
                GuestMenuAction.PROFILE_EDIT_BIRTH_DATE.value,
                GuestMenuAction.PROFILE_EDIT_EMAIL.value,
                GuestMenuAction.PROFILE_EDIT_CANCEL.value,
                GuestMenuAction.PROFILE_EDIT_GENDER_MALE.value,
                GuestMenuAction.PROFILE_EDIT_GENDER_FEMALE.value,
                GuestMenuAction.RETRY_IIKO_SYNC.value,
                # Поддерживаем старые callback_data, которые могли остаться в уже отправленных сообщениях.
                BUTTON_BALANCE,
                BUTTON_VIRTUAL_CARD,
                BUTTON_DELIVERY,
                BUTTON_BUSINESS_LUNCH,
                BUTTON_TABLE_BOOKING,
                BUTTON_SUPPORT,
                BUTTON_VACANCIES,
                BUTTON_PROFILE,
                BUTTON_SUPPORT_FEEDBACK,
                BUTTON_SUPPORT_QUESTION,
                BUTTON_SUPPORT_CONTACTS,
                BUTTON_MY_TICKETS,
                BUTTON_BACK_TO_MAIN,
                BUTTON_BACK_TO_SUPPORT,
                BUTTON_PROFILE_EDIT,
                BUTTON_PROFILE_EDIT_FIRST_NAME,
                BUTTON_PROFILE_EDIT_LAST_NAME,
                BUTTON_PROFILE_EDIT_GENDER,
                BUTTON_PROFILE_EDIT_BIRTH_DATE,
                BUTTON_PROFILE_EDIT_EMAIL,
                BUTTON_PROFILE_EDIT_CANCEL,
                BUTTON_PROFILE_EDIT_GENDER_MALE,
                BUTTON_PROFILE_EDIT_GENDER_FEMALE,
                BUTTON_RETRY_IIKO_SYNC,
            ]
        )
    )
    async def main_menu_callback_handler(callback: CallbackQuery) -> None:
        """Обработчик inline-кнопок меню и профиля."""

        event_logger = router_logger.bind(
            stage="main_menu_callback",
            user_id=str(callback.from_user.id) if callback.from_user else "-",
        )
        await _try_process_pending_deliveries(callback.bot)

        if callback.from_user is None:
            event_logger.warning("Не удалось определить пользователя Telegram в callback меню.")
            await callback.answer("Не удалось определить пользователя. Повторите /start.", show_alert=True)
            return

        await callback.answer()
        if (callback.data or "") not in {
            GuestMenuAction.SUPPORT_QUESTION.value,
            GuestMenuAction.SUPPORT_QUESTION_FROM_LIST.value,
            BUTTON_SUPPORT_QUESTION,
        }:
            support_prompt_message_id_by_user_id.pop(callback.from_user.id, None)
        is_iiko_retry = (callback.data or "") in {
            GuestMenuAction.RETRY_IIKO_SYNC.value,
            BUTTON_RETRY_IIKO_SYNC,
        }
        if is_iiko_retry:
            pending_screen = build_iiko_sync_pending_screen()
            pending_result = TelegramMenuActionResult(
                status="iiko_sync_pending",
                message=pending_screen.text,
            )
            if callback.message is not None:
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                except Exception as error:  # noqa: BLE001
                    if _is_message_not_modified_error(error):
                        event_logger.debug("Inline-клавиатура уже очищена перед retry iiko.")
                    else:
                        event_logger.debug("Не удалось убрать inline-клавиатуру перед retry iiko.")
                await _answer_with_result(
                    message=callback.message,
                    result=pending_result,
                    reply_markup=None,
                )
            else:
                await _send_to_chat_with_result(
                    bot=callback.bot,
                    chat_id=callback.from_user.id,
                    result=pending_result,
                    reply_markup=None,
                )

        result = identity_adapter.handle_menu_action(
            telegram_user_id=callback.from_user.id,
            action_text=callback.data,
        )
        event_logger.info("Callback меню обработан. status={status}.", status=result.status)

        reply_markup = _choose_reply_markup(result)

        if result.status == "virtual_card" and result.virtual_card_numbers:
            if callback.message is not None:
                try:
                    await callback.message.delete()
                except Exception as error:  # noqa: BLE001
                    if _is_message_not_modified_error(error):
                        event_logger.debug("Callback-сообщение уже обновлено перед отправкой QR-кодов.")
                    else:
                        try:
                            await callback.message.edit_reply_markup(reply_markup=None)
                        except Exception:  # noqa: BLE001
                            event_logger.debug(
                                "Не удалось удалить callback-сообщение перед отправкой QR-кодов, продолжаем сценарий."
                            )
            await _send_to_chat_with_result(
                bot=callback.bot,
                chat_id=callback.from_user.id,
                result=result,
                reply_markup=reply_markup,
            )
            return

        if callback.message is not None:
            if not isinstance(reply_markup, InlineKeyboardMarkup):
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                except Exception as error:  # noqa: BLE001
                    if _is_message_not_modified_error(error):
                        event_logger.debug("Inline-клавиатура уже очищена перед текстовым ответом.")
                    else:
                        event_logger.debug("Не удалось убрать inline-клавиатуру перед отправкой текстового ответа.")
                await _answer_with_result(message=callback.message, result=result, reply_markup=reply_markup)
                return
            try:
                await callback.message.edit_text(
                    result.message,
                    parse_mode=result.parse_mode,
                    reply_markup=reply_markup if isinstance(reply_markup, InlineKeyboardMarkup) else None,
                )
                if result.status in {
                    "support_question",
                    "support_question_empty",
                    "support_question_unavailable",
                    "support_question_input",
                    "support_reply_input",
                    "support_reply_empty",
                    "support_reply_error",
                }:
                    _remember_support_prompt_message(
                        user_id=callback.from_user.id,
                        message_id=callback.message.message_id,
                    )
                return
            except Exception as error:  # noqa: BLE001
                if _is_message_not_modified_error(error):
                    event_logger.debug("Редактирование callback-сообщения не требуется: контент не изменился.")
                    return
                # Не блокируем сценарий, если исходную клавиатуру уже нельзя изменить.
                event_logger.debug("Не удалось перерисовать сообщение по callback, отправляем новое.")
                try:
                    await callback.message.delete()
                except Exception:  # noqa: BLE001
                    event_logger.debug("Не удалось удалить callback-сообщение перед fallback-отправкой.")

        await _send_to_chat_with_result(
            bot=callback.bot,
            chat_id=callback.from_user.id,
            result=result,
            reply_markup=reply_markup,
        )
    return router
