"""Точка входа MAX-бота на maxapi."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from vtelemax.adapters.max import MaxIdentityAdapter, register_max_guest_handlers
from vtelemax.core import (
    CreateSupportTicketTransactionalUseCase,
    GetPersonByAccountTransactionalUseCase,
    GetSupportTicketDetailsTransactionalUseCase,
    RegisterOrAttachAccountTransactionalUseCase,
    RouteModeratorReplyTransactionalUseCase,
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
        Base.metadata.create_all(engine)
    return build_session_factory(engine)


def build_identity_use_case(
    session_factory: sessionmaker[Session],
) -> RegisterOrAttachAccountTransactionalUseCase:
    """Собирает транзакционный use-case регистрации/привязки аккаунта."""

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


def build_create_support_ticket_use_case(
    session_factory: sessionmaker[Session],
) -> CreateSupportTicketTransactionalUseCase:
    """Собирает транзакционный use-case создания тикета поддержки."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_moderator_reply_use_case(
    session_factory: sessionmaker[Session],
) -> RouteModeratorReplyTransactionalUseCase:
    """Собирает транзакционный use-case маршрутизации ответа модератора."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return RouteModeratorReplyTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_ticket_details_use_case(
    session_factory: sessionmaker[Session],
) -> GetSupportTicketDetailsTransactionalUseCase:
    """Собирает транзакционный use-case карточки тикета для модератора."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return GetSupportTicketDetailsTransactionalUseCase(unit_of_work_factory=uow_factory)


def _import_maxapi_runtime() -> tuple[type[Any], type[Any], type[Any]]:
    """Импортирует runtime-классы maxapi только в момент запуска."""

    try:
        from maxapi import Bot, Dispatcher, Router
    except ImportError as exc:
        raise RuntimeError(
            "Для запуска MAX-бота установите extra-зависимости: pip install -e .[max]"
        ) from exc
    return Bot, Dispatcher, Router


def build_dispatcher(settings: AppSettings) -> Any:
    """Собирает Dispatcher MAX-бота с подключенным маршрутом идентификации."""

    _, Dispatcher, Router = _import_maxapi_runtime()

    session_factory = build_postgres_session_factory(settings)
    registration_use_case = build_identity_use_case(session_factory)
    lookup_use_case = build_person_lookup_use_case(session_factory)
    create_ticket_use_case = build_create_support_ticket_use_case(session_factory)
    moderator_reply_use_case = build_moderator_reply_use_case(session_factory)
    ticket_details_use_case = build_ticket_details_use_case(session_factory)
    adapter = MaxIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        moderator_reply_use_case=moderator_reply_use_case,
        ticket_details_use_case=ticket_details_use_case,
    )

    dispatcher = Dispatcher()
    router = Router()
    register_max_guest_handlers(router, adapter)
    dispatcher.include_routers(router)
    return dispatcher


async def run_max_bot(settings: AppSettings | None = None) -> None:
    """Запускает MAX-бота в polling-режиме."""

    app_settings = settings or AppSettings()
    app_settings.validate_max_ready()

    Bot, _, _ = _import_maxapi_runtime()
    bot = Bot(token=app_settings.max_bot_token)
    dispatcher = build_dispatcher(app_settings)
    await dispatcher.start_polling(bot)


def main() -> None:
    """Синхронная точка входа запуска MAX-бота."""

    asyncio.run(run_max_bot())


if __name__ == "__main__":
    main()
