"""Aiogram-router для сценария строгой идентификации в Telegram."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from .identity_adapter import TelegramIdentityAdapter
from .menu import build_contact_request_keyboard, build_main_menu_keyboard


def build_telegram_identity_router(identity_adapter: TelegramIdentityAdapter) -> Router:
    """Создает router Telegram с обработчиками регистрации по телефону."""

    router = Router(name="telegram_identity")
    request_contact_keyboard = build_contact_request_keyboard()
    main_menu_keyboard = build_main_menu_keyboard()

    @router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        """Обработчик команды `/start`."""

        await message.answer(
            identity_adapter.build_start_message(),
            reply_markup=request_contact_keyboard,
        )

    @router.message(F.contact)
    async def contact_handler(message: Message) -> None:
        """Обработчик сообщения с контактом от пользователя."""

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

        if message.from_user is None:
            await message.answer("Не удалось определить ваш Telegram-аккаунт. Повторите попытку.")
            return

        result = identity_adapter.handle_menu_action(
            telegram_user_id=message.from_user.id,
            action_text="/menu",
        )
        await message.answer(
            result.message,
            parse_mode=result.parse_mode,
            reply_markup=main_menu_keyboard,
        )

    @router.message(F.text)
    async def text_menu_handler(message: Message) -> None:
        """Обработчик текстовых кнопок и команд меню."""

        if message.text is None:
            return
        if message.from_user is None:
            await message.answer("Не удалось определить ваш Telegram-аккаунт. Повторите попытку.")
            return

        result = identity_adapter.handle_menu_action(
            telegram_user_id=message.from_user.id,
            action_text=message.text,
        )
        reply_markup = request_contact_keyboard if result.requires_contact_keyboard else main_menu_keyboard
        await message.answer(
            result.message,
            parse_mode=result.parse_mode,
            reply_markup=reply_markup,
        )

    return router
