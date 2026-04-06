"""Точка входа Telegram-бота на aiogram."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger
from sqlalchemy.orm import Session, sessionmaker

from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor
from vtelemax.adapters.telegram import TelegramIdentityAdapter, build_telegram_identity_router
from vtelemax.core import (
    CreateSupportTicketTransactionalUseCase,
    GetPersonByAccountTransactionalUseCase,
    GetLoyaltyBalanceUseCase,
    GetVirtualCardUseCase,
    GetPersonTicketsPageTransactionalUseCase,
    ListOpenSupportTicketsTransactionalUseCase,
    ListPersonSupportTicketsTransactionalUseCase,
    GetSupportTicketConversationTransactionalUseCase,
    GetSupportTicketDetailsTransactionalUseCase,
    PullPendingModeratorMessagesTransactionalUseCase,
    RegisterOrAttachAccountTransactionalUseCase,
    RouteModeratorReplyTransactionalUseCase,
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
        logger.bind(platform="telegram", component="app", stage="startup").warning(
            "Интеграция iiko отключена: не заданы IIKO_API_KEY/IIKO_ORG_ID."
        )
        return None

    return IikoLoyaltyGateway(
        api_key=settings.iiko_api_key,
        organization_id=settings.iiko_org_id,
        base_url=settings.iiko_base_url,
    )


def build_dispatcher(settings: AppSettings) -> Dispatcher:
    """Собирает Dispatcher Telegram-бота с подключенным маршрутом идентификации."""

    session_factory = build_postgres_session_factory(settings)
    registration_use_case = build_identity_use_case(session_factory)
    person_lookup_use_case = build_person_lookup_use_case(session_factory)
    create_ticket_use_case = build_create_support_ticket_use_case(session_factory)
    moderator_reply_use_case = build_moderator_reply_use_case(session_factory)
    ticket_details_use_case = build_ticket_details_use_case(session_factory)
    ticket_conversation_use_case = build_ticket_conversation_use_case(session_factory)
    list_open_tickets_use_case = build_list_open_tickets_use_case(session_factory)
    list_person_tickets_use_case = build_list_person_tickets_use_case(session_factory)
    get_person_tickets_page_use_case = build_get_person_tickets_page_use_case(session_factory)
    pull_pending_use_case = build_pull_pending_messages_use_case(session_factory)
    update_delivery_status_use_case = build_update_delivery_status_use_case(session_factory)
    iiko_gateway = build_iiko_gateway(settings)
    balance_use_case = GetLoyaltyBalanceUseCase(iiko_gateway) if iiko_gateway is not None else None
    virtual_card_use_case = GetVirtualCardUseCase(iiko_gateway) if iiko_gateway is not None else None
    identity_adapter = TelegramIdentityAdapter(
        registration_use_case,
        person_lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        moderator_reply_use_case=moderator_reply_use_case,
        ticket_details_use_case=ticket_details_use_case,
        ticket_conversation_use_case=ticket_conversation_use_case,
        list_open_tickets_use_case=list_open_tickets_use_case,
        list_person_tickets_use_case=list_person_tickets_use_case,
        get_person_tickets_page_use_case=get_person_tickets_page_use_case,
        balance_use_case=balance_use_case,
        virtual_card_use_case=virtual_card_use_case,
        loyalty_gateway=iiko_gateway,
    )
    delivery_processor = PendingModeratorDeliveryProcessor(
        target_platform="telegram",
        pull_pending_use_case=pull_pending_use_case,
        update_status_use_case=update_delivery_status_use_case,
    )

    dispatcher = Dispatcher()
    dispatcher.include_router(
        build_telegram_identity_router(
            identity_adapter,
            delivery_processor=delivery_processor,
        )
    )
    return dispatcher


async def run_telegram_bot(settings: AppSettings | None = None) -> None:
    """Запускает Telegram-бота в polling-режиме."""

    app_settings = settings or AppSettings()
    configure_logging(service_name="telegram-bot", log_level=app_settings.log_level)
    app_logger = logger.bind(platform="telegram", component="app", stage="startup")
    app_logger.info("Инициализация Telegram-бота. ENV={env}.", env=app_settings.env)
    app_settings.validate_telegram_ready()

    bot = Bot(
        token=app_settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher(app_settings)
    app_logger.info("Запуск polling Telegram-бота.")
    try:
        await dispatcher.start_polling(bot)
    except Exception:  # noqa: BLE001
        app_logger.exception("Telegram-бот завершился с необработанной ошибкой.")
        raise


def main() -> None:
    """Синхронная точка входа для запуска из командной строки."""

    asyncio.run(run_telegram_bot())


if __name__ == "__main__":
    main()
