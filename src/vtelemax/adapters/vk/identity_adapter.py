"""VK-адаптер сценариев гостя на едином контракте core."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import UUID

from loguru import logger

from vtelemax.core import (
    AddGuestMessageToTicketCommand,
    AddGuestMessageToTicketTransactionalUseCase,
    BUTTON_ACCEPT_RULES,
    BUTTON_RETRY_IIKO_SYNC,
    BUTTON_SUPPORT_QUESTION,
    BUTTON_MY_TICKETS,
    BUTTON_BACK_TO_SUPPORT,
    CreateSupportTicketCommand,
    CreateSupportTicketTransactionalUseCase,
    EnqueueProfileSyncCommand,
    EnqueueProfileSyncTransactionalUseCase,
    GetLoyaltyBalanceUseCase,
    GetPersonTicketsPageTransactionalUseCase,
    LoyaltyCustomerUpsertData,
    LoyaltyGateway,
    LoyaltyGatewayError,
    GetPersonByAccountCommand,
    GetPersonByAccountTransactionalUseCase,
    ListOpenSupportTicketsTransactionalUseCase,
    ListPersonSupportTicketsTransactionalUseCase,
    GetSupportTicketConversationTransactionalUseCase,
    GetSupportTicketDetailsTransactionalUseCase,
    GetVirtualCardUseCase,
    GuestMenuAction,
    IdentityConflictError,
    ModeratorReplyCommand,
    OnboardingFlowService,
    OnboardingState,
    OpenSupportTicketSummary,
    PersonSupportTicketSummary,
    PersonTicketsPageResult,
    PlatformName,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
    RouteModeratorReplyTransactionalUseCase,
    SetSupportTicketStatusCommand,
    SetSupportTicketStatusTransactionalUseCase,
    SUPPORTED_PLATFORMS,
    SupportTicketStatus,
    normalize_email,
    normalize_menu_text,
    normalize_person_name,
    parse_birth_date,
    resolve_guest_menu_action,
)

from .menu_adapter import (
    MOD_CLOSE_PREFIX,
    MOD_LIST_PREFIX,
    MOD_MAIN_CALLBACK,
    MOD_PAGE_PREFIX,
    MOD_REPLY_PREFIX,
    MOD_TAKE_PREFIX,
    MOD_TICKET_PREFIX,
    VkButton,
    VkGuestMenuAdapter,
    VkScreen,
)
from .payloads import build_vk_payload, resolve_action_from_vk_payload

_STATE_WAITING_PHONE = OnboardingState.WAITING_PHONE.value
_STATE_WAITING_RULES_CONSENT = OnboardingState.WAITING_RULES_CONSENT.value
_STATE_WAITING_FIRST_NAME = OnboardingState.WAITING_FIRST_NAME.value
_STATE_WAITING_NOTIFICATIONS_CONSENT = OnboardingState.WAITING_NOTIFICATIONS_CONSENT.value
_STATE_WAITING_IIKO_SYNC = OnboardingState.WAITING_IIKO_SYNC.value
_STATE_WAITING_LEGACY_PHONE = OnboardingState.WAITING_LEGACY_PHONE.value
_STATE_WAITING_SUPPORT_QUESTION = "waiting_support_question"
_STATE_WAITING_SUPPORT_REPLY = "waiting_support_reply"
_STATE_PROFILE_EDIT_CHOICE = "profile_edit_choice"
_STATE_PROFILE_EDIT_FIRST_NAME = "profile_edit_first_name"
_STATE_PROFILE_EDIT_LAST_NAME = "profile_edit_last_name"
_STATE_PROFILE_EDIT_GENDER = "profile_edit_gender"
_STATE_PROFILE_EDIT_BIRTH_DATE = "profile_edit_birth_date"
_STATE_PROFILE_EDIT_EMAIL = "profile_edit_email"
_STATE_PROFILE_EDIT_NOTIFICATIONS = "profile_edit_notifications"
_STATE_MOD_MENU = "moderation_menu"
_STATE_MOD_WAIT_TICKET_FOR_REPLY = "moderation_wait_ticket_for_reply"
_STATE_MOD_WAIT_REPLY_TEXT = "moderation_wait_reply_text"
_STATE_MOD_WAIT_TICKET_FOR_DETAILS = "moderation_wait_ticket_for_details"
_STATE_MOD_WAIT_TICKET_FOR_CLOSE = "moderation_wait_ticket_for_close"
_STATE_MOD_WAIT_TICKET_FOR_IN_PROGRESS = "moderation_wait_ticket_for_in_progress"

# Префиксы callback'ов пагинации тикетов (аналогично Telegram)
USER_TICKETS_PREV_PAGE_PREFIX = "user_tickets_prev_"
USER_TICKETS_NEXT_PAGE_PREFIX = "user_tickets_next_"
USER_TICKET_DETAILS_PREFIX = "user_ticket_"
USER_TICKET_REPLY_PREFIX = "ticket_reply_"

_MOD_FILTER_NEW = "new"
_MOD_FILTER_WORK = "work"
_MOD_FILTER_CLOSED = "closed"
_MOD_FILTER_ALL = "all"
_MOD_FILTER_ORDER: tuple[str, ...] = (
    _MOD_FILTER_NEW,
    _MOD_FILTER_WORK,
    _MOD_FILTER_CLOSED,
    _MOD_FILTER_ALL,
)
_MOD_FILTER_TO_STATUSES: dict[str, tuple[SupportTicketStatus, ...]] = {
    _MOD_FILTER_NEW: (SupportTicketStatus.OPEN,),
    _MOD_FILTER_WORK: (SupportTicketStatus.IN_PROGRESS,),
    _MOD_FILTER_CLOSED: (SupportTicketStatus.CLOSED,),
    _MOD_FILTER_ALL: (
        SupportTicketStatus.OPEN,
        SupportTicketStatus.IN_PROGRESS,
        SupportTicketStatus.CLOSED,
    ),
}
_MOD_FILTER_TITLES: dict[str, str] = {
    _MOD_FILTER_NEW: "🆕 Новые обращения",
    _MOD_FILTER_WORK: "🛠 Обращения в работе",
    _MOD_FILTER_CLOSED: "✅ Закрытые обращения",
    _MOD_FILTER_ALL: "📚 Все обращения",
}


@dataclass(frozen=True, slots=True)
class VkAdapterResponse:
    """Ответ VK-адаптера для отправки пользователю."""

    text: str
    screen: VkScreen | None = None
    parse_mode: str | None = None
    virtual_card_numbers: tuple[str, ...] = ()


@dataclass(slots=True)
class _OnboardingDraft:
    """Промежуточные данные сокращенной регистрации до финальной фиксации."""

    rules_accepted_at: datetime | None = None
    phone_e164: str | None = None
    phone_verified_at: datetime | None = None
    phone_verification_method: str | None = None
    first_name_input: str | None = None
    is_legacy_upgrade: bool = False


class VkIdentityAdapter:
    """Сервисный VK-адаптер для guest-сценариев."""

    def __init__(
        self,
        registration_use_case: RegisterOrAttachAccountTransactionalUseCase,
        person_lookup_use_case: GetPersonByAccountTransactionalUseCase,
        menu_adapter: VkGuestMenuAdapter | None = None,
        create_support_ticket_use_case: CreateSupportTicketTransactionalUseCase | None = None,
        add_guest_message_to_ticket_use_case: AddGuestMessageToTicketTransactionalUseCase | None = None,
        moderator_reply_use_case: RouteModeratorReplyTransactionalUseCase | None = None,
        ticket_details_use_case: GetSupportTicketDetailsTransactionalUseCase | None = None,
        ticket_conversation_use_case: GetSupportTicketConversationTransactionalUseCase | None = None,
        list_open_tickets_use_case: ListOpenSupportTicketsTransactionalUseCase | None = None,
        set_ticket_status_use_case: SetSupportTicketStatusTransactionalUseCase | None = None,
        list_person_tickets_use_case: ListPersonSupportTicketsTransactionalUseCase | None = None,
        get_person_tickets_page_use_case: GetPersonTicketsPageTransactionalUseCase | None = None,
        balance_use_case: GetLoyaltyBalanceUseCase | None = None,
        virtual_card_use_case: GetVirtualCardUseCase | None = None,
        loyalty_gateway: LoyaltyGateway | None = None,
        enqueue_profile_sync_use_case: EnqueueProfileSyncTransactionalUseCase | None = None,
    ) -> None:
        self._logger = logger.bind(platform="vk", component="identity_adapter")
        self._registration_use_case = registration_use_case
        self._person_lookup_use_case = person_lookup_use_case
        self._menu_adapter = menu_adapter or VkGuestMenuAdapter()
        self._state_by_user_id: dict[int, str] = {}
        self._reply_ticket_id_by_user_id: dict[int, UUID] = {}
        self._onboarding_draft_by_user_id: dict[int, _OnboardingDraft] = {}
        self._moderator_state_by_user_id: dict[int, str] = {}
        self._moderator_context_by_user_id: dict[int, dict[str, str]] = {}
        self._onboarding_flow = OnboardingFlowService(platform="vk")
        self._create_support_ticket_use_case = create_support_ticket_use_case
        self._add_guest_message_to_ticket_use_case = add_guest_message_to_ticket_use_case
        self._moderator_reply_use_case = moderator_reply_use_case
        self._ticket_details_use_case = ticket_details_use_case
        self._ticket_conversation_use_case = ticket_conversation_use_case
        self._list_open_tickets_use_case = list_open_tickets_use_case
        self._set_ticket_status_use_case = set_ticket_status_use_case
        self._list_person_tickets_use_case = list_person_tickets_use_case
        self._get_person_tickets_page_use_case = get_person_tickets_page_use_case
        self._balance_use_case = balance_use_case
        self._virtual_card_use_case = virtual_card_use_case
        self._loyalty_gateway = loyalty_gateway
        self._enqueue_profile_sync_use_case = enqueue_profile_sync_use_case

    def handle_start(self, vk_user_id: int) -> VkAdapterResponse:
        """Обрабатывает стартовый вход пользователя в VK-бот."""

        method_logger = self._logger.bind(stage="handle_start", user_id=str(vk_user_id))
        method_logger.debug("Обработка стартового входа пользователя.")
        if self._state_by_user_id.get(vk_user_id) == _STATE_WAITING_IIKO_SYNC:
            method_logger.info("Продолжаем шаг ожидания синхронизации iiko.")
            retry_screen = self._menu_adapter.build_iiko_sync_retry_screen()
            return VkAdapterResponse(text=retry_screen.text, screen=retry_screen)

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        if person is None:
            method_logger.info("Пользователь не найден, запускаем onboarding.")
            transition = self._onboarding_flow.begin_new_user()
            self._state_by_user_id[vk_user_id] = transition.state.value
            self._onboarding_draft_by_user_id[vk_user_id] = _OnboardingDraft()
            self._clear_moderator_state(vk_user_id)
            rules_screen = self._menu_adapter.build_start_rules_screen()
            return VkAdapterResponse(text=transition.message, screen=rules_screen)

        if not person.is_registered_for_platform("vk"):
            method_logger.info("Найден незавершенный профиль, восстанавливаем onboarding.")
            draft = _OnboardingDraft(
                rules_accepted_at=person.get_rules_accepted_at_for_platform("vk"),
                phone_e164=person.phone_e164,
                phone_verified_at=person.phone_verified_at,
                phone_verification_method=person.phone_verification_method,
                first_name_input=person.first_name_input,
                is_legacy_upgrade=person.is_legacy,
            )
            self._onboarding_draft_by_user_id[vk_user_id] = draft
            self._clear_moderator_state(vk_user_id)
            if not person.get_rules_accepted_for_platform("vk"):
                transition = self._onboarding_flow.begin_new_user()
                self._state_by_user_id[vk_user_id] = transition.state.value
                return VkAdapterResponse(
                    text=transition.message,
                    screen=self._menu_adapter.build_start_rules_screen(),
                )
            if not person.first_name_input:
                transition = self._onboarding_flow.begin_first_name_step()
                self._state_by_user_id[vk_user_id] = transition.state.value
                return VkAdapterResponse(text=transition.message, screen=None)

            transition = self._onboarding_flow.begin_notifications_consent_step(
                phone_e164=person.phone_e164,
                accounts_count=len(person.accounts),
                first_name_input=person.first_name_input,
            )
            self._state_by_user_id[vk_user_id] = transition.state.value
            return VkAdapterResponse(
                text=transition.message,
                screen=self._menu_adapter.build_notifications_consent_screen(),
            )

        # Проверяем, собраны ли все согласия для платформы VK.
        platform_consents_complete = (
            person.get_rules_accepted_for_platform("vk") is True
            and person.get_notifications_allowed_at_for_platform("vk") is not None
        )
        if not platform_consents_complete:
            method_logger.info(
                "Пользователь зарегистрирован, но согласия для VK неполные, продолжаем onboarding."
            )
            draft = _OnboardingDraft(
                rules_accepted_at=person.get_rules_accepted_at_for_platform("vk"),
                phone_e164=person.phone_e164,
                phone_verified_at=person.phone_verified_at,
                phone_verification_method=person.phone_verification_method,
                first_name_input=person.first_name_input,
                is_legacy_upgrade=person.is_legacy,
            )
            self._onboarding_draft_by_user_id[vk_user_id] = draft
            self._clear_moderator_state(vk_user_id)

            if not person.get_rules_accepted_for_platform("vk"):
                transition = self._onboarding_flow.begin_new_user()
                self._state_by_user_id[vk_user_id] = transition.state.value
                return VkAdapterResponse(
                    text=transition.message,
                    screen=self._menu_adapter.build_start_rules_screen(),
                )
            if not person.first_name_input:
                transition = self._onboarding_flow.begin_first_name_step()
                self._state_by_user_id[vk_user_id] = transition.state.value
                return VkAdapterResponse(text=transition.message, screen=None)

            transition = self._onboarding_flow.begin_notifications_consent_step(
                phone_e164=person.phone_e164,
                accounts_count=len(person.accounts),
                first_name_input=person.first_name_input,
            )
            self._state_by_user_id[vk_user_id] = transition.state.value
            return VkAdapterResponse(
                text=transition.message,
                screen=self._menu_adapter.build_notifications_consent_screen(),
            )

        self._state_by_user_id.pop(vk_user_id, None)
        self._onboarding_draft_by_user_id.pop(vk_user_id, None)
        self._clear_moderator_state(vk_user_id)
        method_logger.info("Пользователь найден, открываем главное меню.")
        main_screen = self._menu_adapter.build_main_menu_screen(
            user_name=self._resolve_menu_user_name(vk_user_id=vk_user_id, person=person)
        )
        return VkAdapterResponse(text=main_screen.text, screen=main_screen)

    def handle_legacy_start(self, vk_user_id: int) -> VkAdapterResponse:
        """Явно запускает legacy-ветку для зарегистрированного пользователя."""

        method_logger = self._logger.bind(stage="handle_legacy_start", user_id=str(vk_user_id))
        method_logger.debug("Обработка команды legacy.")
        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        if person is None:
            method_logger.info("Пользователь не найден, fallback на стартовый onboarding.")
            return self.handle_start(vk_user_id=vk_user_id)

        transition = self._onboarding_flow.begin_legacy_upgrade()
        method_logger.info("Legacy-flow запущен.")
        self._state_by_user_id[vk_user_id] = transition.state.value
        self._onboarding_draft_by_user_id[vk_user_id] = _OnboardingDraft(is_legacy_upgrade=True)
        self._clear_moderator_state(vk_user_id)
        contact_screen = self._menu_adapter.build_start_contact_screen()
        return VkAdapterResponse(text=transition.message, screen=contact_screen)

    def handle_incoming(self, vk_user_id: int, text: str, payload: dict[str, str] | None) -> VkAdapterResponse:
        """Обрабатывает входящее сообщение VK (text + payload)."""

        method_logger = self._logger.bind(stage="handle_incoming", user_id=str(vk_user_id))
        method_logger.debug("Входящее сообщение. text={text}.", text=text)
        state = self._state_by_user_id.get(vk_user_id)
        if state == _STATE_WAITING_RULES_CONSENT:
            return self._handle_rules_consent(vk_user_id=vk_user_id, text=text, payload=payload)
        if state == _STATE_WAITING_PHONE:
            action = resolve_action_from_vk_payload(payload)
            if action == GuestMenuAction.SHARE_CONTACT:
                return VkAdapterResponse(
                    text="Введите номер телефона в формате +79991234567.",
                    screen=self._menu_adapter.build_start_contact_screen(),
                )
            return self._handle_phone_input(vk_user_id=vk_user_id, text=text, is_legacy=False)
        if state == _STATE_WAITING_FIRST_NAME:
            return self._handle_first_name_input(vk_user_id=vk_user_id, text=text)
        if state == _STATE_WAITING_NOTIFICATIONS_CONSENT:
            return self._handle_notifications_consent(
                vk_user_id=vk_user_id,
                text=text,
                payload=payload,
            )
        if state == _STATE_WAITING_IIKO_SYNC:
            return self._handle_iiko_sync_retry(vk_user_id=vk_user_id, text=text, payload=payload)
        if state == _STATE_WAITING_LEGACY_PHONE:
            return self._handle_phone_input(vk_user_id=vk_user_id, text=text, is_legacy=True)
        if state == _STATE_WAITING_SUPPORT_QUESTION:
            action = resolve_action_from_vk_payload(payload)
            if action is None:
                action = resolve_guest_menu_action(text)
            if action in {
                GuestMenuAction.BACK_TO_MAIN,
                GuestMenuAction.BACK_TO_SUPPORT,
                GuestMenuAction.SUPPORT,
                GuestMenuAction.MAIN_MENU,
                GuestMenuAction.MY_TICKETS,
            }:
                self._state_by_user_id.pop(vk_user_id, None)
                return self._handle_action(vk_user_id=vk_user_id, action=action)
            self._state_by_user_id.pop(vk_user_id, None)
            # Если пользователь ввел что-то неожиданное в состоянии ожидания вопроса,
            # обрабатываем это как вопрос
            return self._handle_support_question(vk_user_id=vk_user_id, text=text)
        if state == _STATE_WAITING_SUPPORT_REPLY:
            action = resolve_action_from_vk_payload(payload)
            if action is None:
                action = resolve_guest_menu_action(text)
            if action in {
                GuestMenuAction.BACK_TO_MAIN,
                GuestMenuAction.BACK_TO_SUPPORT,
                GuestMenuAction.SUPPORT,
                GuestMenuAction.MAIN_MENU,
                GuestMenuAction.MY_TICKETS,
            }:
                self._state_by_user_id.pop(vk_user_id, None)
                self._reply_ticket_id_by_user_id.pop(vk_user_id, None)
                return self._handle_action(vk_user_id=vk_user_id, action=action)
            return self._handle_support_reply(vk_user_id=vk_user_id, text=text)
        if state == _STATE_PROFILE_EDIT_CHOICE:
            return self._handle_profile_edit_choice(vk_user_id=vk_user_id, text=text, payload=payload)
        if state == _STATE_PROFILE_EDIT_FIRST_NAME:
            return self._handle_profile_edit_first_name(vk_user_id=vk_user_id, text=text)
        if state == _STATE_PROFILE_EDIT_LAST_NAME:
            return self._handle_profile_edit_last_name(vk_user_id=vk_user_id, text=text)
        if state == _STATE_PROFILE_EDIT_GENDER:
            return self._handle_profile_edit_gender(vk_user_id=vk_user_id, text=text, payload=payload)
        if state == _STATE_PROFILE_EDIT_BIRTH_DATE:
            return self._handle_profile_edit_birth_date(vk_user_id=vk_user_id, text=text)
        if state == _STATE_PROFILE_EDIT_EMAIL:
            return self._handle_profile_edit_email(vk_user_id=vk_user_id, text=text)
        if state == _STATE_PROFILE_EDIT_NOTIFICATIONS:
            return self._handle_profile_edit_notifications(
                vk_user_id=vk_user_id,
                text=text,
                payload=payload,
            )

        moderator_response = self._try_handle_moderator_command(text=text, vk_user_id=vk_user_id)
        if moderator_response is not None:
            return moderator_response

        moderation_payload_response = self._try_handle_moderation_payload(
            vk_user_id=vk_user_id,
            payload=payload,
        )
        if moderation_payload_response is not None:
            return moderation_payload_response

        moderator_state = self._moderator_state_by_user_id.get(vk_user_id)
        if moderator_state is not None:
            return self._handle_moderator_state_input(vk_user_id=vk_user_id, text=text)

        # Обработка callback'ов пагинации тикетов
        if payload:
            cmd = str(payload.get("cmd", "")).strip()
            if cmd.startswith(USER_TICKETS_PREV_PAGE_PREFIX):
                try:
                    page = int(cmd[len(USER_TICKETS_PREV_PAGE_PREFIX):])
                except ValueError:
                    page = 1
                return self._show_user_tickets_page(vk_user_id=vk_user_id, page=page, per_page=5)
            if cmd.startswith(USER_TICKETS_NEXT_PAGE_PREFIX):
                try:
                    page = int(cmd[len(USER_TICKETS_NEXT_PAGE_PREFIX):])
                except ValueError:
                    page = 1
                return self._show_user_tickets_page(vk_user_id=vk_user_id, page=page, per_page=5)
            if cmd.startswith(USER_TICKET_REPLY_PREFIX):
                try:
                    ticket_id_str = cmd[len(USER_TICKET_REPLY_PREFIX):]
                    ticket_id = UUID(ticket_id_str)
                except ValueError:
                    return VkAdapterResponse(text="Неверный идентификатор тикета.")
                return self._begin_support_reply(vk_user_id=vk_user_id, ticket_id=ticket_id)
            if cmd.startswith(USER_TICKET_DETAILS_PREFIX):
                try:
                    ticket_id_str = cmd[len(USER_TICKET_DETAILS_PREFIX):]
                    ticket_id = UUID(ticket_id_str)
                except ValueError:
                    return VkAdapterResponse(
                        text="Неверный идентификатор тикета.",
                    )
                return self._handle_view_ticket_details(vk_user_id=vk_user_id, ticket_id=ticket_id)

        action = resolve_action_from_vk_payload(payload)
        if action is None:
            action = resolve_guest_menu_action(text)
        method_logger.debug("Распознанное действие: {action}.", action=action)

        if action is None:
            person = self._person_lookup_use_case.execute(
                GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
            )
            if person is None:
                self._state_by_user_id[vk_user_id] = _STATE_WAITING_RULES_CONSENT
                rules_screen = self._menu_adapter.build_start_rules_screen()
                return VkAdapterResponse(
                    text=(
                        "Чтобы продолжить, сначала подтвердите согласие с правилами.\n\n"
                        f"{rules_screen.text}"
                    ),
                    screen=rules_screen,
                )
            main_screen = self._menu_adapter.build_main_menu_screen(
                user_name=self._resolve_menu_user_name(vk_user_id=vk_user_id, person=person)
            )
            return VkAdapterResponse(
                text=(
                    "Команда не распознана. Доступные команды: /start, Начать, /help, Помощь.\n"
                    "Для навигации используйте кнопки меню.\n\n"
                    f"{main_screen.text}"
                ),
                screen=main_screen,
            )

        return self._handle_action(vk_user_id=vk_user_id, action=action)

    def _handle_rules_consent(
        self,
        vk_user_id: int,
        text: str,
        payload: dict[str, str] | None,
    ) -> VkAdapterResponse:
        """Обрабатывает шаг подтверждения согласия с правилами."""

        action = resolve_action_from_vk_payload(payload)
        consent_input = text
        if action in {GuestMenuAction.ACCEPT_RULES, GuestMenuAction.SHARE_CONTACT}:
            consent_input = BUTTON_ACCEPT_RULES

        transition = self._onboarding_flow.handle_rules_input(consent_input)
        next_transition = transition
        if transition.state == OnboardingState.WAITING_PHONE:
            draft = self._onboarding_draft_by_user_id.setdefault(vk_user_id, _OnboardingDraft())
            draft.rules_accepted_at = datetime.now(timezone.utc)
            if draft.is_legacy_upgrade:
                next_transition = self._onboarding_flow.begin_legacy_upgrade()
            self._state_by_user_id[vk_user_id] = next_transition.state.value
            screen = self._menu_adapter.build_start_contact_screen()
        else:
            self._state_by_user_id[vk_user_id] = next_transition.state.value
            screen = self._menu_adapter.build_start_rules_screen()
        return VkAdapterResponse(text=next_transition.message, screen=screen)

    def _handle_phone_input(self, vk_user_id: int, text: str, *, is_legacy: bool) -> VkAdapterResponse:
        """Обрабатывает ввод телефона для регистрации/legacy-обновления."""

        method_logger = self._logger.bind(stage="phone_input", user_id=str(vk_user_id))
        phone_text = (text or "").strip()
        draft = self._onboarding_draft_by_user_id.setdefault(vk_user_id, _OnboardingDraft())
        phone_verified_at = datetime.now(timezone.utc)
        if not phone_text:
            method_logger.warning("Пустой ввод телефона.")
            return VkAdapterResponse(
                text="Пожалуйста, введите номер телефона текстом в формате +79991234567.",
                screen=self._menu_adapter.build_start_contact_screen(),
            )

        try:
            person = self._registration_use_case.execute(
                RegisterOrAttachAccountCommand(
                    platform="vk",
                    external_id=str(vk_user_id),
                    raw_phone=phone_text,
                    rules_accepted=True if draft.rules_accepted_at is not None else None,
                    rules_accepted_at=draft.rules_accepted_at,
                    phone_verified_at=phone_verified_at,
                    phone_verification_method="vk_text_input",
                )
            )
        except IdentityConflictError:
            method_logger.warning("Конфликт strict identity при регистрации телефона.")
            return VkAdapterResponse(
                text=(
                    "Обнаружен конфликт идентификации: этот VK-аккаунт уже привязан к другому "
                    "телефону или телефон связан с другим аккаунтом."
                )
            )
        except ValueError:
            method_logger.warning("Ошибка валидации телефона.")
            return VkAdapterResponse(
                text=(
                    "Не удалось обработать номер телефона. Введите номер в формате +79991234567 "
                    "и попробуйте снова."
                ),
                screen=self._menu_adapter.build_start_contact_screen(),
            )

        draft.phone_e164 = person.phone_e164
        draft.phone_verified_at = phone_verified_at
        draft.phone_verification_method = "vk_text_input"
        legacy_flow_active = is_legacy or bool(person.is_legacy)
        # Проверяем, нужно ли собирать согласия для этой платформы
        platform_consents_complete = (
            person.get_rules_accepted_for_platform("vk") is True
            and person.get_notifications_allowed_at_for_platform("vk") is not None
        )
        if person.first_name_input and not legacy_flow_active and platform_consents_complete:
            # Все согласия для VK уже собраны, можно открыть главное меню
            self._state_by_user_id.pop(vk_user_id, None)
            self._onboarding_draft_by_user_id.pop(vk_user_id, None)
            self._clear_moderator_state(vk_user_id)
            method_logger.info(
                "Телефон найден в зарегистрированном профиле, завершаем привязку VK-аккаунта без повторного onboarding. person_id={person_id}.",
                person_id=person.person_id,
            )
            main_screen = self._menu_adapter.build_main_menu_screen(
                user_name=self._resolve_menu_user_name(vk_user_id=vk_user_id, person=person)
            )
            return VkAdapterResponse(text=main_screen.text, screen=main_screen)
        if legacy_flow_active and not draft.is_legacy_upgrade:
            draft.is_legacy_upgrade = True
        if not is_legacy and person.is_legacy:
            method_logger.info(
                "Обнаружен legacy-профиль по номеру телефона, переключаем пользователя в legacy-ветку. person_id={person_id}.",
                person_id=person.person_id,
            )

        if legacy_flow_active:
            person = self._prefill_profile_from_loyalty(
                vk_user_id=vk_user_id,
                person=person,
            )
            person_first_name = (person.first_name_input or "").strip()
            if person_first_name:
                draft.first_name_input = person_first_name
                transition = self._onboarding_flow.begin_notifications_consent_step(
                    phone_e164=draft.phone_e164,
                    accounts_count=len(person.accounts),
                    first_name_input=person_first_name,
                )
                self._state_by_user_id[vk_user_id] = transition.state.value
                method_logger.info(
                    "Legacy: телефон подтвержден, переходим к шагу согласия на рассылку. person_id={person_id}.",
                    person_id=person.person_id,
                )
                return VkAdapterResponse(
                    text=transition.message,
                    screen=self._menu_adapter.build_notifications_consent_screen(),
                )

            transition = self._onboarding_flow.begin_first_name_step()
            self._state_by_user_id[vk_user_id] = transition.state.value
            method_logger.info(
                "Legacy: телефон подтвержден, переходим к шагу ввода имени. person_id={person_id}.",
                person_id=person.person_id,
            )
            return VkAdapterResponse(text=transition.message, screen=None)

        # Определяем следующий шаг onboarding
        if person.first_name_input:
            # Имя уже есть, переходим к шагу согласия на рассылку
            draft.first_name_input = person.first_name_input
            transition = self._onboarding_flow.begin_notifications_consent_step(
                phone_e164=draft.phone_e164,
                accounts_count=len(person.accounts),
                first_name_input=person.first_name_input,
            )
            self._state_by_user_id[vk_user_id] = transition.state.value
            method_logger.info(
                "Телефон подтвержден, переходим к шагу согласия на рассылку. person_id={person_id}.",
                person_id=person.person_id,
            )
            return VkAdapterResponse(
                text=transition.message,
                screen=self._menu_adapter.build_notifications_consent_screen(),
            )
        else:
            # Имя отсутствует, запрашиваем его
            transition = self._onboarding_flow.begin_first_name_step()
            self._state_by_user_id[vk_user_id] = transition.state.value
            method_logger.info(
                "Телефон подтвержден, переходим к шагу имени. person_id={person_id}.",
                person_id=person.person_id,
            )
            return VkAdapterResponse(text=transition.message, screen=None)

    def _handle_first_name_input(self, vk_user_id: int, text: str) -> VkAdapterResponse:
        """Обрабатывает шаг ввода имени в сокращенной регистрации."""

        normalized_name = self._normalize_first_name(text)
        if normalized_name is None:
            return VkAdapterResponse(
                text=(
                    "Пожалуйста, укажите имя текстом (только буквы, пробел и дефис, "
                    "от 2 до 50 символов)."
                )
            )

        draft = self._onboarding_draft_by_user_id.get(vk_user_id)
        if draft is None or not draft.phone_e164:
            self._state_by_user_id[vk_user_id] = _STATE_WAITING_PHONE
            return VkAdapterResponse(
                text=(
                    "Потерян шаг подтверждения телефона. "
                    "Введите номер телефона в формате +79991234567."
                ),
                screen=self._menu_adapter.build_start_contact_screen(),
            )

        draft.first_name_input = normalized_name
        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        accounts_count = len(person.accounts) if person is not None else 1
        transition = self._onboarding_flow.begin_notifications_consent_step(
            phone_e164=draft.phone_e164,
            accounts_count=accounts_count,
            first_name_input=normalized_name,
        )
        self._state_by_user_id[vk_user_id] = transition.state.value
        return VkAdapterResponse(
            text=transition.message,
            screen=self._menu_adapter.build_notifications_consent_screen(),
        )

    def _handle_notifications_consent(
        self,
        *,
        vk_user_id: int,
        text: str,
        payload: dict[str, str] | None,
    ) -> VkAdapterResponse:
        """Обрабатывает выбор пользователя по шагу согласия на рассылку."""

        action = resolve_action_from_vk_payload(payload)
        consent_input = action.value if action is not None else text
        notifications_choice = self._onboarding_flow.handle_notifications_input(consent_input)
        if notifications_choice is None:
            return VkAdapterResponse(
                text=(
                    "Пожалуйста, выберите один из вариантов согласия на рассылку "
                    "(кнопка «Да» или «Нет»)."
                ),
                screen=self._menu_adapter.build_notifications_consent_screen(),
            )

        draft = self._onboarding_draft_by_user_id.get(vk_user_id)
        if draft is None or not draft.phone_e164 or not draft.first_name_input:
            self._state_by_user_id[vk_user_id] = _STATE_WAITING_PHONE
            return VkAdapterResponse(
                text=(
                    "Потеряны промежуточные данные регистрации. "
                    "Введите номер телефона в формате +79991234567."
                ),
                screen=self._menu_adapter.build_start_contact_screen(),
            )

        notifications_fixed_at = datetime.now(timezone.utc)
        # Определяем, давал ли пользователь согласие с правилами для VK
        rules_accepted = True if draft.rules_accepted_at is not None else None
        rules_accepted_at = draft.rules_accepted_at
        try:
            person = self._registration_use_case.execute(
                RegisterOrAttachAccountCommand(
                    platform="vk",
                    external_id=str(vk_user_id),
                    raw_phone=draft.phone_e164,
                    rules_accepted=rules_accepted,
                    rules_accepted_at=rules_accepted_at,
                    notifications_allowed=notifications_choice,
                    notifications_allowed_at=notifications_fixed_at,
                    first_name_input=draft.first_name_input,
                    is_legacy=False,
                    is_registered=True,
                    phone_verified_at=draft.phone_verified_at or notifications_fixed_at,
                    phone_verification_method=draft.phone_verification_method or "vk_text_input",
                )
            )
        except IdentityConflictError:
            return VkAdapterResponse(
                text=(
                    "Обнаружен конфликт идентификации при сохранении анкеты. "
                    "Повторите регистрацию через /start."
                )
            )
        except ValueError:
            return VkAdapterResponse(
                text="Не удалось завершить регистрацию из-за ошибки в данных. Повторите /start."
            )

        self._state_by_user_id[vk_user_id] = _STATE_WAITING_IIKO_SYNC
        draft.phone_e164 = person.phone_e164
        draft.first_name_input = person.first_name_input or draft.first_name_input
        return self._finalize_iiko_sync_step(
            vk_user_id=vk_user_id,
            phone_e164=person.phone_e164,
            first_name=draft.first_name_input or "Гость",
        )

    def _handle_iiko_sync_retry(
        self,
        *,
        vk_user_id: int,
        text: str,
        payload: dict[str, str] | None,
    ) -> VkAdapterResponse:
        """Обрабатывает повтор синхронизации с iiko в отдельном шаге onboarding."""

        action = resolve_action_from_vk_payload(payload) or resolve_guest_menu_action(text)
        if action != GuestMenuAction.RETRY_IIKO_SYNC:
            retry_screen = self._menu_adapter.build_iiko_sync_retry_screen()
            return VkAdapterResponse(
                text=(
                    f"{retry_screen.text}\n\n"
                    f"Нажмите кнопку «{BUTTON_RETRY_IIKO_SYNC}», чтобы повторить попытку."
                ),
                screen=retry_screen,
            )

        draft = self._onboarding_draft_by_user_id.get(vk_user_id)
        if draft is None or not draft.phone_e164:
            self._state_by_user_id[vk_user_id] = _STATE_WAITING_PHONE
            return VkAdapterResponse(
                text=(
                    "Не удалось восстановить шаг синхронизации. "
                    "Введите номер телефона в формате +79991234567."
                ),
                screen=self._menu_adapter.build_start_contact_screen(),
            )

        return self._finalize_iiko_sync_step(
            vk_user_id=vk_user_id,
            phone_e164=draft.phone_e164,
            first_name=draft.first_name_input or "Гость",
        )

    def _finalize_iiko_sync_step(
        self,
        *,
        vk_user_id: int,
        phone_e164: str,
        first_name: str,
    ) -> VkAdapterResponse:
        """Выполняет синхронизацию с iiko и завершает onboarding только при успехе."""

        registration_card_numbers = self._sync_registration_with_loyalty(
            phone_e164=phone_e164,
            profile=self._build_loyalty_upsert_profile(vk_user_id=vk_user_id),
        )
        if not registration_card_numbers and self._virtual_card_use_case is not None:
            self._state_by_user_id[vk_user_id] = _STATE_WAITING_IIKO_SYNC
            retry_screen = self._menu_adapter.build_iiko_sync_retry_screen()
            return VkAdapterResponse(text=retry_screen.text, screen=retry_screen)

        self._state_by_user_id.pop(vk_user_id, None)
        self._onboarding_draft_by_user_id.pop(vk_user_id, None)
        self._clear_moderator_state(vk_user_id)

        main_screen = self._menu_adapter.build_main_menu_screen(user_name=first_name)
        completion_parts = ["✅ Регистрация успешно завершена."]
        if registration_card_numbers:
            completion_parts.append("🪪 Выше представлены QR-коды ваших карт.")
        completion_parts.extend(
            [
                "ℹ️ Подробности анкеты и информацию профиля можно посмотреть и изменить в разделе «👤 Профиль».",
                main_screen.text,
            ]
        )
        return VkAdapterResponse(
            text="\n\n".join(completion_parts),
            screen=main_screen,
            virtual_card_numbers=registration_card_numbers,
        )

    def _handle_support_question(self, vk_user_id: int, text: str) -> VkAdapterResponse:
        """Обрабатывает шаг 'Мне только спросить' (ввод вопроса)."""

        question = (text or "").strip()
        if not question:
            return VkAdapterResponse(
                text="Пожалуйста, отправьте вопрос текстом. Мы передадим его модератору."
            )

        self._state_by_user_id.pop(vk_user_id, None)
        
        platform = "vk"
        if self._create_support_ticket_use_case is None:
            # Тестовый режим без use-case
            pass
        else:
            try:
                self._create_support_ticket_use_case.execute(
                    CreateSupportTicketCommand(
                        platform=platform,
                        external_id=str(vk_user_id),
                        question_text=question,
                    )
                )
            except ValueError as error:
                return VkAdapterResponse(
                    text=(
                        "Не удалось зарегистрировать обращение в системе модерации.\n"
                        f"Причина: {error}"
                    )
                )
        
        # После создания тикета показываем экран подтверждения с кнопкой "Назад в меню"
        screen = self._menu_adapter.build_support_question_confirmation_screen()
        return VkAdapterResponse(
            text=screen.text,
            screen=screen,
        )

    def _begin_support_reply(self, *, vk_user_id: int, ticket_id: UUID) -> VkAdapterResponse:
        """Переводит пользователя в режим ответа по выбранному тикету."""

        if self._add_guest_message_to_ticket_use_case is None:
            return VkAdapterResponse(text="Функция ответа по обращению временно недоступна.")

        if self._ticket_details_use_case is None:
            return VkAdapterResponse(text="Функционал просмотра деталей тикета временно недоступен.")

        try:
            details, _messages = self._get_ticket_details_with_history(ticket_id)
        except ValueError as error:
            return VkAdapterResponse(text=f"Тикет не найден: {error}")

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        if person is None or person.person_id != details.person_id:
            return VkAdapterResponse(text="У вас нет доступа к этому тикету.")

        if details.status == SupportTicketStatus.CLOSED:
            return VkAdapterResponse(
                text="Обращение уже закрыто. Откройте новое через пункт «❓ Мне только спросить»."
            )

        self._state_by_user_id[vk_user_id] = _STATE_WAITING_SUPPORT_REPLY
        self._reply_ticket_id_by_user_id[vk_user_id] = ticket_id
        short_id = self._format_ticket_id_short(ticket_id)
        return VkAdapterResponse(
            text=(
                f"✍️ Введите ответ для обращения #{short_id}.\n"
                "Минимальная длина ответа: 10 символов."
            )
        )

    def _handle_support_reply(self, *, vk_user_id: int, text: str) -> VkAdapterResponse:
        """Обрабатывает ответ гостя в существующем обращении."""

        ticket_id = self._reply_ticket_id_by_user_id.get(vk_user_id)
        if ticket_id is None:
            self._state_by_user_id.pop(vk_user_id, None)
            return VkAdapterResponse(
                text="Потерян контекст обращения. Откройте «📋 Мои обращения» и выберите тикет снова."
            )

        reply_text = (text or "").strip()
        if not reply_text:
            return VkAdapterResponse(
                text="Ответ не может быть пустым. Введите текст сообщения для модератора."
            )

        if self._add_guest_message_to_ticket_use_case is None:
            return VkAdapterResponse(text="Функция ответа по обращению временно недоступна.")

        try:
            self._add_guest_message_to_ticket_use_case.execute(
                AddGuestMessageToTicketCommand(
                    platform="vk",
                    external_id=str(vk_user_id),
                    ticket_id=ticket_id,
                    message_text=reply_text,
                )
            )
        except ValueError as error:
            error_text = str(error)
            if "закрыт" in error_text.lower():
                self._state_by_user_id.pop(vk_user_id, None)
                self._reply_ticket_id_by_user_id.pop(vk_user_id, None)
                return VkAdapterResponse(
                    text="Обращение уже закрыто. Откройте новое через пункт «❓ Мне только спросить»."
                )
            return VkAdapterResponse(
                text=(
                    "Не удалось добавить сообщение в обращение.\n"
                    f"Причина: {error_text}"
                )
            )

        self._state_by_user_id.pop(vk_user_id, None)
        self._reply_ticket_id_by_user_id.pop(vk_user_id, None)
        short_id = self._format_ticket_id_short(ticket_id)
        return VkAdapterResponse(
            text=(
                f"✅ Ответ по обращению #{short_id} отправлен модератору.\n"
                "Мы уведомим вас, когда поступит новый ответ."
            ),
            screen=self._menu_adapter.build_support_question_confirmation_screen(),
        )

    def _render_profile_screen(self, *, vk_user_id: int) -> VkAdapterResponse:
        """Возвращает экран профиля с кнопками редактирования."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        if person is None:
            screen = self._menu_adapter.build_profile_not_found_screen()
            return VkAdapterResponse(text=screen.text, screen=screen)

        screen = self._menu_adapter.build_profile_screen(
            phone_e164=person.phone_e164,
            accounts_count=len(person.accounts),
            accounts_platforms=self._collect_account_platforms(person.accounts),
            first_name_input=person.first_name_input,
            last_name_input=person.last_name_input,
            gender=person.gender,
            birth_date=person.birth_date,
            email=person.email,
            rules_accepted=person.get_rules_accepted_for_platform("vk"),
            rules_accepted_at=person.get_rules_accepted_at_for_platform("vk"),
            notifications_allowed=person.get_notifications_allowed_for_platform("vk"),
            notifications_allowed_at=person.get_notifications_allowed_at_for_platform("vk"),
        )
        return VkAdapterResponse(text=screen.text, screen=screen, parse_mode=screen.parse_mode)

    def _open_profile_edit_choice(self, *, vk_user_id: int) -> VkAdapterResponse:
        """Открывает меню выбора редактируемого поля профиля."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        if person is None:
            return self._render_profile_screen(vk_user_id=vk_user_id)

        self._state_by_user_id[vk_user_id] = _STATE_PROFILE_EDIT_CHOICE
        screen = self._menu_adapter.build_profile_edit_screen(can_edit_birth_date=person.birth_date is None)
        return VkAdapterResponse(text=screen.text, screen=screen, parse_mode=screen.parse_mode)

    def _handle_profile_edit_choice(
        self,
        *,
        vk_user_id: int,
        text: str,
        payload: dict[str, str] | None,
    ) -> VkAdapterResponse:
        """Обрабатывает выбор поля редактирования профиля."""

        action = resolve_action_from_vk_payload(payload) or resolve_guest_menu_action(text)
        if action in {GuestMenuAction.PROFILE_EDIT_CANCEL, GuestMenuAction.BACK_TO_MAIN}:
            self._state_by_user_id.pop(vk_user_id, None)
            return self._render_profile_screen(vk_user_id=vk_user_id)
        if action == GuestMenuAction.PROFILE_EDIT_FIRST_NAME:
            self._state_by_user_id[vk_user_id] = _STATE_PROFILE_EDIT_FIRST_NAME
            return VkAdapterResponse(text="👤 Введите новое имя текстом (от 2 до 50 символов).")
        if action == GuestMenuAction.PROFILE_EDIT_LAST_NAME:
            self._state_by_user_id[vk_user_id] = _STATE_PROFILE_EDIT_LAST_NAME
            return VkAdapterResponse(text="👥 Введите новую фамилию текстом (от 2 до 50 символов).")
        if action == GuestMenuAction.PROFILE_EDIT_GENDER:
            self._state_by_user_id[vk_user_id] = _STATE_PROFILE_EDIT_GENDER
            screen = self._menu_adapter.build_profile_gender_screen()
            return VkAdapterResponse(text=screen.text, screen=screen)
        if action == GuestMenuAction.PROFILE_EDIT_BIRTH_DATE:
            person = self._person_lookup_use_case.execute(
                GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
            )
            if person is None:
                self._state_by_user_id.pop(vk_user_id, None)
                return self._render_profile_screen(vk_user_id=vk_user_id)
            if person.birth_date is not None:
                self._state_by_user_id.pop(vk_user_id, None)
                return VkAdapterResponse(
                    text=(
                        "🎂 Дата рождения уже заполнена и может быть указана только один раз.\n\n"
                        "Телефон менять нельзя. Другие поля можно обновить в режиме редактирования профиля."
                    )
                )
            self._state_by_user_id[vk_user_id] = _STATE_PROFILE_EDIT_BIRTH_DATE
            return VkAdapterResponse(
                text="🎂 Введите дату рождения в формате ДД.ММ.ГГГГ (дата не должна быть в будущем)."
            )
        if action == GuestMenuAction.PROFILE_EDIT_EMAIL:
            self._state_by_user_id[vk_user_id] = _STATE_PROFILE_EDIT_EMAIL
            return VkAdapterResponse(text="📧 Введите новый email, например name@example.com.")
        if action == GuestMenuAction.PROFILE_EDIT_NOTIFICATIONS:
            return self._open_profile_notifications_edit(vk_user_id=vk_user_id)

        return self._open_profile_edit_choice(vk_user_id=vk_user_id)

    def _handle_profile_edit_first_name(self, *, vk_user_id: int, text: str) -> VkAdapterResponse:
        """Обрабатывает ввод имени в режиме редактирования профиля."""

        normalized = normalize_person_name(text)
        if normalized is None:
            return VkAdapterResponse(
                text=(
                    "⚠️ Не удалось сохранить имя.\n"
                    "Используйте только буквы, пробел и дефис (от 2 до 50 символов)."
                )
            )
        return self._apply_profile_patch(
            vk_user_id=vk_user_id,
            first_name_input=normalized,
            success_message="✅ Имя обновлено.\n\n",
        )

    def _handle_profile_edit_last_name(self, *, vk_user_id: int, text: str) -> VkAdapterResponse:
        """Обрабатывает ввод фамилии в режиме редактирования профиля."""

        normalized = normalize_person_name(text)
        if normalized is None:
            return VkAdapterResponse(
                text=(
                    "⚠️ Не удалось сохранить фамилию.\n"
                    "Используйте только буквы, пробел и дефис (от 2 до 50 символов)."
                )
            )
        return self._apply_profile_patch(
            vk_user_id=vk_user_id,
            last_name_input=normalized,
            success_message="✅ Фамилия обновлена.\n\n",
        )

    def _handle_profile_edit_gender(
        self,
        *,
        vk_user_id: int,
        text: str,
        payload: dict[str, str] | None,
    ) -> VkAdapterResponse:
        """Обрабатывает выбор пола в режиме редактирования профиля."""

        action = resolve_action_from_vk_payload(payload) or resolve_guest_menu_action(text)
        gender: str | None = None
        if action == GuestMenuAction.PROFILE_EDIT_GENDER_MALE:
            gender = "male"
        elif action == GuestMenuAction.PROFILE_EDIT_GENDER_FEMALE:
            gender = "female"
        else:
            lowered = normalize_menu_text(text)
            if lowered in {"мужской", "м", "male"}:
                gender = "male"
            if lowered in {"женский", "ж", "female"}:
                gender = "female"
        if gender is None:
            screen = self._menu_adapter.build_profile_gender_screen()
            return VkAdapterResponse(
                text="⚠️ Выберите пол кнопками «👨 Мужской» или «👩 Женский».",
                screen=screen,
            )
        return self._apply_profile_patch(
            vk_user_id=vk_user_id,
            gender=gender,
            success_message="✅ Пол обновлен.\n\n",
        )

    def _handle_profile_edit_birth_date(self, *, vk_user_id: int, text: str) -> VkAdapterResponse:
        """Обрабатывает ввод даты рождения в режиме редактирования профиля."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        if person is None:
            self._state_by_user_id.pop(vk_user_id, None)
            return self._render_profile_screen(vk_user_id=vk_user_id)
        if person.birth_date is not None:
            self._state_by_user_id.pop(vk_user_id, None)
            return VkAdapterResponse(
                text=(
                    "🎂 Дата рождения уже заполнена и может быть указана только один раз.\n"
                    "Если есть ошибка в данных, обратитесь к администратору."
                )
            )

        parsed = parse_birth_date(text)
        if parsed is None:
            return VkAdapterResponse(
                text=(
                    "⚠️ Некорректная дата рождения.\n"
                    "Введите дату в формате ДД.ММ.ГГГГ и убедитесь, что она не в будущем."
                )
            )
        return self._apply_profile_patch(
            vk_user_id=vk_user_id,
            birth_date=parsed,
            success_message="✅ Дата рождения сохранена.\n\n",
        )

    def _handle_profile_edit_email(self, *, vk_user_id: int, text: str) -> VkAdapterResponse:
        """Обрабатывает ввод email в режиме редактирования профиля."""

        normalized = normalize_email(text)
        if normalized is None:
            return VkAdapterResponse(text="⚠️ Укажите корректный email, например name@example.com.")
        return self._apply_profile_patch(
            vk_user_id=vk_user_id,
            email=normalized,
            success_message="✅ Email обновлен.\n\n",
        )

    def _open_profile_notifications_edit(self, *, vk_user_id: int) -> VkAdapterResponse:
        """Открывает подменю переключения уведомлений профиля."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        if person is None:
            self._state_by_user_id.pop(vk_user_id, None)
            return self._render_profile_screen(vk_user_id=vk_user_id)

        notifications_allowed = person.get_notifications_allowed_for_platform("vk")
        self._state_by_user_id[vk_user_id] = _STATE_PROFILE_EDIT_NOTIFICATIONS
        screen = self._menu_adapter.build_profile_notifications_edit_screen(
            notifications_allowed=notifications_allowed
        )
        return VkAdapterResponse(text=screen.text, screen=screen, parse_mode=screen.parse_mode)

    def _handle_profile_edit_notifications(
        self,
        *,
        vk_user_id: int,
        text: str,
        payload: dict[str, str] | None,
    ) -> VkAdapterResponse:
        """Обрабатывает переключение уведомлений в подменю профиля."""

        action = resolve_action_from_vk_payload(payload) or resolve_guest_menu_action(text)
        if action in {
            GuestMenuAction.PROFILE_NOTIFICATIONS_TOGGLE,
            GuestMenuAction.PROFILE_NOTIFICATIONS_ENABLE,
        }:
            return self._toggle_profile_notifications(
                vk_user_id=vk_user_id,
                new_value=True if action == GuestMenuAction.PROFILE_NOTIFICATIONS_ENABLE else None,
            )
        return self._open_profile_notifications_edit(vk_user_id=vk_user_id)

    def _toggle_profile_notifications(
        self,
        *,
        vk_user_id: int,
        new_value: bool | None,
    ) -> VkAdapterResponse:
        """Переключает/включает уведомления для VK-платформы в профиле."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        if person is None:
            self._state_by_user_id.pop(vk_user_id, None)
            return self._render_profile_screen(vk_user_id=vk_user_id)

        current_value = person.get_notifications_allowed_for_platform("vk")
        target_value = (not current_value) if new_value is None else new_value
        if target_value == current_value:
            self._state_by_user_id.pop(vk_user_id, None)
            profile = self._render_profile_screen(vk_user_id=vk_user_id)
            status_text = "Активны ✅" if current_value else "Отказ ❌"
            return VkAdapterResponse(text=f"ℹ️ Статус уведомлений уже: {status_text}.\n\n{profile.text}", screen=profile.screen, parse_mode=profile.parse_mode)

        fixed_at = datetime.now(timezone.utc)
        success_message = (
            "✅ Уведомления включены.\n\n"
            if target_value
            else "✅ Уведомления отключены.\n\n"
        )
        return self._apply_profile_patch(
            vk_user_id=vk_user_id,
            notifications_allowed=target_value,
            notifications_allowed_at=fixed_at,
            success_message=success_message,
        )

    def _apply_profile_patch(
        self,
        *,
        vk_user_id: int,
        success_message: str,
        first_name_input: str | None = None,
        last_name_input: str | None = None,
        gender: str | None = None,
        birth_date: date | None = None,
        email: str | None = None,
        notifications_allowed: bool | None = None,
        notifications_allowed_at: datetime | None = None,
    ) -> VkAdapterResponse:
        """Применяет частичное обновление профиля через общий registration use-case."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        if person is None:
            self._state_by_user_id.pop(vk_user_id, None)
            return self._render_profile_screen(vk_user_id=vk_user_id)
        try:
            self._registration_use_case.execute(
                RegisterOrAttachAccountCommand(
                    platform="vk",
                    external_id=str(vk_user_id),
                    raw_phone=person.phone_e164,
                    is_registered=True,
                    first_name_input=first_name_input,
                    last_name_input=last_name_input,
                    gender=gender,
                    birth_date=birth_date,
                    email=email,
                    notifications_allowed=notifications_allowed,
                    notifications_allowed_at=notifications_allowed_at,
                )
            )
        except (IdentityConflictError, ValueError):
            return VkAdapterResponse(
                text=(
                    "❌ Не удалось сохранить изменения профиля.\n"
                    "Попробуйте ещё раз чуть позже."
                )
            )

        self._enqueue_profile_sync_for_person(
            person_id=person.person_id,
            source_platform="vk",
        )
        self._state_by_user_id.pop(vk_user_id, None)
        profile = self._render_profile_screen(vk_user_id=vk_user_id)
        return VkAdapterResponse(
            text=f"{success_message}{profile.text}",
            screen=profile.screen,
            parse_mode=profile.parse_mode,
        )

    def _enqueue_profile_sync_for_person(
        self,
        *,
        person_id: UUID,
        source_platform: PlatformName,
    ) -> None:
        """Ставит профиль пользователя в очередь sync после успешного редактирования."""

        if self._enqueue_profile_sync_use_case is None:
            return

        try:
            self._enqueue_profile_sync_use_case.execute(
                EnqueueProfileSyncCommand(
                    person_id=person_id,
                    source_platform=source_platform,
                    payload_json={"trigger": "profile_edit"},
                )
            )
        except Exception as error:  # noqa: BLE001
            self._logger.bind(stage="profile_sync_enqueue", user_id=str(person_id)).warning(
                "Не удалось поставить профиль в очередь синхронизации с iiko. reason={reason}.",
                reason=str(error),
            )

    def _try_handle_moderator_command(
        self,
        *,
        text: str,
        vk_user_id: int,
    ) -> VkAdapterResponse | None:
        """Пытается обработать команду модератора."""

        raw = (text or "").strip()
        lowered = raw.lower()
        if lowered == "/mod":
            return self._open_moderator_menu(vk_user_id=vk_user_id)
        return None

    def _try_handle_moderation_payload(
        self,
        *,
        vk_user_id: int,
        payload: dict[str, str] | None,
    ) -> VkAdapterResponse | None:
        """Пытается обработать callback-навигацию модератора по payload."""

        if not isinstance(payload, dict):
            return None
        cmd = str(payload.get("cmd", "")).strip()
        if not cmd.startswith("mod_"):
            return None

        if cmd == MOD_MAIN_CALLBACK:
            return self._open_moderator_menu(vk_user_id=vk_user_id)

        if not self._is_moderator_account(vk_user_id=vk_user_id):
            self._clear_moderator_state(vk_user_id)
            return VkAdapterResponse(text="Команда /mod доступна только модераторам.")

        if (
            self._moderator_reply_use_case is None
            or self._ticket_details_use_case is None
            or self._list_open_tickets_use_case is None
        ):
            return VkAdapterResponse(
                text="Меню модератора недоступно: не подключены сценарии модерации."
            )

        if cmd.startswith(MOD_LIST_PREFIX):
            filter_key = self._normalize_moderation_filter(cmd[len(MOD_LIST_PREFIX):])
            return self._show_moderation_tickets_page(
                vk_user_id=vk_user_id,
                filter_key=filter_key,
                page=1,
            )

        if cmd.startswith(MOD_PAGE_PREFIX):
            parsed = self._parse_moderation_page_payload(cmd[len(MOD_PAGE_PREFIX):])
            if parsed is None:
                return self._show_moderation_tickets_page(
                    vk_user_id=vk_user_id,
                    filter_key=_MOD_FILTER_NEW,
                    page=1,
                )
            filter_key, page = parsed
            return self._show_moderation_tickets_page(
                vk_user_id=vk_user_id,
                filter_key=filter_key,
                page=page,
            )

        parsed_details = self._parse_moderation_ticket_payload(cmd, MOD_TICKET_PREFIX)
        if parsed_details is not None:
            ticket_id, filter_key, page = parsed_details
            return self._build_moderation_ticket_details_response(
                vk_user_id=vk_user_id,
                ticket_id=ticket_id,
                filter_key=filter_key,
                page=page,
            )

        parsed_reply = self._parse_moderation_ticket_payload(cmd, MOD_REPLY_PREFIX)
        if parsed_reply is not None:
            ticket_id, filter_key, page = parsed_reply
            return self._start_moderation_reply_from_payload(
                vk_user_id=vk_user_id,
                ticket_id=ticket_id,
                filter_key=filter_key,
                page=page,
            )

        parsed_take = self._parse_moderation_ticket_payload(cmd, MOD_TAKE_PREFIX)
        if parsed_take is not None:
            ticket_id, filter_key, page = parsed_take
            return self._set_moderation_status_from_payload(
                vk_user_id=vk_user_id,
                ticket_id=ticket_id,
                new_status=SupportTicketStatus.IN_PROGRESS,
                filter_key=filter_key,
                page=page,
            )

        parsed_close = self._parse_moderation_ticket_payload(cmd, MOD_CLOSE_PREFIX)
        if parsed_close is not None:
            ticket_id, filter_key, page = parsed_close
            return self._set_moderation_status_from_payload(
                vk_user_id=vk_user_id,
                ticket_id=ticket_id,
                new_status=SupportTicketStatus.CLOSED,
                filter_key=filter_key,
                page=page,
            )

        return VkAdapterResponse(text="Не удалось распознать действие меню модератора.")

    @staticmethod
    def _normalize_moderation_filter(raw_filter: str) -> str:
        """Нормализует фильтр обращения в модераторском меню."""

        normalized = (raw_filter or "").strip().lower()
        if normalized in _MOD_FILTER_ORDER:
            return normalized
        return _MOD_FILTER_NEW

    def _parse_moderation_page_payload(self, raw_payload: str) -> tuple[str, int] | None:
        """Разбирает payload вида `mod_page_<filter>_<page>`."""

        payload = (raw_payload or "").strip()
        if not payload or "_" not in payload:
            return None
        filter_raw, page_raw = payload.rsplit("_", maxsplit=1)
        filter_key = self._normalize_moderation_filter(filter_raw)
        try:
            page = max(int(page_raw), 1)
        except ValueError:
            return None
        return filter_key, page

    def _parse_moderation_ticket_payload(
        self,
        raw_cmd: str,
        prefix: str,
    ) -> tuple[UUID, str, int] | None:
        """Разбирает payload вида `<prefix><uuid>_<filter>_<page>`."""

        if not raw_cmd.startswith(prefix):
            return None
        suffix = raw_cmd[len(prefix):].strip()
        parts = suffix.rsplit("_", maxsplit=2)
        if len(parts) != 3:
            return None
        raw_ticket_id, raw_filter, raw_page = parts
        try:
            ticket_id = UUID(raw_ticket_id)
        except ValueError:
            return None
        filter_key = self._normalize_moderation_filter(raw_filter)
        try:
            page = max(int(raw_page), 1)
        except ValueError:
            page = 1
        return ticket_id, filter_key, page

    def _show_moderation_tickets_page(
        self,
        *,
        vk_user_id: int,
        filter_key: str,
        page: int,
        per_page: int = 4,
    ) -> VkAdapterResponse:
        """Показывает страницу списка тикетов модератора."""

        if self._list_open_tickets_use_case is None:
            return VkAdapterResponse(text="Список обращений недоступен: list-open-use-case не подключен.")

        normalized_filter = self._normalize_moderation_filter(filter_key)
        all_tickets = self._list_open_tickets_use_case.execute(
            statuses=_MOD_FILTER_TO_STATUSES[normalized_filter],
            limit=200,
        )
        total_items = len(all_tickets)
        safe_per_page = max(int(per_page), 1)
        total_pages = max((total_items + safe_per_page - 1) // safe_per_page, 1)
        safe_page = min(max(int(page), 1), total_pages)
        start_index = (safe_page - 1) * safe_per_page
        end_index = start_index + safe_per_page
        page_tickets = tuple(all_tickets[start_index:end_index])

        title = _MOD_FILTER_TITLES[normalized_filter]
        if total_items == 0:
            text = f"{title}:\nСейчас обращений в этой категории нет."
        else:
            lines = [f"{title}:"]
            for index, ticket in enumerate(page_tickets, start=1):
                status_emoji, status_text = self._format_ticket_status(ticket.status.value)
                created = ticket.created_at.strftime("%d.%m.%Y %H:%M") if ticket.created_at else "—"
                lines.append(
                    f"{index}. {status_emoji} #{self._format_ticket_id_short(ticket.ticket_id)}"
                    f" • {status_text} • {self._format_platform_label(ticket.source_platform)} • {created}"
                )
            lines.append("")
            lines.append(f"Страница {safe_page}/{total_pages}. Всего обращений: {total_items}.")
            text = "\n".join(lines)

        self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id[vk_user_id] = {
            "filter": normalized_filter,
            "page": str(safe_page),
        }
        return VkAdapterResponse(
            text=text,
            screen=self._menu_adapter.build_moderation_tickets_screen(
                filter_key=normalized_filter,
                current_page=safe_page,
                total_pages=total_pages,
                tickets=page_tickets,
            ),
        )

    def _build_moderation_ticket_details_response(
        self,
        *,
        vk_user_id: int,
        ticket_id: UUID,
        filter_key: str,
        page: int,
    ) -> VkAdapterResponse:
        """Формирует карточку тикета модератора для callback-навигации."""

        try:
            details, messages = self._get_ticket_details_with_history(ticket_id)
        except ValueError as error:
            return VkAdapterResponse(text=f"Не удалось загрузить тикет: {error}")

        status_value = getattr(details.status, "value", str(details.status))
        message_lines = self._build_moderation_ticket_card_lines(
            details=details,
            messages=messages,
        )
        normalized_filter = self._normalize_moderation_filter(filter_key)
        safe_page = max(int(page), 1)
        self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id[vk_user_id] = {
            "filter": normalized_filter,
            "page": str(safe_page),
        }
        return VkAdapterResponse(
            text="\n".join(message_lines),
            screen=self._menu_adapter.build_moderation_ticket_details_screen(
                ticket_id=str(details.ticket_id),
                filter_key=normalized_filter,
                page=safe_page,
                status_value=status_value,
            ),
        )

    def _start_moderation_reply_from_payload(
        self,
        *,
        vk_user_id: int,
        ticket_id: UUID,
        filter_key: str,
        page: int,
    ) -> VkAdapterResponse:
        """Переводит модератора в режим ввода ответа по callback из карточки тикета."""

        if self._ticket_details_use_case is None:
            return VkAdapterResponse(text="Карточка тикета недоступна: details-use-case не подключен.")
        try:
            self._ticket_details_use_case.execute(ticket_id)
        except ValueError as error:
            return VkAdapterResponse(text=f"Не удалось найти тикет: {error}")

        self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_WAIT_REPLY_TEXT
        self._moderator_context_by_user_id[vk_user_id] = {
            "ticket_id": str(ticket_id),
            "filter": self._normalize_moderation_filter(filter_key),
            "page": str(max(int(page), 1)),
        }
        return VkAdapterResponse(
            text=(
                "Введите текст ответа модератора.\n"
                "Отправьте ответ одним сообщением."
            ),
            screen=self._menu_adapter.build_moderation_reply_cancel_screen(),
        )

    def _set_moderation_status_from_payload(
        self,
        *,
        vk_user_id: int,
        ticket_id: UUID,
        new_status: SupportTicketStatus,
        filter_key: str,
        page: int,
    ) -> VkAdapterResponse:
        """Меняет статус тикета из callback-кнопки карточки."""

        if self._set_ticket_status_use_case is None:
            return VkAdapterResponse(text="Изменение статуса тикета временно недоступно.")
        try:
            result = self._set_ticket_status_use_case.execute(
                SetSupportTicketStatusCommand(
                    ticket_id=ticket_id,
                    status=new_status,
                )
            )
        except ValueError as error:
            return VkAdapterResponse(text=f"Не удалось изменить статус тикета: {error}")

        details_response = self._build_moderation_ticket_details_response(
            vk_user_id=vk_user_id,
            ticket_id=result.ticket_id,
            filter_key=filter_key,
            page=page,
        )
        _, previous_status_text = self._format_ticket_status(result.previous_status.value)
        _, new_status_text = self._format_ticket_status(result.new_status.value)
        return VkAdapterResponse(
            text=(
                f"✅ Статус обновлен: {previous_status_text} → {new_status_text}.\n\n"
                f"{details_response.text}"
            ),
            screen=details_response.screen,
            parse_mode=details_response.parse_mode,
        )

    def _open_moderator_menu(self, *, vk_user_id: int) -> VkAdapterResponse:
        """Открывает единое меню модератора."""

        if not self._is_moderator_account(vk_user_id=vk_user_id):
            self._clear_moderator_state(vk_user_id)
            return VkAdapterResponse(text="Команда /mod доступна только модераторам.")

        if self._moderator_reply_use_case is None or self._ticket_details_use_case is None:
            return VkAdapterResponse(
                text="Меню модератора недоступно: не подключены сценарии модерации."
            )

        self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id[vk_user_id] = {
            "filter": _MOD_FILTER_NEW,
            "page": "1",
        }
        return VkAdapterResponse(
            text=self._build_moderation_menu_text(),
            screen=self._menu_adapter.build_moderation_main_screen(),
        )

    def _handle_moderator_state_input(self, *, vk_user_id: int, text: str) -> VkAdapterResponse:
        """Обрабатывает ввод модератора внутри FSM-режима."""

        state = self._moderator_state_by_user_id.get(vk_user_id)
        if state is None:
            return VkAdapterResponse(
                text=self._build_moderation_menu_text(),
                screen=self._menu_adapter.build_moderation_main_screen(),
            )

        raw = (text or "").strip()
        lowered = raw.lower()

        if lowered in {"отмена", "/cancel", "/mod", "меню"}:
            self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_MENU
            self._moderator_context_by_user_id[vk_user_id] = {
                "filter": _MOD_FILTER_NEW,
                "page": "1",
            }
            return VkAdapterResponse(
                text=self._build_moderation_menu_text(),
                screen=self._menu_adapter.build_moderation_main_screen(),
            )

        if lowered in {"выход", "0"}:
            self._clear_moderator_state(vk_user_id)
            return VkAdapterResponse(
                text="Режим модератора завершен. Для повторного входа используйте /mod."
            )

        if state == _STATE_MOD_MENU:
            return self._handle_moderator_menu_choice(vk_user_id=vk_user_id, lowered_text=lowered)

        if state == _STATE_MOD_WAIT_TICKET_FOR_REPLY:
            return self._handle_moderator_wait_ticket_for_reply(
                vk_user_id=vk_user_id,
                raw_ticket_id=raw,
            )

        if state == _STATE_MOD_WAIT_REPLY_TEXT:
            return self._handle_moderator_wait_reply_text(vk_user_id=vk_user_id, raw_message=raw)

        if state == _STATE_MOD_WAIT_TICKET_FOR_DETAILS:
            return self._handle_moderator_wait_ticket_for_details(
                vk_user_id=vk_user_id,
                raw_ticket_id=raw,
            )
        if state == _STATE_MOD_WAIT_TICKET_FOR_CLOSE:
            return self._handle_moderator_wait_ticket_for_status_change(
                vk_user_id=vk_user_id,
                raw_ticket_id=raw,
                new_status=SupportTicketStatus.CLOSED,
            )
        if state == _STATE_MOD_WAIT_TICKET_FOR_IN_PROGRESS:
            return self._handle_moderator_wait_ticket_for_status_change(
                vk_user_id=vk_user_id,
                raw_ticket_id=raw,
                new_status=SupportTicketStatus.IN_PROGRESS,
            )

        self._clear_moderator_state(vk_user_id)
        return VkAdapterResponse(
            text="Состояние модератора сброшено. Откройте меню заново через /mod."
        )

    def _handle_moderator_menu_choice(self, *, vk_user_id: int, lowered_text: str) -> VkAdapterResponse:
        """Обрабатывает выбор пункта главного меню модератора."""

        if lowered_text in {"1", "тикеты", "список"}:
            return self._show_moderation_tickets_page(
                vk_user_id=vk_user_id,
                filter_key=_MOD_FILTER_NEW,
                page=1,
            )

        if lowered_text in {"2", "ответ", "ответить"}:
            self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_WAIT_TICKET_FOR_REPLY
            self._moderator_context_by_user_id.pop(vk_user_id, None)
            return VkAdapterResponse(
                text=(
                    "Введите UUID тикета, для которого нужно отправить ответ.\n"
                    "Для отмены отправьте «Отмена»."
                )
            )

        if lowered_text in {"3", "карточка", "детали"}:
            self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_WAIT_TICKET_FOR_DETAILS
            self._moderator_context_by_user_id.pop(vk_user_id, None)
            return VkAdapterResponse(
                text=(
                    "Введите UUID тикета, чтобы показать карточку обращения.\n"
                    "Для отмены отправьте «Отмена»."
                )
            )

        if lowered_text in {"4", "в работе", "работа", "активные"}:
            return self._show_moderation_tickets_page(
                vk_user_id=vk_user_id,
                filter_key=_MOD_FILTER_WORK,
                page=1,
            )

        if lowered_text in {"5", "закрытые", "архив"}:
            return self._show_moderation_tickets_page(
                vk_user_id=vk_user_id,
                filter_key=_MOD_FILTER_CLOSED,
                page=1,
            )

        if lowered_text in {"6", "закрыть", "close"}:
            self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_WAIT_TICKET_FOR_CLOSE
            self._moderator_context_by_user_id.pop(vk_user_id, None)
            return VkAdapterResponse(
                text=(
                    "Введите UUID тикета, который нужно закрыть.\n"
                    "Для отмены отправьте «Отмена»."
                )
            )

        if lowered_text in {"7", "вработу", "в_работу", "take"}:
            self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_WAIT_TICKET_FOR_IN_PROGRESS
            self._moderator_context_by_user_id.pop(vk_user_id, None)
            return VkAdapterResponse(
                text=(
                    "Введите UUID тикета, который нужно перевести в статус «В работе».\n"
                    "Для отмены отправьте «Отмена»."
                )
            )

        return VkAdapterResponse(
            text=(
                "Не удалось распознать пункт меню модератора.\n"
                f"{self._build_moderation_menu_text()}"
            )
        )

    def _handle_moderator_wait_ticket_for_reply(
        self,
        *,
        vk_user_id: int,
        raw_ticket_id: str,
    ) -> VkAdapterResponse:
        """Обрабатывает ввод ticket_id перед отправкой модераторского ответа."""

        ticket_id = self._parse_ticket_id(raw_ticket_id)
        if ticket_id is None:
            return VkAdapterResponse(text="Некорректный ticket_id. Ожидается UUID.")

        if self._ticket_details_use_case is None:
            return VkAdapterResponse(
                text="Меню модератора недоступно: details-use-case не подключен."
            )

        try:
            self._ticket_details_use_case.execute(ticket_id)
        except ValueError as error:
            return VkAdapterResponse(text=f"Не удалось найти тикет: {error}")

        self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_WAIT_REPLY_TEXT
        self._moderator_context_by_user_id[vk_user_id] = {"ticket_id": str(ticket_id)}
        return VkAdapterResponse(
            text=(
                "Введите текст ответа модератора.\n"
                "Отправьте ответ одним сообщением."
            ),
            screen=self._menu_adapter.build_moderation_reply_cancel_screen(),
        )

    def _handle_moderator_wait_reply_text(self, *, vk_user_id: int, raw_message: str) -> VkAdapterResponse:
        """Обрабатывает ввод текста ответа модератора в FSM-режиме."""

        context = self._moderator_context_by_user_id.get(vk_user_id, {})
        raw_ticket_id = context.get("ticket_id")
        if raw_ticket_id is None:
            self._clear_moderator_state(vk_user_id)
            return VkAdapterResponse(
                text="Потерян ticket_id в состоянии модератора. Откройте /mod заново."
            )

        parsed = self._parse_target_and_reply_text(raw_message)
        if parsed is None:
            return VkAdapterResponse(
                text="Текст ответа модератора не может быть пустым.",
                screen=self._menu_adapter.build_moderation_reply_cancel_screen(),
            )
        preferred_target, message_text = parsed
        if preferred_target is not None and preferred_target not in SUPPORTED_PLATFORMS:
            return VkAdapterResponse(
                text="Недопустимая целевая платформа в --to.",
                screen=self._menu_adapter.build_moderation_reply_cancel_screen(),
            )

        if self._moderator_reply_use_case is None:
            return VkAdapterResponse(
                text="Маршрутизация ответа модератора пока недоступна.",
                screen=self._menu_adapter.build_moderation_reply_cancel_screen(),
            )

        try:
            route = self._moderator_reply_use_case.execute(
                ModeratorReplyCommand(
                    ticket_id=UUID(raw_ticket_id),
                    moderator_platform="vk",
                    reply_text=message_text,
                    preferred_target_platform=preferred_target,  # type: ignore[arg-type]
                )
            )
        except ValueError as error:
            return VkAdapterResponse(
                text=f"Не удалось маршрутизировать ответ: {error}",
                screen=self._menu_adapter.build_moderation_reply_cancel_screen(),
            )

        filter_key = self._normalize_moderation_filter(context.get("filter", _MOD_FILTER_NEW))
        try:
            page = max(int(context.get("page", "1")), 1)
        except ValueError:
            page = 1
        self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id.pop(vk_user_id, None)
        details_response = self._build_moderation_ticket_details_response(
            vk_user_id=vk_user_id,
            ticket_id=route.ticket_id,
            filter_key=filter_key,
            page=page,
        )
        if details_response.screen is not None:
            return VkAdapterResponse(
                text=(
                    "Ответ модератора зарегистрирован.\n"
                    f"Маршрут доставки: {self._format_platform_label(route.target_platform)} ({route.target_external_id})\n\n"
                    f"{details_response.text}"
                ),
                screen=details_response.screen,
                parse_mode=details_response.parse_mode,
            )
        return VkAdapterResponse(
            text=(
                "Ответ модератора зарегистрирован.\n"
                f"Тикет: {route.ticket_id}\n"
                f"Канал исходного обращения: {self._format_platform_label(route.guest_source_platform)}\n"
                f"Маршрут доставки: {self._format_platform_label(route.target_platform)} ({route.target_external_id})\n"
                f"ID сообщения: {route.message_id}\n\n"
                f"{self._build_moderation_menu_text()}"
            )
        )

    def _handle_moderator_wait_ticket_for_details(
        self,
        *,
        vk_user_id: int,
        raw_ticket_id: str,
    ) -> VkAdapterResponse:
        """Обрабатывает ввод ticket_id для показа карточки тикета."""

        ticket_id = self._parse_ticket_id(raw_ticket_id)
        if ticket_id is None:
            return VkAdapterResponse(text="Некорректный ticket_id. Ожидается UUID.")

        if self._ticket_details_use_case is None:
            return VkAdapterResponse(
                text="Команда карточки тикета пока недоступна: details-use-case не подключен."
            )

        try:
            details, messages = self._get_ticket_details_with_history(ticket_id)
        except ValueError as error:
            return VkAdapterResponse(text=f"Не удалось загрузить тикет: {error}")

        self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id.pop(vk_user_id, None)
        message_lines = self._build_moderation_ticket_card_lines(
            details=details,
            messages=messages,
        )
        message_lines.extend(["", self._build_moderation_menu_text()])
        return VkAdapterResponse(
            text="\n".join(message_lines)
        )

    def _handle_moderator_wait_ticket_for_status_change(
        self,
        *,
        vk_user_id: int,
        raw_ticket_id: str,
        new_status: SupportTicketStatus,
    ) -> VkAdapterResponse:
        """Обрабатывает ввод ticket_id для смены статуса тикета."""

        ticket_id = self._parse_ticket_id(raw_ticket_id)
        if ticket_id is None:
            return VkAdapterResponse(text="Некорректный ticket_id. Ожидается UUID.")

        if self._set_ticket_status_use_case is None:
            return VkAdapterResponse(text="Изменение статуса тикета временно недоступно.")

        try:
            result = self._set_ticket_status_use_case.execute(
                SetSupportTicketStatusCommand(
                    ticket_id=ticket_id,
                    status=new_status,
                )
            )
        except ValueError as error:
            return VkAdapterResponse(text=f"Не удалось изменить статус тикета: {error}")

        self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id.pop(vk_user_id, None)
        _, previous_status_text = self._format_ticket_status(result.previous_status.value)
        _, new_status_text = self._format_ticket_status(result.new_status.value)
        short_id = self._format_ticket_id_short(result.ticket_id)
        return VkAdapterResponse(
            text=(
                f"✅ Статус тикета #{short_id} обновлен: {previous_status_text} → {new_status_text}.\n\n"
                f"{self._build_moderation_menu_text()}"
            )
        )

    def _build_tickets_text_by_status(
        self,
        *,
        title: str,
        statuses: tuple[SupportTicketStatus, ...],
        limit: int,
    ) -> str:
        """Формирует текст тикетов по выбранным статусам для меню модератора."""

        if self._list_open_tickets_use_case is None:
            return "Список тикетов недоступен: list-open-use-case не подключен."

        tickets = self._list_open_tickets_use_case.execute(limit=limit, statuses=statuses)
        if not tickets:
            return f"{title}\nСейчас обращений в этой категории нет."

        lines = [title]
        for index, ticket in enumerate(tickets, start=1):
            status_emoji, status_text = self._format_ticket_status(ticket.status.value)
            short_id = self._format_ticket_id_short(ticket.ticket_id)
            lines.append(
                f"{index}. {status_emoji} #{short_id} | "
                f"канал={self._format_platform_label(ticket.source_platform)} | "
                f"последний={self._format_platform_label(ticket.last_guest_platform)} | "
                f"статус={status_text}"
            )
        return "\n".join(lines)

    @staticmethod
    def _build_moderation_menu_text() -> str:
        """Возвращает текст главного меню модератора."""

        return (
            "🛠 Меню модератора\n"
            "Используйте кнопки ниже, чтобы открыть список обращений:\n"
            "• 🆕 Новые\n"
            "• 🛠 В работе\n"
            "• ✅ Закрытые\n"
            "• 📚 Все"
        )

    @staticmethod
    def _parse_target_and_reply_text(raw_message: str) -> tuple[str | None, str] | None:
        """Разбирает optional `--to=` и текст ответа модератора."""

        raw = str(raw_message).strip()
        if not raw:
            return None

        parts = raw.split()
        preferred_target: str | None = None
        if parts and parts[0].lower().startswith("--to="):
            preferred_target = parts[0].split("=", maxsplit=1)[1].strip().lower()
            message_text = " ".join(parts[1:]).strip()
        else:
            message_text = raw

        if not message_text:
            return None
        return preferred_target, message_text

    def _handle_modreply_command(self, raw: str) -> VkAdapterResponse:
        """Обрабатывает команду модератора `/modreply`."""

        if self._moderator_reply_use_case is None:
            return VkAdapterResponse(
                text=(
                    "Команда модерации пока недоступна: сценарий маршрутизации не подключен.\n"
                    "Обратитесь к администратору проекта."
                )
            )

        parts = raw.split()
        if len(parts) < 3:
            return VkAdapterResponse(
                text=(
                    "Формат: /modreply <ticket_id> [--to=telegram|vk|max] <текст ответа>"
                )
            )

        ticket_id = self._parse_ticket_id(parts[1])
        if ticket_id is None:
            return VkAdapterResponse(text="Некорректный ticket_id. Ожидается UUID.")

        preferred_target: str | None = None
        message_start_index = 2
        if len(parts) >= 4 and parts[2].lower().startswith("--to="):
            preferred_target = parts[2].split("=", maxsplit=1)[1].strip().lower()
            message_start_index = 3

        message_text = " ".join(parts[message_start_index:]).strip()
        if not message_text:
            return VkAdapterResponse(text="Текст ответа модератора не может быть пустым.")

        if preferred_target is not None and preferred_target not in SUPPORTED_PLATFORMS:
            return VkAdapterResponse(text="Недопустимая целевая платформа в --to.")

        try:
            route = self._moderator_reply_use_case.execute(
                ModeratorReplyCommand(
                    ticket_id=ticket_id,
                    moderator_platform="vk",
                    reply_text=message_text,
                    preferred_target_platform=preferred_target,  # type: ignore[arg-type]
                )
            )
        except ValueError as error:
            return VkAdapterResponse(text=f"Не удалось маршрутизировать ответ: {error}")

        return VkAdapterResponse(
            text=(
                "Ответ модератора зарегистрирован.\n"
                f"Тикет: {route.ticket_id}\n"
                f"Канал исходного обращения: {self._format_platform_label(route.guest_source_platform)}\n"
                f"Маршрут доставки: {self._format_platform_label(route.target_platform)} ({route.target_external_id})\n"
                f"ID сообщения: {route.message_id}"
            )
        )

    def _handle_modticket_command(self, raw: str) -> VkAdapterResponse:
        """Обрабатывает команду модератора `/modticket`."""

        if self._ticket_details_use_case is None:
            return VkAdapterResponse(
                text=(
                    "Команда карточки тикета пока недоступна: details-use-case не подключен."
                )
            )

        parts = raw.split()
        if len(parts) != 2:
            return VkAdapterResponse(text="Формат: /modticket <ticket_id>")

        ticket_id = self._parse_ticket_id(parts[1])
        if ticket_id is None:
            return VkAdapterResponse(text="Некорректный ticket_id. Ожидается UUID.")

        try:
            details = self._ticket_details_use_case.execute(ticket_id)
        except ValueError as error:
            return VkAdapterResponse(text=f"Не удалось загрузить тикет: {error}")

        linked = ", ".join(self._format_platform_label(platform) for platform in details.linked_platforms)
        return VkAdapterResponse(
            text=(
                f"Тикет: {details.ticket_id}\n"
                f"Статус: {details.status}\n"
                f"Канал создания: {self._format_platform_label(details.source_platform)}\n"
                f"Последний канал гостя: {self._format_platform_label(details.last_guest_platform)}\n"
                f"Каналы гостя: {linked}"
            )
        )

    @staticmethod
    def _parse_ticket_id(raw_ticket_id: str) -> UUID | None:
        try:
            return UUID(raw_ticket_id)
        except ValueError:
            return None

    def _clear_moderator_state(self, vk_user_id: int) -> None:
        """Очищает модераторское FSM-состояние пользователя."""

        self._moderator_state_by_user_id.pop(vk_user_id, None)
        self._moderator_context_by_user_id.pop(vk_user_id, None)

    def _is_moderator_account(self, *, vk_user_id: int) -> bool:
        """Проверяет признак модератора по профилю strict identity в БД."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(
                platform="vk",
                external_id=str(vk_user_id),
            )
        )
        if person is None:
            return False
        return bool(getattr(person, "is_moderator", False))

    def _resolve_menu_user_name(self, *, vk_user_id: int, person: object | None = None) -> str:
        """Возвращает имя для приветствия в главном меню."""

        resolved_person = person
        if resolved_person is None:
            resolved_person = self._person_lookup_use_case.execute(
                GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
            )
        first_name = getattr(resolved_person, "first_name_input", None)
        if isinstance(first_name, str):
            normalized = first_name.strip()
            if normalized:
                return normalized
        return "Гость"

    def _handle_action(self, vk_user_id: int, action: GuestMenuAction) -> VkAdapterResponse:
        """Обрабатывает пункт меню для зарегистрированного пользователя."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        menu_user_name = self._resolve_menu_user_name(vk_user_id=vk_user_id, person=person)

        if person is None and action not in {
            GuestMenuAction.MAIN_MENU,
            GuestMenuAction.SHARE_CONTACT,
            GuestMenuAction.ACCEPT_RULES,
        }:
            self._state_by_user_id[vk_user_id] = _STATE_WAITING_RULES_CONSENT
            rules_screen = self._menu_adapter.build_start_rules_screen()
            return VkAdapterResponse(
                text=(
                    "Раздел доступен после регистрации. Сначала подтвердите согласие с правилами.\n\n"
                    f"{rules_screen.text}"
                ),
                screen=rules_screen,
            )

        if action == GuestMenuAction.ACCEPT_RULES:
            self._state_by_user_id[vk_user_id] = _STATE_WAITING_RULES_CONSENT
            return self._handle_rules_consent(
                vk_user_id=vk_user_id,
                text=BUTTON_ACCEPT_RULES,
                payload={"cmd": GuestMenuAction.ACCEPT_RULES.value},
            )

        if action == GuestMenuAction.SHARE_CONTACT:
            if person is None:
                self._state_by_user_id[vk_user_id] = _STATE_WAITING_PHONE
            else:
                self._state_by_user_id[vk_user_id] = _STATE_WAITING_LEGACY_PHONE
            contact_screen = self._menu_adapter.build_start_contact_screen()
            return VkAdapterResponse(text=contact_screen.text, screen=contact_screen)

        if action == GuestMenuAction.PROFILE:
            self._state_by_user_id.pop(vk_user_id, None)
            return self._render_profile_screen(vk_user_id=vk_user_id)

        if action == GuestMenuAction.PROFILE_EDIT:
            return self._open_profile_edit_choice(vk_user_id=vk_user_id)

        if action == GuestMenuAction.PROFILE_EDIT_NOTIFICATIONS:
            return self._open_profile_notifications_edit(vk_user_id=vk_user_id)

        if action == GuestMenuAction.PROFILE_NOTIFICATIONS_ENABLE:
            return self._toggle_profile_notifications(vk_user_id=vk_user_id, new_value=True)

        if action == GuestMenuAction.PROFILE_NOTIFICATIONS_TOGGLE:
            return self._toggle_profile_notifications(vk_user_id=vk_user_id, new_value=None)

        if action == GuestMenuAction.PROFILE_EDIT_CANCEL:
            self._state_by_user_id.pop(vk_user_id, None)
            return self._render_profile_screen(vk_user_id=vk_user_id)

        if action in {
            GuestMenuAction.PROFILE_EDIT_FIRST_NAME,
            GuestMenuAction.PROFILE_EDIT_LAST_NAME,
            GuestMenuAction.PROFILE_EDIT_GENDER,
            GuestMenuAction.PROFILE_EDIT_BIRTH_DATE,
            GuestMenuAction.PROFILE_EDIT_EMAIL,
            GuestMenuAction.PROFILE_EDIT_NOTIFICATIONS,
            GuestMenuAction.PROFILE_EDIT_GENDER_MALE,
            GuestMenuAction.PROFILE_EDIT_GENDER_FEMALE,
        }:
            return self._open_profile_edit_choice(vk_user_id=vk_user_id)

        if action == GuestMenuAction.BALANCE:
            return self._handle_balance_action(
                vk_user_id=vk_user_id,
                person_phone_e164=person.phone_e164,
            )

        if action == GuestMenuAction.VIRTUAL_CARD:
            return self._handle_virtual_card_action(
                vk_user_id=vk_user_id,
                person_phone_e164=person.phone_e164,
            )

        if action == GuestMenuAction.MY_TICKETS:
            # Показываем первую страницу тикетов с пагинацией
            return self._show_user_tickets_page(vk_user_id=vk_user_id, page=1, per_page=3)

        if action == GuestMenuAction.SUPPORT_QUESTION:
            has_tickets = self._has_user_tickets(platform="vk", external_id=str(vk_user_id))
            if has_tickets:
                # Показываем первую страницу тикетов с пагинацией
                return self._show_user_tickets_page(vk_user_id=vk_user_id, page=1, per_page=5)
            # тикетов нет — переходим в состояние ожидания вопроса
            self._state_by_user_id[vk_user_id] = _STATE_WAITING_SUPPORT_QUESTION
            self._reply_ticket_id_by_user_id.pop(vk_user_id, None)
            screen = self._menu_adapter.build_support_question_screen()
            return VkAdapterResponse(text=screen.text, screen=screen)

        if action == GuestMenuAction.SUPPORT_QUESTION_FROM_LIST:
            # Всегда переходим к созданию нового тикета, независимо от наличия тикетов
            self._state_by_user_id[vk_user_id] = _STATE_WAITING_SUPPORT_QUESTION
            self._reply_ticket_id_by_user_id.pop(vk_user_id, None)
            screen = self._menu_adapter.build_support_question_screen()
            return VkAdapterResponse(text=screen.text, screen=screen)

        if action == GuestMenuAction.MAIN_MENU:
            screen = self._menu_adapter.build_main_menu_screen(user_name=menu_user_name)
            return VkAdapterResponse(text=screen.text, screen=screen)

        has_tickets = self._has_user_tickets(platform="vk", external_id=str(vk_user_id))
        screen = self._menu_adapter.resolve_action_screen(
            action,
            user_name=menu_user_name,
            has_tickets=has_tickets,
        )
        return VkAdapterResponse(text=screen.text, screen=screen)

    def _handle_balance_action(self, *, vk_user_id: int, person_phone_e164: str) -> VkAdapterResponse:
        """Обрабатывает пункт меню «Мой баланс» через общий use-case лояльности."""

        balance_screen = self._menu_adapter.build_balance_screen(balance=0.0)
        if self._balance_use_case is None:
            error_message = (
                "❌ Сервис бонусов временно недоступен.\n"
                "Код ошибки: IIKO-BAL-000.\n"
                "Покажите это сообщение сотруднику и попробуйте позже."
            )
            self._create_external_error_ticket_for_guest(
                vk_user_id=vk_user_id,
                guest_error_message=error_message,
            )
            return VkAdapterResponse(
                text=error_message,
                screen=balance_screen,
            )

        result = self._balance_use_case.execute(phone_e164=person_phone_e164)
        if result.status == "balance_unavailable":
            self._create_external_error_ticket_for_guest(
                vk_user_id=vk_user_id,
                guest_error_message=result.message,
            )
        return VkAdapterResponse(
            text=result.message,
            screen=balance_screen,
            parse_mode="Markdown" if result.parse_mode == "markdown" else None,
        )

    def _handle_virtual_card_action(self, *, vk_user_id: int, person_phone_e164: str) -> VkAdapterResponse:
        """Обрабатывает пункт меню «Виртуальная карта» через общий use-case лояльности."""

        back_to_main_screen = self._menu_adapter.build_balance_screen(balance=0.0)
        if self._virtual_card_use_case is None:
            error_message = (
                "❌ Сервис виртуальной карты временно недоступен.\n"
                "Код ошибки: IIKO-CARD-000.\n"
                "Покажите это сообщение сотруднику и попробуйте позже."
            )
            self._create_external_error_ticket_for_guest(
                vk_user_id=vk_user_id,
                guest_error_message=error_message,
            )
            return VkAdapterResponse(
                text=error_message,
                screen=back_to_main_screen,
            )

        result = self._virtual_card_use_case.execute(phone_e164=person_phone_e164)
        if result.status in {"virtual_card_error", "virtual_card_unavailable"}:
            self._create_external_error_ticket_for_guest(
                vk_user_id=vk_user_id,
                guest_error_message=result.message,
            )
            return VkAdapterResponse(
                text=result.message,
                screen=back_to_main_screen,
                parse_mode="Markdown" if result.parse_mode == "markdown" else None,
                virtual_card_numbers=result.card_numbers,
            )
        if result.status == "virtual_card" and result.card_numbers:
            followup_screen = self._menu_adapter.build_virtual_card_result_screen()
            return VkAdapterResponse(
                text=followup_screen.text,
                screen=followup_screen,
                parse_mode=followup_screen.parse_mode,
                virtual_card_numbers=result.card_numbers,
            )
        return VkAdapterResponse(
            text=result.message,
            parse_mode="Markdown" if result.parse_mode == "markdown" else None,
            virtual_card_numbers=result.card_numbers,
        )

    def _create_external_error_ticket_for_guest(
        self,
        *,
        vk_user_id: int,
        guest_error_message: str,
    ) -> None:
        """Создает тикет модератору при критической ошибке внешней системы."""

        if self._create_support_ticket_use_case is None:
            return

        normalized_error = str(guest_error_message).strip()
        if not normalized_error:
            return

        error_code = self._extract_iiko_error_code(normalized_error) or "unknown"
        ticket_text = (
            "⚠️ Автоматическое обращение: критическая ошибка внешней системы.\n"
            "Платформа: vk\n"
            f"ID гостя: {vk_user_id}\n"
            f"Код ошибки: {error_code}\n\n"
            "Текст сообщения, показанного гостю:\n"
            f"{normalized_error}\n\n"
            "Просьба модератору: передайте это сообщение техническим специалистам."
        )

        method_logger = self._logger.bind(stage="external_error_ticket", user_id=str(vk_user_id))
        try:
            self._create_support_ticket_use_case.execute(
                CreateSupportTicketCommand(
                    platform="vk",
                    external_id=str(vk_user_id),
                    question_text=ticket_text,
                )
            )
            method_logger.warning("Автоматически создан тикет по критической ошибке iiko. code={code}.", code=error_code)
        except ValueError as error:
            method_logger.warning(
                "Не удалось создать автотикет по критической ошибке iiko. reason={reason}.",
                reason=str(error),
            )

    @staticmethod
    def _extract_iiko_error_code(error_text: str) -> str | None:
        """Извлекает код ошибки IIKO-***-*** из текста ошибки."""

        match = re.search(r"IIKO-[A-Z]+-\d{3}", str(error_text))
        if match is None:
            return None
        return match.group(0)

    def _has_user_tickets(self, *, platform: str, external_id: str) -> bool:
        """Проверяет, есть ли у пользователя хотя бы один тикет поддержки."""

        return bool(self._list_user_tickets(platform=platform, external_id=external_id, limit=1))

    def _list_user_tickets(
        self,
        *,
        platform: str,
        external_id: str,
        limit: int,
    ) -> tuple[PersonSupportTicketSummary, ...]:
        """Возвращает тикеты пользователя для раздела «Мои обращения»."""

        if self._list_person_tickets_use_case is None:
            return ()
        try:
            return self._list_person_tickets_use_case.execute(
                platform=platform,  # type: ignore[arg-type]
                external_id=external_id,
                limit=limit,
            )
        except ValueError:
            return ()

    def _show_user_tickets_page(
        self,
        vk_user_id: int,
        page: int = 1,
        per_page: int = 3,  # Ограничиваем 3 тикетами на страницу для VK из-за ограничений клавиатуры
    ) -> VkAdapterResponse:
        """Показывает страницу тикетов пользователя с пагинацией."""

        if self._get_person_tickets_page_use_case is None:
            # Fallback: используем старый метод без пагинации
            tickets = self._list_user_tickets(
                platform="vk",
                external_id=str(vk_user_id),
                limit=5,
            )
            if not tickets:
                # Нет тикетов — показываем экран с предложением задать вопрос
                self._state_by_user_id[vk_user_id] = _STATE_WAITING_SUPPORT_QUESTION
                self._reply_ticket_id_by_user_id.pop(vk_user_id, None)
                screen = self._menu_adapter.build_support_question_screen()
                return VkAdapterResponse(text=screen.text, screen=screen)
            # Форматируем сообщение с тикетами
            message = self._format_person_tickets_message(tickets)
            # Создаем экран пагинации с тикетами (без пагинации, т.к. total_pages = 1)
            screen = self._menu_adapter.build_user_tickets_pagination_screen(
                current_page=1,
                total_pages=1,
                tickets=tickets,
                has_tickets=True,
            )
            return VkAdapterResponse(text=message, screen=screen)

        try:
            page_result = self._get_person_tickets_page_use_case.execute(
                platform="vk",
                external_id=str(vk_user_id),
                page=page,
                per_page=per_page,
            )
        except ValueError:
            return VkAdapterResponse(
                text="Произошла ошибка при загрузке обращений."
            )

        if not page_result.tickets:
            # Нет тикетов — показываем экран с предложением задать вопрос
            self._state_by_user_id[vk_user_id] = _STATE_WAITING_SUPPORT_QUESTION
            self._reply_ticket_id_by_user_id.pop(vk_user_id, None)
            screen = self._menu_adapter.build_support_question_screen()
            return VkAdapterResponse(text=screen.text, screen=screen)

        # Форматируем сообщение со страницей
        message = self._format_person_tickets_page_message(page_result)
        # Создаем экран пагинации с тикетами
        screen = self._menu_adapter.build_user_tickets_pagination_screen(
            current_page=page_result.page,
            total_pages=page_result.total_pages,
            tickets=page_result.tickets,
            has_tickets=True,
        )
        return VkAdapterResponse(text=message, screen=screen)

    @staticmethod
    def _format_ticket_id_short(ticket_id: UUID) -> str:
        """Возвращает короткое представление UUID (последние 4 символа в верхнем регистре)."""
        full_str = str(ticket_id)
        if len(full_str) >= 4:
            return full_str[-4:].upper()
        return full_str.upper()

    @staticmethod
    def _format_ticket_status(status_value: str) -> tuple[str, str]:
        """Возвращает эмодзи и человекочитаемый текст статуса тикета."""

        if status_value == "open":
            return "🆕", "открыт"
        if status_value == "in_progress":
            return "🛠", "в работе"
        if status_value == "closed":
            return "🔒", "закрыт"
        return "❓", status_value

    @staticmethod
    def _format_platform_label(platform: str | None) -> str:
        """Форматирует код платформы для компактного отображения в интерфейсе."""

        normalized = str(platform or "-").strip().lower()
        if normalized == "telegram":
            return "tg"
        if normalized in {"vk", "max"}:
            return normalized
        return normalized if normalized else "-"

    @staticmethod
    def _extract_first_ticket_question(messages: tuple[object, ...]) -> str:
        """Возвращает первый вопрос гостя из истории тикета."""

        for message in messages:
            author_value = getattr(getattr(message, "author", None), "value", "")
            body = str(getattr(message, "body", "")).strip()
            if author_value == "guest" and body:
                return body
        for message in messages:
            body = str(getattr(message, "body", "")).strip()
            if body:
                return body
        return "—"

    def _build_moderation_ticket_card_lines(
        self,
        *,
        details: object,
        messages: tuple[object, ...],
    ) -> list[str]:
        """Формирует компактную карточку тикета в стиле прототипов."""

        status_emoji, status_text = self._format_ticket_status(getattr(details.status, "value", str(details.status)))
        linked = ", ".join(self._format_platform_label(platform) for platform in details.linked_platforms) or "-"
        question = self._extract_first_ticket_question(messages)
        message_lines = [
            f"{status_emoji} Тикет #{self._format_ticket_id_short(details.ticket_id)}",
            f"Статус: {status_text.capitalize()}",
            f"Канал создания: {self._format_platform_label(details.source_platform)}",
            f"Последний канал гостя: {self._format_platform_label(details.last_guest_platform)}",
            f"Каналы гостя: {linked}",
            "",
            "❓ Вопрос:",
            question,
            "",
        ]
        message_lines.extend(self._format_ticket_history_lines(messages))
        return message_lines

    @staticmethod
    def _format_ticket_history_lines(messages: tuple[object, ...]) -> list[str]:
        """Форматирует блок истории переписки тикета."""

        lines: list[str] = ["--- История переписки ---"]
        if not messages:
            lines.append("Сообщений в тикете пока нет.")
            return lines

        for message in messages:
            author_value = getattr(getattr(message, "author", None), "value", "")
            author_label = "👤 Гость" if author_value == "guest" else "👨‍💼 Модератор"
            source_platform = VkIdentityAdapter._format_platform_label(
                str(getattr(message, "source_platform", "-"))
            )
            created_at = getattr(message, "created_at", None)
            created_at_text = created_at.strftime("%d.%m %H:%M") if created_at else "время не указано"
            body = str(getattr(message, "body", "")).strip() or "—"
            lines.append(f"[{created_at_text}] {author_label} ({source_platform}):")
            for line in body.splitlines():
                lines.append(f"» {line}" if line.strip() else "»")
            lines.append("")

        if lines and lines[-1] == "":
            lines.pop()

        return lines

    def _get_ticket_details_with_history(self, ticket_id: UUID) -> tuple[object, tuple[object, ...]]:
        """Возвращает карточку тикета и историю переписки (если use-case подключен)."""

        if self._ticket_conversation_use_case is not None:
            conversation = self._ticket_conversation_use_case.execute(ticket_id)
            return conversation, conversation.messages

        if self._ticket_details_use_case is None:
            raise ValueError("Функционал карточки тикета временно недоступен.")

        details = self._ticket_details_use_case.execute(ticket_id)
        return details, ()

    @staticmethod
    def _format_person_tickets_message(tickets: tuple[PersonSupportTicketSummary, ...]) -> str:
        """Форматирует список тикетов пользователя в текстовое представление."""

        lines = ["📋 Ваши обращения:"]
        status_emoji = {"open": "🆕", "closed": "🔒"}
        for i, ticket in enumerate(tickets, 1):
            created_at = ticket.created_at.strftime("%d.%m.%Y") if ticket.created_at else "—"
            short_status = "открыт" if ticket.status.value == "open" else "закрыт"
            short_id = VkIdentityAdapter._format_ticket_id_short(ticket.ticket_id)
            lines.append(
                f"{i}. {status_emoji.get(ticket.status.value, '❓')} #{short_id} от {created_at}: {short_status}"
            )
        
        lines.append("\nℹ️ Для просмотра деталей тикета или ответа используйте кнопки ниже.")
        return "\n".join(lines)

    def _format_person_tickets_page_message(self, page_result: PersonTicketsPageResult) -> str:
        """Форматирует страницу тикетов пользователя с пагинацией."""

        lines = ["📋 Ваши обращения:"]
        status_emoji = {"open": "🆕", "closed": "🔒"}
        
        for i, ticket in enumerate(page_result.tickets, 1):
            created_at = ticket.created_at.strftime("%d.%m.%Y") if ticket.created_at else "—"
            short_status = "открыт" if ticket.status.value == "open" else "закрыт"
            short_id = self._format_ticket_id_short(ticket.ticket_id)
            lines.append(
                f"{i}. {status_emoji.get(ticket.status.value, '❓')} #{short_id} от {created_at}: {short_status}"
            )
        
        if page_result.total_pages > 1:
            lines.append(f"\n📄 Страница {page_result.page} из {page_result.total_pages}")
        
        lines.append("\nℹ️ Для просмотра деталей тикета или ответа используйте кнопки ниже.")
        return "\n".join(lines)

    def _build_profile_text_for_draft(self, vk_user_id: int) -> str:
        """Формирует текст review-профиля на основании черновика onboarding и сохранённого Person."""

        draft = self._onboarding_draft_by_user_id.get(vk_user_id)
        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        phone_e164 = (
            (draft.phone_e164 if draft is not None else None)
            or (person.phone_e164 if person is not None else None)
            or "не указан"
        )
        first_name_input = (
            (draft.first_name_input if draft is not None else None)
            or (person.first_name_input if person is not None else None)
        )
        rules_accepted_at = (
            (draft.rules_accepted_at if draft is not None else None)
            or (person.get_rules_accepted_at_for_platform("vk") if person is not None else None)
        )
        rules_accepted = bool(
            (draft is not None and draft.rules_accepted_at is not None)
            or (person is not None and person.get_rules_accepted_for_platform("vk"))
        )
        accounts_count = len(person.accounts) if person is not None else 1
        accounts_platforms = (
            self._collect_account_platforms(person.accounts)
            if person is not None
            else ("vk",)
        )

        return self._menu_adapter.build_profile_screen(
            phone_e164=phone_e164,
            accounts_count=accounts_count,
            accounts_platforms=accounts_platforms,
            first_name_input=first_name_input,
            last_name_input=person.last_name_input if person is not None else None,
            gender=person.gender if person is not None else None,
            birth_date=person.birth_date if person is not None else None,
            email=person.email if person is not None else None,
            rules_accepted=rules_accepted,
            rules_accepted_at=rules_accepted_at,
            notifications_allowed=person.get_notifications_allowed_for_platform("vk") if person is not None else None,
            notifications_allowed_at=person.get_notifications_allowed_at_for_platform("vk") if person is not None else None,
        ).text

    @staticmethod
    def _normalize_first_name(raw_text: str) -> str | None:
        """Проверяет и нормализует имя пользователя для шага сокращённой регистрации."""

        return normalize_person_name(raw_text)

    def _prefill_profile_from_loyalty(self, *, vk_user_id: int, person):
        """Дозаполняет пустые поля профиля данными iiko в legacy-ветке, не перезаписывая локальные значения."""

        if self._loyalty_gateway is None:
            return person

        method_logger = self._logger.bind(stage="legacy_loyalty_prefill", user_id=str(vk_user_id))
        try:
            customer = self._loyalty_gateway.get_customer_info(person.phone_e164)
        except LoyaltyGatewayError as error:
            method_logger.warning("Не удалось получить профиль из iiko: {error}.", error=error)
            return person

        if customer is None:
            method_logger.info("Профиль в iiko не найден, legacy-префилл пропущен.")
            return person

        update_kwargs: dict[str, object] = {}
        if not (person.first_name_input or "").strip() and (customer.first_name or "").strip():
            update_kwargs["first_name_input"] = customer.first_name.strip()
        if not (person.last_name_input or "").strip() and (customer.last_name or "").strip():
            update_kwargs["last_name_input"] = customer.last_name.strip()
        if not person.gender and customer.gender in {"male", "female"}:
            update_kwargs["gender"] = customer.gender
        if person.birth_date is None and customer.birth_date is not None:
            update_kwargs["birth_date"] = customer.birth_date
        if not (person.email or "").strip():
            normalized_email = normalize_email(customer.email or "")
            if normalized_email is not None:
                update_kwargs["email"] = normalized_email

        if not update_kwargs:
            method_logger.info("Пустых полей для префилла из iiko не найдено.")
            return person

        try:
            updated_person = self._registration_use_case.execute(
                RegisterOrAttachAccountCommand(
                    platform="vk",
                    external_id=str(vk_user_id),
                    raw_phone=person.phone_e164,
                    **update_kwargs,
                )
            )
        except (IdentityConflictError, ValueError) as error:
            method_logger.warning("Префилл из iiko пропущен из-за ошибки обновления профиля: {error}.", error=error)
            return person

        method_logger.info(
            "Legacy-профиль дополнен из iiko. updated_fields={fields}.",
            fields=",".join(sorted(update_kwargs.keys())),
        )
        return updated_person

    @staticmethod
    def _collect_account_platforms(accounts: set[object]) -> tuple[str, ...]:
        """Возвращает отсортированный список платформ привязанных аккаунтов пользователя."""

        sort_order = {"telegram": 0, "vk": 1, "max": 2}
        platforms: set[str] = {
            str(getattr(account, "platform", "")).lower()
            for account in accounts
            if getattr(account, "platform", None)
        }
        return tuple(sorted(platforms, key=lambda platform: sort_order.get(platform, 99)))

    def _handle_view_ticket_details(
        self,
        vk_user_id: int,
        ticket_id: UUID,
    ) -> VkAdapterResponse:
        """Показывает детали тикета (историю переписки) для пользователя."""
        
        method_logger = self._logger.bind(
            stage="view_ticket_details",
            user_id=str(vk_user_id),
            ticket_id=str(ticket_id),
        )
        
        # Получаем информацию о тикете
        if self._ticket_details_use_case is None:
            method_logger.warning("Use-case деталей тикета недоступен.")
            return VkAdapterResponse(
                text="Функционал просмотра деталей тикета временно недоступен.",
            )
        
        try:
            details, messages = self._get_ticket_details_with_history(ticket_id)
        except ValueError as error:
            method_logger.warning("Тикет не найден или недоступен. error={error}", error=str(error))
            return VkAdapterResponse(
                text=f"Тикет не найден: {error}",
            )
        
        # Проверяем, принадлежит ли тикет текущему пользователю
        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        if person is None or person.person_id != details.person_id:
            method_logger.warning(
                "Попытка просмотра чужого тикета. user_person_id={user_person_id}, ticket_person_id={ticket_person_id}",
                user_person_id=person.person_id if person else None,
                ticket_person_id=details.person_id,
            )
            return VkAdapterResponse(
                text="У вас нет доступа к этому тикету.",
            )
        
        # Форматируем сообщение с деталями тикета
        short_id = self._format_ticket_id_short(ticket_id)
        status_emoji, status_text = self._format_ticket_status(details.status.value)
        message_lines = [
            f"{status_emoji} Тикет #{short_id}",
            f"Статус: {status_text}",
            f"Создан в: {self._format_platform_label(details.source_platform)}",
        ]

        if details.last_guest_platform:
            message_lines.append(
                f"Последний ответ из: {self._format_platform_label(details.last_guest_platform)}"
            )

        message_lines.append("")
        message_lines.extend(self._format_ticket_history_lines(messages))
        message = "\n".join(message_lines)

        rows: list[tuple[VkButton, ...]] = []
        if details.status != SupportTicketStatus.CLOSED:
            rows.append(
                (
                    VkButton(
                        label="✍️ Ответить",
                        payload={"cmd": f"{USER_TICKET_REPLY_PREFIX}{ticket_id}"},
                    ),
                )
            )
        back_button = VkButton(
            label=BUTTON_MY_TICKETS,
            payload=build_vk_payload(GuestMenuAction.MY_TICKETS),
        )
        rows.append((back_button,))
        screen = VkScreen(
            screen_id="ticket_details",
            text=message,
            rows=tuple(rows),
        )
        
        return VkAdapterResponse(
            text=message,
            screen=screen,
        )

    def _sync_registration_with_loyalty(
        self,
        *,
        phone_e164: str,
        profile: LoyaltyCustomerUpsertData | None = None,
    ) -> tuple[str, ...]:
        """Запускает синхронизацию с iiko и возвращает номера карт для отправки QR."""

        method_logger = self._logger.bind(stage="sync_registration_with_loyalty")
        if self._virtual_card_use_case is None:
            method_logger.info("Синхронизация с iiko пропущена: virtual_card_use_case не подключен.")
            return ()

        result = self._virtual_card_use_case.execute(phone_e164=phone_e164, profile=profile)
        if result.status == "virtual_card":
            method_logger.info(
                "Синхронизация с iiko завершена успешно. cards={cards_count}.",
                cards_count=len(result.card_numbers),
            )
            return result.card_numbers

        method_logger.warning(
            "Синхронизация с iiko завершилась без карт. status={status}.",
            status=result.status,
        )
        return ()

    def _build_loyalty_upsert_profile(self, *, vk_user_id: int) -> LoyaltyCustomerUpsertData | None:
        """Готовит профиль для create_or_update в iiko на шаге завершения регистрации."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        if person is None:
            return None

        return LoyaltyCustomerUpsertData(
            first_name=person.first_name_input,
            last_name=person.last_name_input,
            gender=person.gender,
            birth_date=person.birth_date,
            email=person.email,
            rules_accepted=person.get_rules_accepted_for_platform("vk"),
            notifications_allowed=person.get_notifications_allowed_for_platform("vk"),
            rules_accepted_at=person.get_rules_accepted_at_for_platform("vk"),
            notifications_allowed_at=person.get_notifications_allowed_at_for_platform("vk"),
        )
