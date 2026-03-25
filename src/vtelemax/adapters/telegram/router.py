"""Aiogram-router для сценария строгой идентификации в Telegram."""

from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor

from .identity_adapter import TelegramIdentityAdapter
from .menu import build_contact_request_keyboard, build_main_menu_keyboard


def build_telegram_identity_router(
    identity_adapter: TelegramIdentityAdapter,
    delivery_processor: PendingModeratorDeliveryProcessor | None = None,
) -> Router:
    """Создает router Telegram с обработчиками регистрации по телефону."""

    router = Router(name="telegram_identity")
    request_contact_keyboard = build_contact_request_keyboard()
    main_menu_keyboard = build_main_menu_keyboard()
    delivery_lock = asyncio.Lock()

    async def _try_process_pending_deliveries(bot: Bot) -> None:
        """Пытается доставить pending-сообщения модератора без влияния на UX пользователя."""

        if delivery_processor is None:
            return
        if delivery_lock.locked():
            return

        async with delivery_lock:
            async def _send_message(target_external_id: str, text: str) -> None:
                await bot.send_message(chat_id=int(target_external_id), text=text)

            try:
                await delivery_processor.process_once(sender=_send_message, limit=20)
            except Exception:  # noqa: BLE001
                # На MVP-этапе не прерываем пользовательский сценарий из-за сбоя доставки.
                return

    @router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        """Обработчик команды `/start`."""

        await _try_process_pending_deliveries(message.bot)
        if message.from_user is None:
            await message.answer("Не удалось определить ваш Telegram-аккаунт. Повторите попытку.")
            return

        result = identity_adapter.start_interaction(telegram_user_id=message.from_user.id)
        if result.requires_contact_keyboard:
            reply_markup = request_contact_keyboard
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

        await _try_process_pending_deliveries(message.bot)
        if message.from_user is None:
            await message.answer("Не удалось определить ваш Telegram-аккаунт. Повторите попытку.")
            return

        result = identity_adapter.start_interaction(
            telegram_user_id=message.from_user.id,
            force_legacy_upgrade=True,
        )
        reply_markup = request_contact_keyboard if result.requires_contact_keyboard else None
        await message.answer(result.message, reply_markup=reply_markup)

    @router.message(F.contact)
    async def contact_handler(message: Message) -> None:
        """Обработчик сообщения с контактом от пользователя."""

        await _try_process_pending_deliveries(message.bot)
        if message.contact is None or not message.contact.phone_number:
            await message.answer("Не удалось прочитать контакт. Попробуйте отправить номер еще раз.")
            return

        if message.from_user is None:
            await message.answer("Не удалось определить ваш Telegram-аккаунт. Повторите попытку.")
            return

        if message.contact.user_id and message.contact.user_id != message.from_user.id:
            await message.answer(
                "Для безопасности отправьте, пожалуйста, только свой собственный контакт."
            )
            return

        result = identity_adapter.register_contact(
            telegram_user_id=message.from_user.id,
            raw_phone=message.contact.phone_number,
        )
        reply_markup = main_menu_keyboard if result.is_success else request_contact_keyboard
        await message.answer(result.message, reply_markup=reply_markup)

    @router.message(Command("menu"))
    async def command_menu_handler(message: Message) -> None:
        """Обработчик команды `/menu`."""

        await _try_process_pending_deliveries(message.bot)
        if message.from_user is None:
            await message.answer("Не удалось определить ваш Telegram-аккаунт. Повторите попытку.")
            return

        result = identity_adapter.handle_menu_action(
            telegram_user_id=message.from_user.id,
            action_text="/menu",
        )
        if result.requires_contact_keyboard:
            reply_markup = request_contact_keyboard
        elif result.status in {"rules_consent_required", "rules_consent_pending"}:
            reply_markup = None
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

        await _try_process_pending_deliveries(message.bot)
        if message.text is None:
            return
        if message.from_user is None:
            await message.answer("Не удалось определить ваш Telegram-аккаунт. Повторите попытку.")
            return

        result = identity_adapter.handle_menu_action(
            telegram_user_id=message.from_user.id,
            action_text=message.text,
        )
        if result.requires_contact_keyboard:
            reply_markup = request_contact_keyboard
        elif result.status in {"rules_consent_required", "rules_consent_pending"}:
            reply_markup = None
        else:
            reply_markup = main_menu_keyboard
        await message.answer(
            result.message,
            parse_mode=result.parse_mode,
            reply_markup=reply_markup,
        )

    return router
