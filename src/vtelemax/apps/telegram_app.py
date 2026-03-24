"""Точка входа Telegram-бота на aiogram."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy.orm import Session, sessionmaker

from vtelemax.adapters.telegram import TelegramIdentityAdapter, build_telegram_identity_router
from vtelemax.core import (
    GetPersonByAccountTransactionalUseCase,
    RegisterOrAttachAccountTransactionalUseCase,
)
from vtelemax.infrastructure.postgres import (
    Base,
    SQLAlchemyIdentityUnitOfWork,
    build_engine,
    build_session_factory,
)
from vtelemax.settings import AppSettings


def build_postgres_session_factory(settings: AppSettings) -> sessionmaker[Session]:
    """Создает session factory PostgreSQL с учетом настроек проекта."""

    engine = build_engine(settings.postgres_sqlalchemy_dsn, echo=settings.postgres_echo)
    if settings.postgres_auto_create_schema:
        # Для локальной разработки можно включать автосоздание таблиц.
        Base.metadata.create_all(engine)
    return build_session_factory(engine)


def build_identity_use_case(
    session_factory: sessionmaker[Session],
) -> RegisterOrAttachAccountTransactionalUseCase:
    """Собирает транзакционный use-case strict identity."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_person_lookup_use_case(
    session_factory: sessionmaker[Session],
) -> GetPersonByAccountTransactionalUseCase:
    """Собирает транзакционный use-case чтения пользователя по аккаунту."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return GetPersonByAccountTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_dispatcher(settings: AppSettings) -> Dispatcher:
    """Собирает Dispatcher Telegram-бота с подключенным маршрутом идентификации."""

    session_factory = build_postgres_session_factory(settings)
    registration_use_case = build_identity_use_case(session_factory)
    person_lookup_use_case = build_person_lookup_use_case(session_factory)
    identity_adapter = TelegramIdentityAdapter(registration_use_case, person_lookup_use_case)

    dispatcher = Dispatcher()
    dispatcher.include_router(build_telegram_identity_router(identity_adapter))
    return dispatcher


async def run_telegram_bot(settings: AppSettings | None = None) -> None:
    """Запускает Telegram-бота в polling-режиме."""

    app_settings = settings or AppSettings()
    app_settings.validate_telegram_ready()

    bot = Bot(
        token=app_settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher(app_settings)
    await dispatcher.start_polling(bot)


def main() -> None:
    """Синхронная точка входа для запуска из командной строки."""

    asyncio.run(run_telegram_bot())


if __name__ == "__main__":
    main()
