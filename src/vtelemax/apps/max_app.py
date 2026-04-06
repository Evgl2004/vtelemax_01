"""Точка входа MAX-бота на maxapi."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker

from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor
from vtelemax.adapters.max import MaxIdentityAdapter, register_max_guest_handlers
from vtelemax.core import (
    CreateSupportTicketTransactionalUseCase,
    GetPersonByAccountTransactionalUseCase,
    GetLoyaltyBalanceUseCase,
    GetVirtualCardUseCase,
    ListOpenSupportTicketsTransactionalUseCase,
    ListPersonSupportTicketsTransactionalUseCase,
    GetPersonTicketsPageTransactionalUseCase,
    GetSupportTicketConversationTransactionalUseCase,
    GetSupportTicketDetailsTransactionalUseCase,
    PullPendingModeratorMessagesTransactionalUseCase,
    RegisterOrAttachAccountTransactionalUseCase,
    RouteModeratorReplyTransactionalUseCase,
    SetSupportTicketStatusTransactionalUseCase,
    UpdateModeratorMessageDeliveryStatusTransactionalUseCase,
)
from vtelemax.infrastructure.postgres import (
    Base,
    SQLAlchemyIdentityUnitOfWork,
    build_engine,
    build_session_factory,
)
from vtelemax.infrastructure import IikoLoyaltyGateway, configure_logging
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


def build_ticket_conversation_use_case(
    session_factory: sessionmaker[Session],
) -> GetSupportTicketConversationTransactionalUseCase:
    """Собирает транзакционный use-case карточки тикета с историей сообщений."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return GetSupportTicketConversationTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_list_open_tickets_use_case(
    session_factory: sessionmaker[Session],
) -> ListOpenSupportTicketsTransactionalUseCase:
    """Собирает транзакционный use-case списка открытых тикетов."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return ListOpenSupportTicketsTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_set_ticket_status_use_case(
    session_factory: sessionmaker[Session],
) -> SetSupportTicketStatusTransactionalUseCase:
    """Собирает транзакционный use-case изменения статуса тикета модератором."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return SetSupportTicketStatusTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_list_person_tickets_use_case(
    session_factory: sessionmaker[Session],
) -> ListPersonSupportTicketsTransactionalUseCase:
    """Собирает транзакционный use-case списка тикетов пользователя."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return ListPersonSupportTicketsTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_get_person_tickets_page_use_case(
    session_factory: sessionmaker[Session],
) -> GetPersonTicketsPageTransactionalUseCase:
    """Собирает транзакционный use-case страницы тикетов пользователя с пагинацией."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return GetPersonTicketsPageTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_pull_pending_messages_use_case(
    session_factory: sessionmaker[Session],
) -> PullPendingModeratorMessagesTransactionalUseCase:
    """Собирает use-case выборки pending-сообщений модератора по целевой платформе."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return PullPendingModeratorMessagesTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_update_delivery_status_use_case(
    session_factory: sessionmaker[Session],
) -> UpdateModeratorMessageDeliveryStatusTransactionalUseCase:
    """Собирает use-case фиксации статуса доставки модераторского сообщения."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return UpdateModeratorMessageDeliveryStatusTransactionalUseCase(unit_of_work_factory=uow_factory)


def build_iiko_gateway(settings: AppSettings) -> IikoLoyaltyGateway | None:
    """Собирает iiko-шлюз для разделов лояльности или возвращает `None`, если интеграция выключена."""

    if not settings.is_iiko_configured:
        logger.bind(platform="max", component="app", stage="startup").warning(
            "Интеграция iiko отключена: не заданы IIKO_API_KEY/IIKO_ORG_ID."
        )
        return None

    return IikoLoyaltyGateway(
        api_key=settings.iiko_api_key,
        organization_id=settings.iiko_org_id,
        base_url=settings.iiko_base_url,
    )


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
    ticket_conversation_use_case = build_ticket_conversation_use_case(session_factory)
    list_open_tickets_use_case = build_list_open_tickets_use_case(session_factory)
    set_ticket_status_use_case = build_set_ticket_status_use_case(session_factory)
    list_person_tickets_use_case = build_list_person_tickets_use_case(session_factory)
    get_person_tickets_page_use_case = build_get_person_tickets_page_use_case(session_factory)
    pull_pending_use_case = build_pull_pending_messages_use_case(session_factory)
    update_delivery_status_use_case = build_update_delivery_status_use_case(session_factory)
    iiko_gateway = build_iiko_gateway(settings)
    balance_use_case = GetLoyaltyBalanceUseCase(iiko_gateway) if iiko_gateway is not None else None
    virtual_card_use_case = GetVirtualCardUseCase(iiko_gateway) if iiko_gateway is not None else None
    adapter = MaxIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        moderator_reply_use_case=moderator_reply_use_case,
        ticket_details_use_case=ticket_details_use_case,
        ticket_conversation_use_case=ticket_conversation_use_case,
        list_open_tickets_use_case=list_open_tickets_use_case,
        set_ticket_status_use_case=set_ticket_status_use_case,
        list_person_tickets_use_case=list_person_tickets_use_case,
        get_person_tickets_page_use_case=get_person_tickets_page_use_case,
        balance_use_case=balance_use_case,
        virtual_card_use_case=virtual_card_use_case,
        loyalty_gateway=iiko_gateway,
    )
    delivery_processor = PendingModeratorDeliveryProcessor(
        target_platform="max",
        pull_pending_use_case=pull_pending_use_case,
        update_status_use_case=update_delivery_status_use_case,
    )

    dispatcher = Dispatcher()
    router = Router()
    register_max_guest_handlers(router, adapter, delivery_processor=delivery_processor)
    dispatcher.include_routers(router)
    return dispatcher


async def run_max_bot(settings: AppSettings | None = None) -> None:
    """Запускает MAX-бота в polling-режиме."""

    app_settings = settings or AppSettings()
    configure_logging(service_name="max-bot", log_level=app_settings.log_level)
    app_logger = logger.bind(platform="max", component="app", stage="startup")
    app_logger.info("Инициализация MAX-бота. ENV={env}.", env=app_settings.env)
    app_settings.validate_max_ready()

    Bot, _, _ = _import_maxapi_runtime()
    bot = Bot(token=app_settings.max_bot_token)
    dispatcher = build_dispatcher(app_settings)
    app_logger.info("Запуск polling MAX-бота.")
    try:
        await dispatcher.start_polling(bot)
    except Exception:  # noqa: BLE001
        app_logger.exception("MAX-бот завершился с необработанной ошибкой.")
        raise


def main() -> None:
    """Синхронная точка входа запуска MAX-бота."""

    asyncio.run(run_max_bot())


if __name__ == "__main__":
    main()
