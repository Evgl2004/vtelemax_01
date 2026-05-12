"""Интеграционные тесты репозитория поддержки на SQLAlchemy UoW."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from vtelemax.core import (
    CreateSupportTicketCommand,
    CreateSupportTicketTransactionalUseCase,
    GetSupportTicketDetailsTransactionalUseCase,
    ModeratorReplyCommand,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
    RouteModeratorReplyTransactionalUseCase,
    SupportTicketStatus,
)
from vtelemax.infrastructure.postgres import Base, SQLAlchemyIdentityUnitOfWork, build_session_factory


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """Создает фабрику сессий поверх in-memory SQLite для integration-тестов."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _: object) -> None:
        """Включает проверку внешних ключей в SQLite для реалистичного integration-контура."""

        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_support_ticket_and_cross_platform_route_are_persisted(
    session_factory: sessionmaker[Session],
) -> None:
    """Проверяет создание тикета и маршрутизацию модераторского ответа через БД."""

    uow_factory = lambda: SQLAlchemyIdentityUnitOfWork(session_factory)
    register_use_case = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=uow_factory)
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="tg-1001",
            raw_phone="+79123456789",
        )
    )
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="vk-2002",
            raw_phone="+79123456789",
        )
    )

    create_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)
    created = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="vk",
            external_id="vk-2002",
            question_text="Нужна консультация по бонусам.",
        )
    )

    route_use_case = RouteModeratorReplyTransactionalUseCase(unit_of_work_factory=uow_factory, vk_pending_verification_delivery_enabled=True)
    route = route_use_case.execute(
        ModeratorReplyCommand(
            ticket_id=created.ticket_id,
            moderator_platform="telegram",
            reply_text="Отправили вам подробности в Telegram.",
            preferred_target_platform="telegram",
        )
    )

    assert route.target_platform == "telegram"
    assert route.target_external_id == "tg-1001"

    details_use_case = GetSupportTicketDetailsTransactionalUseCase(unit_of_work_factory=uow_factory)
    details = details_use_case.execute(created.ticket_id)
    assert details.linked_platforms == ("telegram", "vk")
    assert details.status == SupportTicketStatus.IN_PROGRESS


def test_support_ticket_creation_requires_registered_account(
    session_factory: sessionmaker[Session],
) -> None:
    """Проверяет запрет создания тикета для неидентифицированного аккаунта."""

    create_use_case = CreateSupportTicketTransactionalUseCase(
        unit_of_work_factory=lambda: SQLAlchemyIdentityUnitOfWork(session_factory)
    )

    with pytest.raises(ValueError):
        create_use_case.execute(
            CreateSupportTicketCommand(
                platform="vk",
                external_id="not-registered",
                question_text="Помогите",
            )
        )

