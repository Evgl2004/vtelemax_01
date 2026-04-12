"""Use-case сценарии поддержки и кросс-мессенджер модерации."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from .models import PlatformName, SUPPORTED_PLATFORMS
from .support_models import (
    SupportDeliveryStatus,
    SupportMessage,
    SupportMessageAuthor,
    SupportTicket,
    SupportTicketStatus,
)
from .support_ports import SupportUnitOfWork

MIN_SUPPORT_QUESTION_LENGTH = 10


@dataclass(frozen=True, slots=True)
class CreateSupportTicketCommand:
    """Команда создания тикета из сообщения гостя."""

    platform: PlatformName
    external_id: str
    question_text: str


@dataclass(frozen=True, slots=True)
class CreatedSupportTicketResult:
    """Результат создания тикета поддержки."""

    ticket_id: UUID
    person_id: UUID
    source_platform: PlatformName
    message_id: UUID


class CreateSupportTicketTransactionalUseCase:
    """Создает тикет и первое сообщение гостя в рамках транзакции."""

    def __init__(self, unit_of_work_factory: Callable[[], SupportUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, command: CreateSupportTicketCommand) -> CreatedSupportTicketResult:
        """Создает тикет по гостевому сообщению."""

        if command.platform not in SUPPORTED_PLATFORMS:
            raise ValueError("Платформа не поддерживается. Допустимые значения: telegram, vk, max.")

        external_id = str(command.external_id).strip()
        if not external_id:
            raise ValueError("Внешний идентификатор аккаунта не может быть пустым.")

        question_text = str(command.question_text).strip()
        if not question_text:
            raise ValueError("Текст обращения не может быть пустым.")
        if len(question_text) < MIN_SUPPORT_QUESTION_LENGTH:
            raise ValueError(
                f"Текст обращения должен содержать минимум {MIN_SUPPORT_QUESTION_LENGTH} символов."
            )

        with self._unit_of_work_factory() as unit_of_work:
            person = unit_of_work.identity_repository.get_person_by_account(command.platform, external_id)
            if person is None:
                raise ValueError(
                    "Нельзя создать тикет: аккаунт не зарегистрирован в strict identity."
                )
            guest_display_name = self._resolve_guest_display_name(
                first_name_input=getattr(person, "first_name_input", None)
            )

            ticket_id = uuid4()
            message_id = uuid4()
            unit_of_work.support_repository.create_ticket(
                SupportTicket(
                    ticket_id=ticket_id,
                    person_id=person.person_id,
                    source_platform=command.platform,
                    status=SupportTicketStatus.OPEN,
                    last_guest_platform=command.platform,
                )
            )
            unit_of_work.support_repository.add_message(
                SupportMessage(
                    message_id=message_id,
                    ticket_id=ticket_id,
                    author=SupportMessageAuthor.GUEST,
                    body=question_text,
                    source_platform=command.platform,
                )
            )
            self._enqueue_moderator_notifications(
                unit_of_work=unit_of_work,
                source_message_id=message_id,
                ticket_id=ticket_id,
                source_platform=command.platform,
                source_external_id=external_id,
                guest_display_name=guest_display_name,
                question_text=question_text,
            )
            unit_of_work.commit()
            return CreatedSupportTicketResult(
                ticket_id=ticket_id,
                person_id=person.person_id,
                source_platform=command.platform,
                message_id=message_id,
            )

    @staticmethod
    def _build_moderator_notification_message_id(
        *,
        source_message_id: UUID,
        target_platform: PlatformName,
        target_external_id: str,
    ) -> UUID:
        """Формирует детерминированный message_id для защиты от дублей уведомлений."""

        seed = f"mod-notify:{source_message_id}:{target_platform}:{target_external_id}"
        return uuid5(NAMESPACE_URL, seed)

    @staticmethod
    def _build_moderator_notification_text(
        *,
        ticket_id: UUID,
        guest_display_name: str,
        source_platform: PlatformName,
        question_text: str,
    ) -> str:
        """Формирует текст уведомления модератору о новом обращении."""

        short_id = str(ticket_id)[-4:].upper()
        return "\n".join(
            (
                "🔔 Новое обращение от гостя",
                f"Гость: {guest_display_name}",
                f"Тикет: #{short_id}",
                f"Канал: {source_platform}",
                "",
                "Сообщение:",
                question_text,
                "",
                "Нажмите «✍️ Ответить» или откройте меню модератора командой /mod.",
            )
        )

    def _enqueue_moderator_notifications(
        self,
        *,
        unit_of_work: SupportUnitOfWork,
        source_message_id: UUID,
        ticket_id: UUID,
        source_platform: PlatformName,
        source_external_id: str,
        guest_display_name: str,
        question_text: str,
    ) -> None:
        """Ставит в outbox уведомления модераторам о новом сообщении гостя."""

        moderators = unit_of_work.identity_repository.list_moderator_accounts()
        if not moderators:
            return

        notification_body = self._build_moderator_notification_text(
            ticket_id=ticket_id,
            guest_display_name=guest_display_name,
            source_platform=source_platform,
            question_text=question_text,
        )
        for moderator_account in moderators:
            if (
                moderator_account.platform == source_platform
                and moderator_account.external_id == source_external_id
            ):
                # Если обращение создано из аккаунта модератора, не шлем уведомление в тот же аккаунт.
                continue

            unit_of_work.support_repository.add_message(
                SupportMessage(
                    message_id=self._build_moderator_notification_message_id(
                        source_message_id=source_message_id,
                        target_platform=moderator_account.platform,
                        target_external_id=moderator_account.external_id,
                    ),
                    ticket_id=ticket_id,
                    author=SupportMessageAuthor.SYSTEM,
                    body=notification_body,
                    source_platform=source_platform,
                    target_platform=moderator_account.platform,
                    target_external_id=moderator_account.external_id,
                    delivery_status=SupportDeliveryStatus.CREATED,
                )
            )

    @staticmethod
    def _resolve_guest_display_name(*, first_name_input: str | None) -> str:
        """Возвращает отображаемое имя гостя для уведомления модератору."""

        value = (first_name_input or "").strip()
        if value:
            return value
        return "Гость"


@dataclass(frozen=True, slots=True)
class AddGuestMessageToTicketCommand:
    """Команда добавления сообщения гостя в существующий тикет."""

    platform: PlatformName
    external_id: str
    ticket_id: UUID
    message_text: str


@dataclass(frozen=True, slots=True)
class AddedGuestMessageToTicketResult:
    """Результат добавления сообщения гостя в существующий тикет."""

    ticket_id: UUID
    person_id: UUID
    source_platform: PlatformName
    message_id: UUID


class AddGuestMessageToTicketTransactionalUseCase:
    """Добавляет сообщение гостя в существующий тикет в рамках транзакции."""

    def __init__(self, unit_of_work_factory: Callable[[], SupportUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, command: AddGuestMessageToTicketCommand) -> AddedGuestMessageToTicketResult:
        """Регистрирует сообщение гостя в существующем тикете."""

        if command.platform not in SUPPORTED_PLATFORMS:
            raise ValueError("Платформа не поддерживается. Допустимые значения: telegram, vk, max.")

        external_id = str(command.external_id).strip()
        if not external_id:
            raise ValueError("Внешний идентификатор аккаунта не может быть пустым.")

        message_text = str(command.message_text).strip()
        if not message_text:
            raise ValueError("Текст обращения не может быть пустым.")
        if len(message_text) < MIN_SUPPORT_QUESTION_LENGTH:
            raise ValueError(
                f"Текст обращения должен содержать минимум {MIN_SUPPORT_QUESTION_LENGTH} символов."
            )

        with self._unit_of_work_factory() as unit_of_work:
            person = unit_of_work.identity_repository.get_person_by_account(command.platform, external_id)
            if person is None:
                raise ValueError(
                    "Нельзя добавить сообщение: аккаунт не зарегистрирован в strict identity."
                )
            guest_display_name = self._resolve_guest_display_name(
                first_name_input=getattr(person, "first_name_input", None)
            )

            ticket = unit_of_work.support_repository.get_ticket(command.ticket_id)
            if ticket is None:
                raise ValueError("Тикет не найден.")
            if ticket.person_id != person.person_id:
                raise ValueError("Нельзя добавить сообщение: тикет принадлежит другому пользователю.")
            if ticket.status == SupportTicketStatus.CLOSED:
                raise ValueError("Нельзя добавить сообщение: тикет уже закрыт.")

            message_id = uuid4()
            unit_of_work.support_repository.add_message(
                SupportMessage(
                    message_id=message_id,
                    ticket_id=ticket.ticket_id,
                    author=SupportMessageAuthor.GUEST,
                    body=message_text,
                    source_platform=command.platform,
                )
            )
            if ticket.status == SupportTicketStatus.IN_PROGRESS:
                unit_of_work.support_repository.update_ticket_status(
                    ticket_id=ticket.ticket_id,
                    status=SupportTicketStatus.OPEN,
                )

            self._enqueue_moderator_notifications(
                unit_of_work=unit_of_work,
                source_message_id=message_id,
                ticket_id=ticket.ticket_id,
                source_platform=command.platform,
                source_external_id=external_id,
                guest_display_name=guest_display_name,
                message_text=message_text,
            )
            unit_of_work.commit()
            return AddedGuestMessageToTicketResult(
                ticket_id=ticket.ticket_id,
                person_id=person.person_id,
                source_platform=command.platform,
                message_id=message_id,
            )

    @staticmethod
    def _build_moderator_notification_message_id(
        *,
        source_message_id: UUID,
        target_platform: PlatformName,
        target_external_id: str,
    ) -> UUID:
        """Формирует детерминированный message_id для защиты от дублей уведомлений."""

        seed = f"mod-followup:{source_message_id}:{target_platform}:{target_external_id}"
        return uuid5(NAMESPACE_URL, seed)

    @staticmethod
    def _build_moderator_notification_text(
        *,
        ticket_id: UUID,
        guest_display_name: str,
        source_platform: PlatformName,
        message_text: str,
    ) -> str:
        """Формирует текст уведомления модератору о новом сообщении гостя в тикете."""

        short_id = str(ticket_id)[-4:].upper()
        return "\n".join(
            (
                "📨 Новое сообщение гостя в обращении",
                f"Гость: {guest_display_name}",
                f"Тикет: #{short_id}",
                f"Канал: {source_platform}",
                "",
                "Сообщение:",
                message_text,
                "",
                "Нажмите «✍️ Ответить» или откройте меню модератора командой /mod.",
            )
        )

    def _enqueue_moderator_notifications(
        self,
        *,
        unit_of_work: SupportUnitOfWork,
        source_message_id: UUID,
        ticket_id: UUID,
        source_platform: PlatformName,
        source_external_id: str,
        guest_display_name: str,
        message_text: str,
    ) -> None:
        """Ставит в outbox уведомления модераторам о новом сообщении гостя в тикете."""

        moderators = unit_of_work.identity_repository.list_moderator_accounts()
        if not moderators:
            return

        notification_body = self._build_moderator_notification_text(
            ticket_id=ticket_id,
            guest_display_name=guest_display_name,
            source_platform=source_platform,
            message_text=message_text,
        )
        for moderator_account in moderators:
            if (
                moderator_account.platform == source_platform
                and moderator_account.external_id == source_external_id
            ):
                # Если сообщение оставлено из аккаунта модератора, не шлем уведомление в тот же аккаунт.
                continue

            unit_of_work.support_repository.add_message(
                SupportMessage(
                    message_id=self._build_moderator_notification_message_id(
                        source_message_id=source_message_id,
                        target_platform=moderator_account.platform,
                        target_external_id=moderator_account.external_id,
                    ),
                    ticket_id=ticket_id,
                    author=SupportMessageAuthor.SYSTEM,
                    body=notification_body,
                    source_platform=source_platform,
                    target_platform=moderator_account.platform,
                    target_external_id=moderator_account.external_id,
                    delivery_status=SupportDeliveryStatus.CREATED,
                )
            )

    @staticmethod
    def _resolve_guest_display_name(*, first_name_input: str | None) -> str:
        """Возвращает отображаемое имя гостя для уведомления модератору."""

        value = (first_name_input or "").strip()
        if value:
            return value
        return "Гость"


@dataclass(frozen=True, slots=True)
class ModeratorReplyCommand:
    """Команда маршрутизации ответа модератора."""

    ticket_id: UUID
    moderator_platform: PlatformName
    reply_text: str
    preferred_target_platform: PlatformName | None = None


@dataclass(frozen=True, slots=True)
class ModeratorReplyRoutingResult:
    """Результат маршрутизации ответа модератора."""

    ticket_id: UUID
    message_id: UUID
    guest_source_platform: PlatformName
    target_platform: PlatformName
    target_external_id: str


class RouteModeratorReplyTransactionalUseCase:
    """Маршрутизирует ответ модератора в целевой канал гостя."""

    def __init__(self, unit_of_work_factory: Callable[[], SupportUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, command: ModeratorReplyCommand) -> ModeratorReplyRoutingResult:
        """Создает сообщение модератора и определяет канал доставки."""

        if command.moderator_platform not in SUPPORTED_PLATFORMS:
            raise ValueError("Платформа модератора не поддерживается.")
        if command.preferred_target_platform is not None and (
            command.preferred_target_platform not in SUPPORTED_PLATFORMS
        ):
            raise ValueError("Целевая платформа доставки не поддерживается.")

        reply_text = str(command.reply_text).strip()
        if not reply_text:
            raise ValueError("Текст ответа модератора не может быть пустым.")

        with self._unit_of_work_factory() as unit_of_work:
            ticket = unit_of_work.support_repository.get_ticket(command.ticket_id)
            if ticket is None:
                raise ValueError("Тикет не найден.")
            if ticket.status == SupportTicketStatus.CLOSED:
                raise ValueError("Нельзя ответить: тикет уже закрыт.")

            person = unit_of_work.identity_repository.get_person_by_id(ticket.person_id)
            if person is None:
                raise ValueError("Пользователь тикета не найден в strict identity.")

            account_by_platform = {account.platform: account.external_id for account in person.accounts}
            if not account_by_platform:
                raise ValueError("У пользователя нет привязанных аккаунтов для доставки ответа.")

            target_platform = self._resolve_target_platform(
                preferred=command.preferred_target_platform,
                last_guest=ticket.last_guest_platform,
                available_platforms=set(account_by_platform.keys()),
            )
            target_external_id = account_by_platform[target_platform]

            message_id = uuid4()
            unit_of_work.support_repository.add_message(
                SupportMessage(
                    message_id=message_id,
                    ticket_id=ticket.ticket_id,
                    author=SupportMessageAuthor.MODERATOR,
                    body=reply_text,
                    source_platform=command.moderator_platform,
                    target_platform=target_platform,
                    target_external_id=target_external_id,
                    delivery_status=SupportDeliveryStatus.CREATED,
                )
            )
            if ticket.status == SupportTicketStatus.OPEN:
                unit_of_work.support_repository.update_ticket_status(
                    ticket_id=ticket.ticket_id,
                    status=SupportTicketStatus.IN_PROGRESS,
                )
            unit_of_work.commit()

            guest_source = ticket.last_guest_platform or ticket.source_platform
            return ModeratorReplyRoutingResult(
                ticket_id=ticket.ticket_id,
                message_id=message_id,
                guest_source_platform=guest_source,
                target_platform=target_platform,
                target_external_id=target_external_id,
            )

    @staticmethod
    def _resolve_target_platform(
        *,
        preferred: PlatformName | None,
        last_guest: PlatformName | None,
        available_platforms: set[PlatformName],
    ) -> PlatformName:
        """Определяет целевой канал доставки ответа модератора."""

        if preferred is not None and preferred in available_platforms:
            return preferred
        if last_guest is not None and last_guest in available_platforms:
            return last_guest
        # Детерминированный fallback, чтобы маршрутизация не зависела от порядка set.
        return sorted(available_platforms)[0]


@dataclass(frozen=True, slots=True)
class SetSupportTicketStatusCommand:
    """Команда изменения статуса тикета модератором."""

    ticket_id: UUID
    status: SupportTicketStatus


@dataclass(frozen=True, slots=True)
class SetSupportTicketStatusResult:
    """Результат изменения статуса тикета."""

    ticket_id: UUID
    previous_status: SupportTicketStatus
    new_status: SupportTicketStatus


class SetSupportTicketStatusTransactionalUseCase:
    """Изменяет статус тикета с валидацией допустимых переходов."""

    def __init__(self, unit_of_work_factory: Callable[[], SupportUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, command: SetSupportTicketStatusCommand) -> SetSupportTicketStatusResult:
        """Обновляет статус тикета в рамках транзакции."""

        with self._unit_of_work_factory() as unit_of_work:
            ticket = unit_of_work.support_repository.get_ticket(command.ticket_id)
            if ticket is None:
                raise ValueError("Тикет не найден.")

            previous_status = ticket.status
            new_status = command.status
            if previous_status == new_status:
                return SetSupportTicketStatusResult(
                    ticket_id=ticket.ticket_id,
                    previous_status=previous_status,
                    new_status=new_status,
                )

            if previous_status == SupportTicketStatus.CLOSED and new_status != SupportTicketStatus.CLOSED:
                raise ValueError("Закрытый тикет нельзя перевести в другой статус.")

            unit_of_work.support_repository.update_ticket_status(
                ticket_id=ticket.ticket_id,
                status=new_status,
            )
            unit_of_work.commit()
            return SetSupportTicketStatusResult(
                ticket_id=ticket.ticket_id,
                previous_status=previous_status,
                new_status=new_status,
            )


@dataclass(frozen=True, slots=True)
class SupportTicketDetails:
    """Карточка тикета для модератора."""

    ticket_id: UUID
    person_id: UUID
    status: SupportTicketStatus
    source_platform: PlatformName
    last_guest_platform: PlatformName | None
    linked_platforms: tuple[PlatformName, ...]


@dataclass(frozen=True, slots=True)
class SupportTicketConversationMessage:
    """Сообщение тикета в карточке истории переписки."""

    author: SupportMessageAuthor
    body: str
    source_platform: PlatformName
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class SupportTicketConversation:
    """Карточка тикета с историей сообщений."""

    ticket_id: UUID
    person_id: UUID
    status: SupportTicketStatus
    source_platform: PlatformName
    last_guest_platform: PlatformName | None
    linked_platforms: tuple[PlatformName, ...]
    messages: tuple[SupportTicketConversationMessage, ...]


class GetSupportTicketDetailsTransactionalUseCase:
    """Возвращает карточку тикета и платформы гостя."""

    def __init__(self, unit_of_work_factory: Callable[[], SupportUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, ticket_id: UUID) -> SupportTicketDetails:
        """Читает карточку тикета для модератора."""

        with self._unit_of_work_factory() as unit_of_work:
            ticket = unit_of_work.support_repository.get_ticket(ticket_id)
            if ticket is None:
                raise ValueError("Тикет не найден.")

            person = unit_of_work.identity_repository.get_person_by_id(ticket.person_id)
            if person is None:
                raise ValueError("Пользователь тикета не найден в strict identity.")

            linked_platforms = tuple(sorted(account.platform for account in person.accounts))
            return SupportTicketDetails(
                ticket_id=ticket.ticket_id,
                person_id=ticket.person_id,
                status=ticket.status,
                source_platform=ticket.source_platform,
                last_guest_platform=ticket.last_guest_platform,
                linked_platforms=linked_platforms,
            )


class GetSupportTicketConversationTransactionalUseCase:
    """Возвращает карточку тикета и историю переписки."""

    def __init__(self, unit_of_work_factory: Callable[[], SupportUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, ticket_id: UUID) -> SupportTicketConversation:
        """Читает карточку тикета и связанные сообщения."""

        with self._unit_of_work_factory() as unit_of_work:
            ticket = unit_of_work.support_repository.get_ticket(ticket_id)
            if ticket is None:
                raise ValueError("Тикет не найден.")

            person = unit_of_work.identity_repository.get_person_by_id(ticket.person_id)
            if person is None:
                raise ValueError("Пользователь тикета не найден в strict identity.")

            linked_platforms = tuple(sorted(account.platform for account in person.accounts))
            messages = tuple(
                message
                for message in unit_of_work.support_repository.list_messages(ticket_id)
                if message.author != SupportMessageAuthor.SYSTEM
            )

            return SupportTicketConversation(
                ticket_id=ticket.ticket_id,
                person_id=ticket.person_id,
                status=ticket.status,
                source_platform=ticket.source_platform,
                last_guest_platform=ticket.last_guest_platform,
                linked_platforms=linked_platforms,
                messages=tuple(
                    SupportTicketConversationMessage(
                        author=message.author,
                        body=message.body,
                        source_platform=message.source_platform,
                        created_at=message.created_at,
                    )
                    for message in messages
                ),
            )


@dataclass(frozen=True, slots=True)
class OpenSupportTicketSummary:
    """Краткая карточка открытого тикета для меню модератора."""

    ticket_id: UUID
    status: SupportTicketStatus
    source_platform: PlatformName
    last_guest_platform: PlatformName | None
    created_at: datetime | None


class ListOpenSupportTicketsTransactionalUseCase:
    """Возвращает список открытых тикетов для модераторского меню."""

    def __init__(self, unit_of_work_factory: Callable[[], SupportUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(
        self,
        *,
        limit: int = 10,
        statuses: tuple[SupportTicketStatus, ...] | None = None,
    ) -> tuple[OpenSupportTicketSummary, ...]:
        """Читает открытые тикеты с ограничением по количеству."""

        safe_limit = max(int(limit), 1)
        safe_statuses = tuple(dict.fromkeys(statuses or (SupportTicketStatus.OPEN,)))
        if not safe_statuses:
            raise ValueError("Набор статусов для фильтрации тикетов не может быть пустым.")
        with self._unit_of_work_factory() as unit_of_work:
            tickets = unit_of_work.support_repository.list_tickets_by_status(
                statuses=safe_statuses,
                limit=safe_limit,
            )

        # Нормализуем сортировку по дате по убыванию, чтобы интерфейс
        # модератора всегда показывал самые свежие тикеты вверху.
        epoch = datetime.fromtimestamp(0, tz=timezone.utc)
        sorted_tickets = sorted(
            tickets,
            key=lambda item: item.created_at or epoch,
            reverse=True,
        )
        return tuple(
            OpenSupportTicketSummary(
                ticket_id=ticket.ticket_id,
                status=ticket.status,
                source_platform=ticket.source_platform,
                last_guest_platform=ticket.last_guest_platform,
                created_at=ticket.created_at,
            )
            for ticket in sorted_tickets[:safe_limit]
        )


@dataclass(frozen=True, slots=True)
class PersonSupportTicketSummary:
    """Краткая карточка тикета для раздела «Мои обращения»."""

    ticket_id: UUID
    status: SupportTicketStatus
    source_platform: PlatformName
    last_guest_platform: PlatformName | None
    created_at: datetime | None


class ListPersonSupportTicketsTransactionalUseCase:
    """Возвращает тикеты конкретного пользователя для гостевого меню."""

    def __init__(self, unit_of_work_factory: Callable[[], SupportUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(
        self,
        *,
        platform: PlatformName,
        external_id: str,
        limit: int = 10,
    ) -> tuple[PersonSupportTicketSummary, ...]:
        """Читает список тикетов пользователя по его аккаунту платформы."""

        if platform not in SUPPORTED_PLATFORMS:
            raise ValueError("Платформа не поддерживается.")

        safe_external_id = str(external_id).strip()
        if not safe_external_id:
            raise ValueError("Внешний идентификатор аккаунта не может быть пустым.")

        safe_limit = max(int(limit), 1)
        with self._unit_of_work_factory() as unit_of_work:
            person = unit_of_work.identity_repository.get_person_by_account(platform, safe_external_id)
            if person is None:
                return ()
            tickets = unit_of_work.support_repository.list_person_tickets(
                person_id=person.person_id,
                limit=safe_limit,
            )

        return tuple(
            PersonSupportTicketSummary(
                ticket_id=ticket.ticket_id,
                status=ticket.status,
                source_platform=ticket.source_platform,
                last_guest_platform=ticket.last_guest_platform,
                created_at=ticket.created_at,
            )
            for ticket in tickets[:safe_limit]
        )


@dataclass(frozen=True, slots=True)
class PersonTicketsPageResult:
    """Результат страницы тикетов пользователя с пагинацией."""

    tickets: tuple[PersonSupportTicketSummary, ...]
    total_tickets: int
    page: int
    per_page: int
    total_pages: int


class GetPersonTicketsPageTransactionalUseCase:
    """Возвращает страницу тикетов пользователя с пагинацией."""

    def __init__(self, unit_of_work_factory: Callable[[], SupportUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(
        self,
        *,
        platform: PlatformName,
        external_id: str,
        page: int = 1,
        per_page: int = 5,
    ) -> PersonTicketsPageResult:
        """Читает страницу тикетов пользователя по его аккаунту платформы."""

        if platform not in SUPPORTED_PLATFORMS:
            raise ValueError("Платформа не поддерживается.")

        safe_external_id = str(external_id).strip()
        if not safe_external_id:
            raise ValueError("Внешний идентификатор аккаунта не может быть пустым.")

        if page < 1:
            page = 1
        if per_page < 1:
            per_page = 5

        with self._unit_of_work_factory() as unit_of_work:
            person = unit_of_work.identity_repository.get_person_by_account(platform, safe_external_id)
            if person is None:
                # Если пользователь не найден, возвращаем пустую страницу
                return PersonTicketsPageResult(
                    tickets=(),
                    total_tickets=0,
                    page=page,
                    per_page=per_page,
                    total_pages=0,
                )
            tickets, total = unit_of_work.support_repository.list_person_tickets_page(
                person_id=person.person_id,
                page=page,
                per_page=per_page,
            )

            total_pages = (total + per_page - 1) // per_page if total > 0 else 0

            summaries = tuple(
                PersonSupportTicketSummary(
                    ticket_id=ticket.ticket_id,
                    status=ticket.status,
                    source_platform=ticket.source_platform,
                    last_guest_platform=ticket.last_guest_platform,
                    created_at=ticket.created_at,
                )
                for ticket in tickets
            )
            return PersonTicketsPageResult(
                tickets=summaries,
                total_tickets=total,
                page=page,
                per_page=per_page,
                total_pages=total_pages,
            )


@dataclass(frozen=True, slots=True)
class PendingModeratorDelivery:
    """Краткая карточка pending-сообщения outbox для доставки в мессенджер."""

    message_id: UUID
    author: SupportMessageAuthor
    ticket_id: UUID
    source_platform: PlatformName
    target_platform: PlatformName
    target_external_id: str
    body: str
    created_at: datetime | None


class PullPendingModeratorMessagesTransactionalUseCase:
    """Возвращает pending-сообщения по целевой платформе доставки.

    В выборку входят:
    1. ответы модератора гостю;
    2. системные уведомления модераторам о новых обращениях.
    """

    def __init__(self, unit_of_work_factory: Callable[[], SupportUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(
        self,
        *,
        target_platform: PlatformName,
        limit: int = 20,
    ) -> tuple[PendingModeratorDelivery, ...]:
        """Читает pending-сообщения для заданного канала."""

        if target_platform not in SUPPORTED_PLATFORMS:
            raise ValueError("Платформа доставки не поддерживается.")

        safe_limit = max(int(limit), 1)
        with self._unit_of_work_factory() as unit_of_work:
            messages = unit_of_work.support_repository.pull_pending_moderator_messages(
                target_platform=target_platform,
                limit=safe_limit,
            )

        return tuple(
            PendingModeratorDelivery(
                message_id=message.message_id,
                author=message.author,
                ticket_id=message.ticket_id,
                source_platform=message.source_platform,
                target_platform=message.target_platform or target_platform,
                target_external_id=message.target_external_id or "",
                body=message.body,
                created_at=message.created_at,
            )
            for message in messages[:safe_limit]
        )


@dataclass(frozen=True, slots=True)
class UpdateModeratorMessageDeliveryStatusCommand:
    """Команда обновления статуса доставки модераторского сообщения."""

    message_id: UUID
    status: SupportDeliveryStatus
    error_text: str | None = None


class UpdateModeratorMessageDeliveryStatusTransactionalUseCase:
    """Обновляет delivery-статус модераторского сообщения в транзакции."""

    def __init__(self, unit_of_work_factory: Callable[[], SupportUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, command: UpdateModeratorMessageDeliveryStatusCommand) -> None:
        """Фиксирует delivery-статус (`sent` или `failed`) модераторского сообщения."""

        if command.status not in {SupportDeliveryStatus.SENT, SupportDeliveryStatus.FAILED}:
            raise ValueError("Для обновления доставки допустимы только статусы sent/failed.")

        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.support_repository.update_message_delivery(
                message_id=command.message_id,
                status=command.status,
                error_text=command.error_text,
            )
            unit_of_work.commit()
