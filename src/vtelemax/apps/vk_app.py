"""Точка входа VK-бота на vkbottle."""

from __future__ import annotations

from collections.abc import Callable

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker
from vkbottle.bot import Bot

from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor
from vtelemax.adapters.vk import VkIdentityAdapter, register_vk_guest_handlers
from vtelemax.core import (
    CreateSupportTicketTransactionalUseCase,
    GetPersonByAccountTransactionalUseCase,
    ListOpenSupportTicketsTransactionalUseCase,
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
from vtelemax.infrastructure import configure_logging
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


def build_list_open_tickets_use_case(
    session_factory: sessionmaker[Session],
) -> ListOpenSupportTicketsTransactionalUseCase:
    """Собирает транзакционный use-case списка открытых тикетов."""

    uow_factory: Callable[[], SQLAlchemyIdentityUnitOfWork] = lambda: SQLAlchemyIdentityUnitOfWork(
        session_factory
    )
    return ListOpenSupportTicketsTransactionalUseCase(unit_of_work_factory=uow_factory)


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


def build_bot(settings: AppSettings) -> Bot:
    """Создает и конфигурирует экземпляр VK-бота."""

    session_factory = build_postgres_session_factory(settings)
    registration_use_case = build_identity_use_case(session_factory)
    lookup_use_case = build_person_lookup_use_case(session_factory)
    create_ticket_use_case = build_create_support_ticket_use_case(session_factory)
    moderator_reply_use_case = build_moderator_reply_use_case(session_factory)
    ticket_details_use_case = build_ticket_details_use_case(session_factory)
    list_open_tickets_use_case = build_list_open_tickets_use_case(session_factory)
    pull_pending_use_case = build_pull_pending_messages_use_case(session_factory)
    update_delivery_status_use_case = build_update_delivery_status_use_case(session_factory)
    adapter = VkIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        moderator_reply_use_case=moderator_reply_use_case,
        ticket_details_use_case=ticket_details_use_case,
        list_open_tickets_use_case=list_open_tickets_use_case,
    )
    delivery_processor = PendingModeratorDeliveryProcessor(
        target_platform="vk",
        pull_pending_use_case=pull_pending_use_case,
        update_status_use_case=update_delivery_status_use_case,
    )

    bot = Bot(settings.vk_bot_token)
    register_vk_guest_handlers(bot, adapter, delivery_processor=delivery_processor)
    return bot


def run_vk_bot(settings: AppSettings | None = None) -> None:
    """Запускает VK-бота в режиме long-poll."""

    app_settings = settings or AppSettings()
    configure_logging(service_name="vk-bot", log_level=app_settings.log_level)
    app_logger = logger.bind(platform="vk", component="app", stage="startup")
    app_logger.info("Инициализация VK-бота. ENV={env}.", env=app_settings.env)
    app_settings.validate_vk_ready()

    bot = build_bot(app_settings)
    app_logger.info("Запуск long-poll VK-бота.")
    try:
        bot.run_forever()
    except Exception:  # noqa: BLE001
        app_logger.exception("VK-бот завершился с необработанной ошибкой.")
        raise


def main() -> None:
    """Синхронная точка входа запуска VK-бота."""

    run_vk_bot()


if __name__ == "__main__":
    main()
