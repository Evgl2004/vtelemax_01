"""Aiogram-router для сценария строгой идентификации в Telegram."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from .identity_adapter import TelegramIdentityAdapter


def build_telegram_identity_router(identity_adapter: TelegramIdentityAdapter) -> Router:
    """Создает router Telegram с обработчиками регистрации по телефону."""

    router = Router(name="telegram_identity")

    request_contact_keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="Отправить номер телефона",
                    request_contact=True,
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    @router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        """Обработчик команды `/start`."""

        await message.answer(
            "Здравствуйте. Для регистрации в единой базе нажмите кнопку и отправьте ваш номер телефона.",
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
        await message.answer(result.message)

    return router
