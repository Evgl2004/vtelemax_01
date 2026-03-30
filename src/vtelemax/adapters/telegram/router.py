"""Aiogram-router для сценария строгой идентификации в Telegram."""

from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from loguru import logger

from vtelemax.core import BUTTON_ACCEPT_RULES
from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor
from vtelemax.infrastructure import QrGenerationError, generate_qr_png_bytes

from .identity_adapter import TelegramIdentityAdapter, TelegramMenuActionResult
from .menu import (
    NOTIFY_NO_CALLBACK,
    NOTIFY_YES_CALLBACK,
    RULES_ACCEPT_CALLBACK,
    BUTTON_BACK_TO_MAIN,
    BUTTON_BACK_TO_SUPPORT,
    BUTTON_PROFILE_EDIT,
    BUTTON_PROFILE_EDIT_BIRTH_DATE,
    BUTTON_PROFILE_EDIT_CANCEL,
    BUTTON_PROFILE_EDIT_EMAIL,
    BUTTON_PROFILE_EDIT_FIRST_NAME,
    BUTTON_PROFILE_EDIT_GENDER,
    BUTTON_PROFILE_EDIT_GENDER_FEMALE,
    BUTTON_PROFILE_EDIT_GENDER_MALE,
    BUTTON_PROFILE_EDIT_LAST_NAME,
    BUTTON_SUPPORT_CONTACTS,
    BUTTON_SUPPORT_FEEDBACK,
    BUTTON_SUPPORT_QUESTION,
    BUTTON_MY_TICKETS,
    build_back_to_main_inline_keyboard,
    build_back_to_support_inline_keyboard,
    build_main_menu_inline_keyboard,
    build_notifications_consent_inline_keyboard,
    build_profile_edit_inline_keyboard,
    build_profile_gender_inline_keyboard,
    build_profile_inline_keyboard,
    build_rules_consent_inline_keyboard,
    build_support_menu_inline_keyboard,
    BUTTON_PROFILE,
    BUTTON_SUPPORT,
    BUTTON_BALANCE,
    BUTTON_VIRTUAL_CARD,
    BUTTON_VACANCIES,
)


def _is_message_not_modified_error(error: Exception) -> bool:
    """Проверяет, что ошибка редактирования связана только с отсутствием изменений."""

    if isinstance(error, TelegramBadRequest):
        text = str(error).lower()
        return "message is not modified" in text or "message_not_modified" in text
    text = str(error).lower()
    return "message is not modified" in text or "message_not_modified" in text


def build_telegram_identity_router(
    identity_adapter: TelegramIdentityAdapter,
    delivery_processor: PendingModeratorDeliveryProcessor | None = None,
) -> Router:
    """Создает router Telegram с обработчиками регистрации по телефону."""

    router = Router(name="telegram_identity")
    router_logger = logger.bind(platform="telegram", component="router")
    main_menu_inline_keyboard = build_main_menu_inline_keyboard()
    back_to_main_keyboard = build_back_to_main_inline_keyboard()
    back_to_support_keyboard = build_back_to_support_inline_keyboard()
    profile_keyboard = build_profile_inline_keyboard()
    delivery_lock = asyncio.Lock()
    legacy_reply_keyboard_cleaned_chats: set[int] = set()

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
        result: TelegramMenuActionResult,
    ) -> None:
        """Отправляет QR-коды виртуальных карт отдельными сообщениями перед итоговым текстом."""

        if result.status != "virtual_card" or not result.virtual_card_numbers:
            return

        qr_logger = router_logger.bind(stage="virtual_card_qr", user_id=str(chat_id))
        for index, card_number in enumerate(result.virtual_card_numbers, start=1):
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

    async def _cleanup_legacy_reply_keyboard_once(*, bot: Bot, chat_id: int) -> None:
        """Один раз очищает legacy reply-клавиатуру в чате перед inline-сценариями."""

        if chat_id in legacy_reply_keyboard_cleaned_chats:
            return

        cleanup_logger = router_logger.bind(stage="reply_keyboard_cleanup", user_id=str(chat_id))
        try:
            cleanup_message = await bot.send_message(
                chat_id=chat_id,
                text="\u2060",
                reply_markup=ReplyKeyboardRemove(),
            )
        except Exception:  # noqa: BLE001
            cleanup_logger.debug("Не удалось отправить служебную очистку reply-клавиатуры.")
            legacy_reply_keyboard_cleaned_chats.add(chat_id)
            return

        try:
            await bot.delete_message(chat_id=chat_id, message_id=cleanup_message.message_id)
        except Exception:  # noqa: BLE001
            # Не блокируем основной сценарий, если удалить служебное сообщение не удалось.
            cleanup_logger.debug("Не удалось удалить служебное сообщение очистки reply-клавиатуры.")
        finally:
            legacy_reply_keyboard_cleaned_chats.add(chat_id)

    async def _answer_with_result(
        *,
        message: Message,
        result: TelegramMenuActionResult,
        reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None,
    ) -> None:
        """Отправляет результат адаптера для message-handler, включая QR при необходимости."""

        if isinstance(reply_markup, InlineKeyboardMarkup):
            await _cleanup_legacy_reply_keyboard_once(bot=message.bot, chat_id=message.chat.id)
        await _send_virtual_card_qr(bot=message.bot, chat_id=message.chat.id, result=result)
        await message.answer(
            result.message,
            parse_mode=result.parse_mode,
            reply_markup=_with_reply_keyboard_cleanup(reply_markup),
        )

    async def _send_to_chat_with_result(
        *,
        bot: Bot,
        chat_id: int,
        result: TelegramMenuActionResult,
        reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None,
    ) -> None:
        """Отправляет результат адаптера напрямую в чат, включая QR при необходимости."""

        if isinstance(reply_markup, InlineKeyboardMarkup):
            await _cleanup_legacy_reply_keyboard_once(bot=bot, chat_id=chat_id)
        await _send_virtual_card_qr(bot=bot, chat_id=chat_id, result=result)
        await bot.send_message(
            chat_id=chat_id,
            text=result.message,
            parse_mode=result.parse_mode,
            reply_markup=_with_reply_keyboard_cleanup(reply_markup),
        )

    def _choose_reply_markup(result: TelegramMenuActionResult) -> InlineKeyboardMarkup | ReplyKeyboardMarkup | None:
        """Выбирает клавиатуру для ответа на основе результата адаптера."""
        if result.status in {"rules_consent_required", "rules_consent_pending"}:
            return build_rules_consent_inline_keyboard()
        if result.status in {"phone_required", "phone_validation_error"}:
            return None
        if result.status in {"notifications_consent_required", "notifications_consent_pending"}:
            return build_notifications_consent_inline_keyboard()
        if result.status in {"support", "tickets_list", "tickets_empty"}:
            return build_support_menu_inline_keyboard(has_tickets=result.has_support_tickets)
        if result.status in {"support_feedback", "support_question", "support_contacts", "support_question_empty"}:
            return back_to_support_keyboard
        if result.status in {
            "balance",
            "balance_unavailable",
            "virtual_card",
            "virtual_card_error",
            "virtual_card_unavailable",
            "vacancies",
            "help",
            "about",
            "support_question_submitted",
            "support_question_error",
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
            async def _send_message(target_external_id: str, text: str) -> None:
                await bot.send_message(chat_id=int(target_external_id), text=text)

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
        event_logger.info("Ответ /start сформирован. status={status}.", status=result.status)
        reply_markup = _choose_reply_markup(result)
        await _answer_with_result(message=message, result=result, reply_markup=reply_markup)

    @router.message(Command("legacy"))
    async def legacy_start_handler(message: Message) -> None:
        """Явный запуск legacy-ветки обновления профиля."""

        event_logger = router_logger.bind(
            stage="legacy_command",
            user_id=str(message.from_user.id) if message.from_user else "-",
        )
        event_logger.debug("Получена команда /legacy.")
        await _try_process_pending_deliveries(message.bot)
        if message.from_user is None:
            event_logger.warning("Не удалось определить пользователя Telegram в /legacy.")
            await message.answer("Не удалось определить ваш Telegram-аккаунт. Повторите попытку.")
            return

        result = identity_adapter.start_interaction(
            telegram_user_id=message.from_user.id,
            force_legacy_upgrade=True,
        )
        event_logger.info("Legacy-flow запущен. status={status}.", status=result.status)
        await _answer_with_result(message=message, result=result, reply_markup=None)

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

        result = identity_adapter.register_contact(
            telegram_user_id=message.from_user.id,
            raw_phone=message.contact.phone_number,
        )
        event_logger.info("Обработка контакта завершена. status={status}.", status=result.status)
        if result.status == "first_name_required":
            reply_markup = None
        elif result.is_success:
            reply_markup = main_menu_inline_keyboard
        else:
            reply_markup = None
        await _answer_with_result(message=message, result=result, reply_markup=reply_markup)

    @router.message(Command("menu"))
    async def command_menu_handler(message: Message) -> None:
        """Обработчик команды `/menu`."""

        event_logger = router_logger.bind(
            stage="menu_command",
            user_id=str(message.from_user.id) if message.from_user else "-",
        )
        event_logger.debug("Получена команда /menu.")
        await _try_process_pending_deliveries(message.bot)
        if message.from_user is None:
            event_logger.warning("Не удалось определить пользователя Telegram в /menu.")
            await message.answer("Не удалось определить ваш Telegram-аккаунт. Повторите попытку.")
            return

        result = identity_adapter.handle_menu_action(
            telegram_user_id=message.from_user.id,
            action_text="/menu",
        )
        event_logger.info("Ответ /menu сформирован. status={status}.", status=result.status)
        reply_markup = _choose_reply_markup(result)
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

        result = identity_adapter.handle_menu_action(
            telegram_user_id=message.from_user.id,
            action_text=message.text,
        )
        event_logger.info("Текстовый ввод обработан. status={status}.", status=result.status)
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

        result = identity_adapter.handle_menu_action(
            telegram_user_id=callback.from_user.id,
            action_text=callback.data or "",
        )
        event_logger.info("Callback уведомлений обработан. status={status}.", status=result.status)

        reply_markup = _choose_reply_markup(result)

        await callback.answer()
        if callback.message is not None:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception as error:  # noqa: BLE001
                if _is_message_not_modified_error(error):
                    event_logger.debug("Inline-клавиатура уже очищена после callback уведомлений.")
                else:
                    event_logger.debug("Не удалось убрать старую inline-клавиатуру после callback уведомлений.")
            await _answer_with_result(message=callback.message, result=result, reply_markup=reply_markup)
            return

        await _send_to_chat_with_result(
            bot=callback.bot,
            chat_id=callback.from_user.id,
            result=result,
            reply_markup=reply_markup,
        )

    @router.callback_query(
        F.data.in_(
            [
                BUTTON_BALANCE,
                BUTTON_VIRTUAL_CARD,
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

        result = identity_adapter.handle_menu_action(
            telegram_user_id=callback.from_user.id,
            action_text=callback.data,
        )
        event_logger.info("Callback меню обработан. status={status}.", status=result.status)

        reply_markup = _choose_reply_markup(result)

        await callback.answer()
        if result.status == "virtual_card" and result.virtual_card_numbers:
            if callback.message is not None:
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                except Exception as error:  # noqa: BLE001
                    if _is_message_not_modified_error(error):
                        event_logger.debug("Inline-клавиатура уже очищена перед отправкой QR-кодов.")
                    else:
                        event_logger.debug("Не удалось убрать inline-клавиатуру перед отправкой QR-кодов.")
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
                return
            except Exception as error:  # noqa: BLE001
                if _is_message_not_modified_error(error):
                    event_logger.debug("Редактирование callback-сообщения не требуется: контент не изменился.")
                    return
                # Не блокируем сценарий, если исходную клавиатуру уже нельзя изменить.
                event_logger.debug("Не удалось перерисовать сообщение по callback, отправляем новое.")

        await _send_to_chat_with_result(
            bot=callback.bot,
            chat_id=callback.from_user.id,
            result=result,
            reply_markup=reply_markup,
        )
    return router
