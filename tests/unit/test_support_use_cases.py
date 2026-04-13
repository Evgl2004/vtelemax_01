"""Тесты use-case сценариев поддержки и модерации."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import TracebackType
from uuid import uuid4

import pytest

from vtelemax.core import (
    CreateSupportTicketCommand,
    CreateSupportTicketTransactionalUseCase,
    GetSupportTicketConversationTransactionalUseCase,
    GetSupportTicketDetailsTransactionalUseCase,
    IdentityRepository,
    IdentityUnitOfWork,
    InMemoryIdentityRepository,
    InMemorySupportRepository,
    ListOpenSupportTicketsTransactionalUseCase,
    ListPersonSupportTicketsTransactionalUseCase,
    ModeratorReplyCommand,
    PersonProfilePatch,
    PullPendingModeratorMessagesTransactionalUseCase,
    RouteModeratorReplyTransactionalUseCase,
    SetSupportTicketStatusCommand,
    SetSupportTicketStatusTransactionalUseCase,
    SupportDeliveryStatus,
    SupportMessage,
    SupportMessageAuthor,
    SupportTicket,
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


def test_support_use_case_rejects_too_short_question() -> None:
    """Проверяет, что обращение короче минимальной длины отклоняется."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

    register_use_case = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=uow_factory)
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="1001",
            raw_phone="+79123456789",
        )
    )
    create_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)

    with pytest.raises(ValueError, match="10"):
        create_use_case.execute(
            CreateSupportTicketCommand(
                platform="telegram",
                external_id="1001",
                question_text="коротко",
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


def test_route_moderator_reply_closes_stale_system_pending_notifications() -> None:
    """Проверяет, что после ответа модератора старые system-pending уведомления по тикету закрываются."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

    register_use_case = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=uow_factory)
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="tg-guest-3001",
            raw_phone="+79129993001",
        )
    )
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="vk-mod-3001",
            raw_phone="+79129994001",
        )
    )
    vk_moderator = identity_repository.get_person_by_account("vk", "vk-mod-3001")
    assert vk_moderator is not None
    identity_repository.update_person_profile(
        vk_moderator.person_id,
        PersonProfilePatch(is_moderator=True),
    )

    create_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)
    created = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="telegram",
            external_id="tg-guest-3001",
            question_text="Нужна помощь по заказу, проверьте статус, пожалуйста.",
        )
    )

    pull_pending_use_case = PullPendingModeratorMessagesTransactionalUseCase(unit_of_work_factory=uow_factory)
    vk_pending_before = pull_pending_use_case.execute(target_platform="vk", limit=10)
    assert len(vk_pending_before) == 1
    assert vk_pending_before[0].author == SupportMessageAuthor.SYSTEM
    system_messages_before = [
        message
        for message in support_repository.list_messages(created.ticket_id)
        if message.author == SupportMessageAuthor.SYSTEM
    ]
    assert system_messages_before
    assert all(message.delivery_status == SupportDeliveryStatus.CREATED for message in system_messages_before)

    route_use_case = RouteModeratorReplyTransactionalUseCase(unit_of_work_factory=uow_factory)
    route_use_case.execute(
        ModeratorReplyCommand(
            ticket_id=created.ticket_id,
            moderator_platform="vk",
            reply_text="Приняли обращение, уже работаем по вашему вопросу.",
        )
    )

    vk_pending_after = pull_pending_use_case.execute(target_platform="vk", limit=10)
    assert len(vk_pending_after) == 0

    system_messages = [
        message
        for message in support_repository.list_messages(created.ticket_id)
        if message.author == SupportMessageAuthor.SYSTEM
    ]
    assert system_messages
    assert all(message.delivery_status == SupportDeliveryStatus.SENT for message in system_messages)


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


def test_get_support_ticket_conversation_returns_messages_in_order() -> None:
    """Проверяет, что карточка тикета возвращает историю сообщений в порядке создания."""

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
    create_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)
    created = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="telegram",
            external_id="tg-1001",
            question_text="Нужна помощь с начислением бонусов",
        )
    )
    route_use_case = RouteModeratorReplyTransactionalUseCase(unit_of_work_factory=uow_factory)
    route_use_case.execute(
        ModeratorReplyCommand(
            ticket_id=created.ticket_id,
            moderator_platform="vk",
            reply_text="Проверили, начисление будет выполнено сегодня.",
        )
    )

    conversation_use_case = GetSupportTicketConversationTransactionalUseCase(unit_of_work_factory=uow_factory)
    conversation = conversation_use_case.execute(created.ticket_id)

    assert conversation.ticket_id == created.ticket_id
    assert conversation.status == SupportTicketStatus.IN_PROGRESS
    assert len(conversation.messages) == 2
    assert conversation.messages[0].author.value == "guest"
    assert "Нужна помощь" in conversation.messages[0].body
    assert conversation.messages[1].author.value == "moderator"
    assert "начисление будет выполнено" in conversation.messages[1].body


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


def test_route_moderator_reply_moves_ticket_to_in_progress() -> None:
    """Проверяет, что первый ответ модератора переводит тикет в статус in_progress."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

    register_use_case = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=uow_factory)
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="vk-7001",
            raw_phone="+79123450001",
        )
    )
    create_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)
    created = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="vk",
            external_id="vk-7001",
            question_text="Нужна помощь по начислению бонусов.",
        )
    )

    route_use_case = RouteModeratorReplyTransactionalUseCase(unit_of_work_factory=uow_factory)
    route_use_case.execute(
        ModeratorReplyCommand(
            ticket_id=created.ticket_id,
            moderator_platform="vk",
            reply_text="Приняли обращение в работу.",
        )
    )

    ticket = support_repository.get_ticket(created.ticket_id)
    assert ticket is not None
    assert ticket.status == SupportTicketStatus.IN_PROGRESS


def test_list_open_tickets_can_filter_multiple_statuses() -> None:
    """Проверяет фильтрацию тикетов модерации по нескольким статусам."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

    register_use_case = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=uow_factory)
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="tg-7002",
            raw_phone="+79123450002",
        )
    )

    create_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)
    first = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="telegram",
            external_id="tg-7002",
            question_text="Первый тестовый вопрос пользователя.",
        )
    )
    second = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="telegram",
            external_id="tg-7002",
            question_text="Второй тестовый вопрос пользователя.",
        )
    )
    third = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="telegram",
            external_id="tg-7002",
            question_text="Третий тестовый вопрос пользователя.",
        )
    )

    support_repository.update_ticket_status(first.ticket_id, SupportTicketStatus.CLOSED)
    support_repository.update_ticket_status(second.ticket_id, SupportTicketStatus.IN_PROGRESS)
    support_repository.update_ticket_status(third.ticket_id, SupportTicketStatus.OPEN)

    list_use_case = ListOpenSupportTicketsTransactionalUseCase(unit_of_work_factory=uow_factory)
    result = list_use_case.execute(
        limit=10,
        statuses=(SupportTicketStatus.OPEN, SupportTicketStatus.IN_PROGRESS),
    )

    assert {item.ticket_id for item in result} == {second.ticket_id, third.ticket_id}
    assert all(item.status in {SupportTicketStatus.OPEN, SupportTicketStatus.IN_PROGRESS} for item in result)


def test_create_support_ticket_enqueues_system_notifications_for_moderators() -> None:
    """Проверяет, что при новом обращении создаются pending-уведомления для модераторов."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

    register_use_case = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=uow_factory)
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="tg-guest-1001",
            raw_phone="+79129990001",
        )
    )
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="vk-mod-7001",
            raw_phone="+79129997701",
        )
    )
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="max",
            external_id="max-mod-7002",
            raw_phone="+79129997702",
        )
    )

    vk_moderator = identity_repository.get_person_by_account("vk", "vk-mod-7001")
    assert vk_moderator is not None
    identity_repository.update_person_profile(
        vk_moderator.person_id,
        PersonProfilePatch(is_moderator=True),
    )
    max_moderator = identity_repository.get_person_by_account("max", "max-mod-7002")
    assert max_moderator is not None
    identity_repository.update_person_profile(
        max_moderator.person_id,
        PersonProfilePatch(is_moderator=True),
    )

    create_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)
    created = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="telegram",
            external_id="tg-guest-1001",
            question_text="Проверьте, пожалуйста, начисление бонусов по последнему чеку.",
        )
    )

    pull_use_case = PullPendingModeratorMessagesTransactionalUseCase(unit_of_work_factory=uow_factory)
    vk_pending = pull_use_case.execute(target_platform="vk", limit=10)
    max_pending = pull_use_case.execute(target_platform="max", limit=10)
    tg_pending = pull_use_case.execute(target_platform="telegram", limit=10)
    assert len(vk_pending) == 1
    assert len(max_pending) == 1
    assert len(tg_pending) == 0
    assert vk_pending[0].author == SupportMessageAuthor.SYSTEM
    assert max_pending[0].author == SupportMessageAuthor.SYSTEM
    assert "Новое обращение" in vk_pending[0].body
    assert "Гость:" in max_pending[0].body
    assert "Тикет: #" in max_pending[0].body
    assert str(created.ticket_id) not in max_pending[0].body
    assert "Нажмите «✍️ Ответить»" in max_pending[0].body

    conversation_use_case = GetSupportTicketConversationTransactionalUseCase(unit_of_work_factory=uow_factory)
    conversation = conversation_use_case.execute(created.ticket_id)
    assert len(conversation.messages) == 1
    assert conversation.messages[0].author == SupportMessageAuthor.GUEST


def test_support_repository_add_message_is_idempotent_by_message_id() -> None:
    """Проверяет защиту от дублей: повтор с тем же message_id не создает вторую запись."""

    support_repository = InMemorySupportRepository()
    ticket_id = uuid4()
    support_repository.create_ticket(
        SupportTicket(
            ticket_id=ticket_id,
            person_id=uuid4(),
            source_platform="telegram",
            status=SupportTicketStatus.OPEN,
            last_guest_platform="telegram",
        )
    )

    duplicate_message_id = uuid4()
    message = SupportMessage(
        message_id=duplicate_message_id,
        ticket_id=ticket_id,
        author=SupportMessageAuthor.SYSTEM,
        body="Тестовое уведомление",
        source_platform="telegram",
        target_platform="vk",
        target_external_id="vk-mod-1",
        delivery_status=SupportDeliveryStatus.CREATED,
    )
    support_repository.add_message(message)
    support_repository.add_message(message)

    messages = support_repository.list_messages(ticket_id)
    assert len(messages) == 1
    assert messages[0].message_id == duplicate_message_id


def test_set_support_ticket_status_updates_open_to_closed() -> None:
    """Проверяет успешную смену статуса тикета из open в closed."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

    register_use_case = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=uow_factory)
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="vk-9001",
            raw_phone="+79123450901",
        )
    )
    create_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)
    created = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="vk",
            external_id="vk-9001",
            question_text="Нужно закрыть обращение после проверки.",
        )
    )

    set_status_use_case = SetSupportTicketStatusTransactionalUseCase(unit_of_work_factory=uow_factory)
    result = set_status_use_case.execute(
        SetSupportTicketStatusCommand(
            ticket_id=created.ticket_id,
            status=SupportTicketStatus.CLOSED,
        )
    )

    assert result.previous_status == SupportTicketStatus.OPEN
    assert result.new_status == SupportTicketStatus.CLOSED
    stored_ticket = support_repository.get_ticket(created.ticket_id)
    assert stored_ticket is not None
    assert stored_ticket.status == SupportTicketStatus.CLOSED


def test_set_support_ticket_status_allows_reopen_closed_ticket() -> None:
    """Проверяет, что закрытый тикет можно переоткрыть через статус OPEN."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

    register_use_case = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=uow_factory)
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="tg-9002",
            raw_phone="+79123450902",
        )
    )
    create_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)
    created = create_use_case.execute(
        CreateSupportTicketCommand(
            platform="telegram",
            external_id="tg-9002",
            question_text="Тестовая заявка для проверки смены статусов.",
        )
    )
    support_repository.update_ticket_status(created.ticket_id, SupportTicketStatus.CLOSED)

    set_status_use_case = SetSupportTicketStatusTransactionalUseCase(unit_of_work_factory=uow_factory)
    result = set_status_use_case.execute(
        SetSupportTicketStatusCommand(
            ticket_id=created.ticket_id,
            status=SupportTicketStatus.OPEN,
        )
    )
    assert result.previous_status == SupportTicketStatus.CLOSED
    assert result.new_status == SupportTicketStatus.OPEN
    stored_ticket = support_repository.get_ticket(created.ticket_id)
    assert stored_ticket is not None
    assert stored_ticket.status == SupportTicketStatus.OPEN
