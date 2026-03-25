"""Тесты use-case сценариев поддержки и модерации."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import TracebackType
from uuid import uuid4

import pytest

from vtelemax.core import (
    CreateSupportTicketCommand,
    CreateSupportTicketTransactionalUseCase,
    GetSupportTicketDetailsTransactionalUseCase,
    IdentityRepository,
    IdentityUnitOfWork,
    InMemoryIdentityRepository,
    InMemorySupportRepository,
    ListOpenSupportTicketsTransactionalUseCase,
    ListPersonSupportTicketsTransactionalUseCase,
    ModeratorReplyCommand,
    PullPendingModeratorMessagesTransactionalUseCase,
    RouteModeratorReplyTransactionalUseCase,
    SupportDeliveryStatus,
    SupportTicketStatus,
    SupportRepository,
    SupportUnitOfWork,
    UpdateModeratorMessageDeliveryStatusCommand,
    UpdateModeratorMessageDeliveryStatusTransactionalUseCase,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
)


class InMemorySupportUnitOfWork(IdentityUnitOfWork, SupportUnitOfWork):
    """Тестовый UoW с in-memory identity + support репозиториями."""

    def __init__(self, identity_repository: IdentityRepository, support_repository: SupportRepository) -> None:
        self.identity_repository = identity_repository
        self.support_repository = support_repository

    def __enter__(self) -> "InMemorySupportUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return

    def commit(self) -> None:
        return

    def rollback(self) -> None:
        return


def test_support_use_case_creates_ticket_for_registered_user() -> None:
    """Проверяет создание тикета из обращения гостя."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

    register_use_case = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=uow_factory)
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="1001",
            raw_phone="+79123456789",
        )
    )
    create_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)

    result = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="vk",
            external_id="1001",
            question_text="Когда начисляются бонусы?",
        )
    )

    ticket = support_repository.get_ticket(result.ticket_id)
    messages = support_repository.list_messages(result.ticket_id)

    assert ticket is not None
    assert ticket.source_platform == "vk"
    assert ticket.last_guest_platform == "vk"
    assert len(messages) == 1
    assert messages[0].body == "Когда начисляются бонусы?"


def test_support_use_case_rejects_unregistered_account() -> None:
    """Проверяет грязный сценарий: тикет без регистрации запрещен."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)
    create_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)

    with pytest.raises(ValueError):
        create_use_case.execute(
            CreateSupportTicketCommand(
                platform="vk",
                external_id="missing-user",
                question_text="Помогите",
            )
        )


def test_route_moderator_reply_prefers_last_guest_platform() -> None:
    """Проверяет автоматический выбор канала доставки по последней активности гостя."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

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
            question_text="Подскажите, где посмотреть баланс?",
        )
    )

    route_use_case = RouteModeratorReplyTransactionalUseCase(unit_of_work_factory=uow_factory)
    routing = route_use_case.execute(
        ModeratorReplyCommand(
            ticket_id=created.ticket_id,
            moderator_platform="telegram",
            reply_text="Проверяем, сейчас вернемся с ответом.",
        )
    )

    assert routing.target_platform == "vk"
    assert routing.target_external_id == "vk-2002"

    moderation_messages = support_repository.pull_pending_moderator_messages("vk")
    assert len(moderation_messages) == 1
    assert moderation_messages[0].delivery_status == SupportDeliveryStatus.CREATED


def test_route_moderator_reply_allows_cross_platform_override() -> None:
    """Проверяет ручной override канала доставки модераторского ответа."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

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
            question_text="Подскажите, где посмотреть баланс?",
        )
    )

    route_use_case = RouteModeratorReplyTransactionalUseCase(unit_of_work_factory=uow_factory)
    routing = route_use_case.execute(
        ModeratorReplyCommand(
            ticket_id=created.ticket_id,
            moderator_platform="vk",
            reply_text="Ответим в Telegram по вашему запросу.",
            preferred_target_platform="telegram",
        )
    )

    assert routing.target_platform == "telegram"
    assert routing.target_external_id == "tg-1001"


def test_get_support_ticket_details_returns_linked_platforms() -> None:
    """Проверяет карточку тикета с перечнем подключенных мессенджеров."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

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
            platform="max",
            external_id="max-3003",
            raw_phone="+79123456789",
        )
    )
    create_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)
    created = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="max",
            external_id="max-3003",
            question_text="Нужна помощь с картой",
        )
    )

    details_use_case = GetSupportTicketDetailsTransactionalUseCase(unit_of_work_factory=uow_factory)
    details = details_use_case.execute(created.ticket_id)

    assert details.source_platform == "max"
    assert details.last_guest_platform == "max"
    assert details.linked_platforms == ("max", "telegram")


def test_list_open_tickets_handles_dirty_limit_and_excludes_closed() -> None:
    """Проверяет список открытых тикетов: limit<=0 нормализуется и закрытые тикеты не возвращаются."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

    register_use_case = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=uow_factory)
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="vk-1001",
            raw_phone="+79123456789",
        )
    )

    create_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)
    closed_ticket = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="vk",
            external_id="vk-1001",
            question_text="Первый вопрос",
        )
    )
    open_ticket = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="vk",
            external_id="vk-1001",
            question_text="Второй вопрос",
        )
    )

    # Имитируем закрытие первого тикета, чтобы проверить фильтрацию по статусу.
    stored_closed_ticket = support_repository.get_ticket(closed_ticket.ticket_id)
    assert stored_closed_ticket is not None
    stored_closed_ticket.status = SupportTicketStatus.CLOSED

    list_use_case = ListOpenSupportTicketsTransactionalUseCase(unit_of_work_factory=uow_factory)
    result = list_use_case.execute(limit=0)

    assert len(result) == 1
    assert result[0].ticket_id == open_ticket.ticket_id
    assert result[0].status == SupportTicketStatus.OPEN


def test_list_person_tickets_returns_latest_for_person() -> None:
    """Проверяет список тикетов пользователя в порядке свежести."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

    register_use_case = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=uow_factory)
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="vk-1001",
            raw_phone="+79123456789",
        )
    )

    create_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)
    first_ticket = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="vk",
            external_id="vk-1001",
            question_text="Первый вопрос",
        )
    )
    second_ticket = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="vk",
            external_id="vk-1001",
            question_text="Второй вопрос",
        )
    )

    first_stored = support_repository.get_ticket(first_ticket.ticket_id)
    second_stored = support_repository.get_ticket(second_ticket.ticket_id)
    assert first_stored is not None
    assert second_stored is not None
    first_stored.created_at = datetime.now(tz=timezone.utc) - timedelta(minutes=5)
    second_stored.created_at = datetime.now(tz=timezone.utc)

    list_person_use_case = ListPersonSupportTicketsTransactionalUseCase(unit_of_work_factory=uow_factory)
    result = list_person_use_case.execute(platform="vk", external_id="vk-1001", limit=10)

    assert len(result) == 2
    assert result[0].ticket_id == second_ticket.ticket_id
    assert result[1].ticket_id == first_ticket.ticket_id


def test_list_person_tickets_handles_unknown_account_and_dirty_input() -> None:
    """Проверяет пустой результат для неизвестного аккаунта и валидацию грязного ввода."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)
    list_person_use_case = ListPersonSupportTicketsTransactionalUseCase(unit_of_work_factory=uow_factory)

    empty_result = list_person_use_case.execute(platform="telegram", external_id="missing", limit=5)
    assert empty_result == ()

    with pytest.raises(ValueError):
        list_person_use_case.execute(platform="telegram", external_id="   ", limit=5)


def test_pull_pending_moderator_messages_returns_target_platform_messages() -> None:
    """Проверяет выборку pending-сообщений модератора по платформе доставки."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

    register_use_case = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=uow_factory)
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="vk-1001",
            raw_phone="+79123456789",
        )
    )
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="tg-2002",
            raw_phone="+79123456789",
        )
    )

    create_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)
    created = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="vk",
            external_id="vk-1001",
            question_text="Подскажите, где посмотреть бонусы?",
        )
    )

    route_use_case = RouteModeratorReplyTransactionalUseCase(unit_of_work_factory=uow_factory)
    route_use_case.execute(
        ModeratorReplyCommand(
            ticket_id=created.ticket_id,
            moderator_platform="vk",
            reply_text="Отправляем ответ в Telegram.",
            preferred_target_platform="telegram",
        )
    )

    pull_use_case = PullPendingModeratorMessagesTransactionalUseCase(unit_of_work_factory=uow_factory)
    pending = pull_use_case.execute(target_platform="telegram", limit=10)

    assert len(pending) == 1
    assert pending[0].target_platform == "telegram"
    assert pending[0].target_external_id == "tg-2002"
    assert pending[0].body == "Отправляем ответ в Telegram."


def test_update_moderator_delivery_status_rejects_created_status() -> None:
    """Проверяет грязный сценарий: use-case обновления не принимает статус created."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)
    update_use_case = UpdateModeratorMessageDeliveryStatusTransactionalUseCase(
        unit_of_work_factory=uow_factory
    )

    with pytest.raises(ValueError):
        update_use_case.execute(
            UpdateModeratorMessageDeliveryStatusCommand(
                message_id=uuid4(),
                status=SupportDeliveryStatus.CREATED,
            )
        )
