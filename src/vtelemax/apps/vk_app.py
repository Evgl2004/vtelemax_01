"""Точка входа VK-бота на vkbottle."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker
from vkbottle.bot import Bot

from vtelemax.adapters.vk import VkIdentityAdapter, register_vk_guest_handlers
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


def build_bot(settings: AppSettings) -> Bot:
    """Создает и конфигурирует экземпляр VK-бота."""

    session_factory = build_postgres_session_factory(settings)
    registration_use_case = build_identity_use_case(session_factory)
    lookup_use_case = build_person_lookup_use_case(session_factory)
    adapter = VkIdentityAdapter(registration_use_case, lookup_use_case)

    bot = Bot(settings.vk_bot_token)
    register_vk_guest_handlers(bot, adapter)
    return bot


def run_vk_bot(settings: AppSettings | None = None) -> None:
    """Запускает VK-бота в режиме long-poll."""

    app_settings = settings or AppSettings()
    app_settings.validate_vk_ready()

    bot = build_bot(app_settings)
    bot.run_forever()


def main() -> None:
    """Синхронная точка входа запуска VK-бота."""

    run_vk_bot()


if __name__ == "__main__":
    main()
