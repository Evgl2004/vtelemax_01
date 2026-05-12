"""Unit-тесты одноразовой доставки pending-сообщений модератора."""

from __future__ import annotations

import asyncio
from types import TracebackType
from uuid import UUID

from vtelemax.adapters.moderation_delivery import PendingModeratorDeliveryProcessor
from vtelemax.core import (
    CreateSupportTicketCommand,
    CreateSupportTicketTransactionalUseCase,
    IdentityRepository,
    IdentityUnitOfWork,
    InMemoryIdentityRepository,
    InMemorySupportRepository,
    ModeratorReplyCommand,
    PullPendingModeratorMessagesTransactionalUseCase,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
    RouteModeratorReplyTransactionalUseCase,
    PendingModeratorDelivery,
    PersonProfilePatch,
    SupportDeliveryStatus,
    SupportMessageAuthor,
    UpdateModeratorMessageDeliveryStatusTransactionalUseCase,
)


class InMemorySupportUnitOfWork(IdentityUnitOfWork):
    """Тестовый UnitOfWork поверх in-memory identity + support репозиториев."""

    def __init__(self, identity_repository: IdentityRepository, support_repository: InMemorySupportRepository) -> None:
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


def _build_pending_delivery_processor(
    *,
    target_external_id: str,
) -> tuple[PendingModeratorDeliveryProcessor, InMemorySupportRepository, UUID]:
    """Создает контекст с одним pending-сообщением модератора в канал VK."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

    register_use_case = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=uow_factory)
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="tg-2002",
            raw_phone="+79123456789",
        )
    )
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id=target_external_id,
            raw_phone="+79123456789",
        )
    )

    create_ticket_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)
    created_ticket = create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="telegram",
            external_id="tg-2002",
            question_text="Нужна помощь",
        )
    )

    route_reply_use_case = RouteModeratorReplyTransactionalUseCase(unit_of_work_factory=uow_factory, vk_pending_verification_delivery_enabled=True)
    route_reply_use_case.execute(
        ModeratorReplyCommand(
            ticket_id=created_ticket.ticket_id,
            moderator_platform="telegram",
            reply_text="Ответ модератора",
            preferred_target_platform="vk",
        )
    )

    pull_pending_use_case = PullPendingModeratorMessagesTransactionalUseCase(unit_of_work_factory=uow_factory)
    update_status_use_case = UpdateModeratorMessageDeliveryStatusTransactionalUseCase(
        unit_of_work_factory=uow_factory
    )
    processor = PendingModeratorDeliveryProcessor(
        target_platform="vk",
        pull_pending_use_case=pull_pending_use_case,
        update_status_use_case=update_status_use_case,
    )
    return processor, support_repository, created_ticket.ticket_id


def _get_last_moderator_message_status(
    support_repository: InMemorySupportRepository,
    *,
    ticket_id: UUID,
) -> tuple[SupportDeliveryStatus | None, str | None]:
    """Возвращает delivery-статус и ошибку последнего сообщения модератора в тикете."""

    messages = support_repository.list_messages(ticket_id)
    moderator_messages = [message for message in messages if message.author == SupportMessageAuthor.MODERATOR]
    assert moderator_messages, "Ожидалось хотя бы одно сообщение модератора."
    last_message = moderator_messages[-1]
    return last_message.delivery_status, last_message.delivery_error


def test_delivery_processor_marks_message_as_sent_on_success() -> None:
    """Проверяет успешную доставку pending-сообщения в один проход."""

    processor, support_repository, ticket_id = _build_pending_delivery_processor(target_external_id="1001")
    sent_payloads: list[tuple[PendingModeratorDelivery, str]] = []

    async def sender(delivery: PendingModeratorDelivery, text: str) -> None:
        sent_payloads.append((delivery, text))

    sent_count, failed_count = asyncio.run(processor.process_once(sender=sender, limit=10))

    assert sent_count == 1
    assert failed_count == 0
    assert len(sent_payloads) == 1
    assert sent_payloads[0][0].target_external_id == "1001"
    assert sent_payloads[0][1] == "📬 Ответ модератора:\nОтвет модератора"
    status, error_text = _get_last_moderator_message_status(support_repository, ticket_id=ticket_id)
    assert status == SupportDeliveryStatus.SENT
    assert error_text is None


def test_delivery_processor_marks_message_as_failed_without_retry() -> None:
    """Проверяет dirty-сценарий: невалидный external_id помечается как failed без повторной попытки."""

    processor, support_repository, ticket_id = _build_pending_delivery_processor(
        target_external_id="vk-user-not-int"
    )

    async def sender(delivery: PendingModeratorDelivery, text: str) -> None:  # noqa: ARG001
        int(delivery.target_external_id)

    first_sent, first_failed = asyncio.run(processor.process_once(sender=sender, limit=10))
    second_sent, second_failed = asyncio.run(processor.process_once(sender=sender, limit=10))

    assert first_sent == 0
    assert first_failed == 1
    assert second_sent == 0
    assert second_failed == 0

    status, error_text = _get_last_moderator_message_status(support_repository, ticket_id=ticket_id)
    assert status == SupportDeliveryStatus.FAILED
    assert error_text is not None


def test_delivery_processor_sends_system_notification_without_moderator_prefix() -> None:
    """Проверяет, что системное уведомление модератору доставляется как есть (без префикса ответа)."""

    identity_repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    uow_factory = lambda: InMemorySupportUnitOfWork(identity_repository, support_repository)

    register_use_case = RegisterOrAttachAccountTransactionalUseCase(unit_of_work_factory=uow_factory)
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="tg-guest-1001",
            raw_phone="+79128880001",
        )
    )
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="vk-mod-9001",
            raw_phone="+79128889991",
        )
    )
    moderator_person = identity_repository.get_person_by_account("vk", "vk-mod-9001")
    assert moderator_person is not None
    identity_repository.update_person_profile(
        moderator_person.person_id,
        PersonProfilePatch(is_moderator=True),
    )

    create_ticket_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=uow_factory)
    create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="telegram",
            external_id="tg-guest-1001",
            question_text="Подскажите, пожалуйста, почему не начислились бонусы за заказ.",
        )
    )

    pull_pending_use_case = PullPendingModeratorMessagesTransactionalUseCase(unit_of_work_factory=uow_factory)
    update_status_use_case = UpdateModeratorMessageDeliveryStatusTransactionalUseCase(
        unit_of_work_factory=uow_factory
    )
    processor = PendingModeratorDeliveryProcessor(
        target_platform="vk",
        pull_pending_use_case=pull_pending_use_case,
        update_status_use_case=update_status_use_case,
    )

    sent_payloads: list[tuple[PendingModeratorDelivery, str]] = []

    async def sender(delivery: PendingModeratorDelivery, text: str) -> None:
        sent_payloads.append((delivery, text))

    sent_count, failed_count = asyncio.run(processor.process_once(sender=sender, limit=10))

    assert sent_count == 1
    assert failed_count == 0
    assert sent_payloads[0][0].target_external_id == "vk-mod-9001"
    assert "🔔 Новое обращение от гостя" in sent_payloads[0][1]
    assert "Тикет: #" in sent_payloads[0][1]
    assert "Гость:" in sent_payloads[0][1]
    assert "Нажмите «✍️ Ответить»" in sent_payloads[0][1]
    assert "откройте меню модератора командой /mod." in sent_payloads[0][1]
    assert "Ответ модератора" not in sent_payloads[0][1]

