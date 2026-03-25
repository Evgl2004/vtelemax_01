"""Aiogram-router для сценария строгой идентификации в Telegram."""

from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message
from loguru import logger

from vtelemax.core import BUTTON_ACCEPT_RULES
from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor

from .identity_adapter import TelegramIdentityAdapter
from .menu import (
    RULES_ACCEPT_CALLBACK,
    build_contact_request_keyboard,
    build_main_menu_keyboard,
    build_rules_consent_inline_keyboard,
)


def build_telegram_identity_router(
    identity_adapter: TelegramIdentityAdapter,
    delivery_processor: PendingModeratorDeliveryProcessor | None = None,
) -> Router:
    """Создает router Telegram с обработчиками регистрации по телефону."""

    router = Router(name="telegram_identity")
    router_logger = logger.bind(platform="telegram", component="router")
    request_contact_keyboard = build_contact_request_keyboard()
    main_menu_keyboard = build_main_menu_keyboard()
    rules_consent_keyboard = build_rules_consent_inline_keyboard()
    delivery_lock = asyncio.Lock()

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
        if result.requires_contact_keyboard:
            reply_markup = request_contact_keyboard
        elif result.status in {"rules_consent_required", "rules_consent_pending"}:
            reply_markup = rules_consent_keyboard
        elif result.status == "menu":
            reply_markup = main_menu_keyboard
        else:
            reply_markup = None

        await message.answer(
            result.message,
            reply_markup=reply_markup,
        )

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
        reply_markup = request_contact_keyboard if result.requires_contact_keyboard else None
        await message.answer(result.message, reply_markup=reply_markup)

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
        reply_markup = main_menu_keyboard if result.is_success else request_contact_keyboard
        await message.answer(result.message, reply_markup=reply_markup)

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
        if result.requires_contact_keyboard:
            reply_markup = request_contact_keyboard
        elif result.status in {"rules_consent_required", "rules_consent_pending"}:
            reply_markup = rules_consent_keyboard
        else:
            reply_markup = main_menu_keyboard
        await message.answer(
            result.message,
            parse_mode=result.parse_mode,
            reply_markup=reply_markup,
        )

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
        if result.requires_contact_keyboard:
            reply_markup = request_contact_keyboard
        elif result.status in {"rules_consent_required", "rules_consent_pending"}:
            reply_markup = rules_consent_keyboard
        else:
            reply_markup = main_menu_keyboard
        await message.answer(
            result.message,
            parse_mode=result.parse_mode,
            reply_markup=reply_markup,
        )

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

        if result.requires_contact_keyboard:
            reply_markup = request_contact_keyboard
        elif result.status in {"rules_consent_required", "rules_consent_pending"}:
            reply_markup = rules_consent_keyboard
        else:
            reply_markup = main_menu_keyboard

        await callback.answer()
        if callback.message is not None:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:  # noqa: BLE001
                # Не блокируем сценарий, если исходную клавиатуру уже нельзя изменить.
                event_logger.debug("Не удалось убрать старую inline-клавиатуру после callback.")
            await callback.message.answer(
                result.message,
                parse_mode=result.parse_mode,
                reply_markup=reply_markup,
            )
            return

        await callback.bot.send_message(
            chat_id=callback.from_user.id,
            text=result.message,
            parse_mode=result.parse_mode,
            reply_markup=reply_markup,
        )

    return router
