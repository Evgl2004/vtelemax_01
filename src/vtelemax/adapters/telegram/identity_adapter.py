"""Адаптер регистрации пользователя Telegram в strict identity."""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import UUID

from loguru import logger

from vtelemax.core import (
    AddGuestMessageToTicketCommand,
    AddGuestMessageToTicketTransactionalUseCase,
    BUTTON_ACCEPT_RULES,
    BUTTON_ABOUT,
    BUTTON_BALANCE,
    BUTTON_DELIVERY,
    BUTTON_HELP,
    BUTTON_MAIN_MENU,
    BUTTON_PROFILE,
    BUTTON_PROFILE_EDIT,
    BUTTON_PROFILE_EDIT_BIRTH_DATE,
    BUTTON_PROFILE_EDIT_CANCEL,
    BUTTON_PROFILE_EDIT_EMAIL,
    BUTTON_PROFILE_EDIT_FIRST_NAME,
    BUTTON_PROFILE_EDIT_GENDER,
    BUTTON_PROFILE_EDIT_GENDER_FEMALE,
    BUTTON_PROFILE_EDIT_GENDER_MALE,
    BUTTON_PROFILE_EDIT_LAST_NAME,
    BUTTON_RETRY_IIKO_SYNC,
    BUTTON_SEND_PHONE,
    BUTTON_SUPPORT_QUESTION,
    BUTTON_SUPPORT,
    BUTTON_VACANCIES,
    BUTTON_VIRTUAL_CARD,
    CreateSupportTicketCommand,
    CreateSupportTicketTransactionalUseCase,
    GetLoyaltyBalanceUseCase,
    GetPersonTicketsPageTransactionalUseCase,
    LoyaltyCustomerUpsertData,
    LoyaltyGateway,
    LoyaltyGatewayError,
    GuestMenuAction,
    GetSupportTicketConversationTransactionalUseCase,
    GetSupportTicketDetailsTransactionalUseCase,
    GetVirtualCardUseCase,
    ListOpenSupportTicketsTransactionalUseCase,
    ListPersonSupportTicketsTransactionalUseCase,
    ModeratorReplyCommand,
    OnboardingFlowService,
    OnboardingState,
    OpenSupportTicketSummary,
    PersonSupportTicketSummary,
    PersonTicketsPageResult,
    GetPersonByAccountCommand,
    GetPersonByAccountTransactionalUseCase,
    IdentityConflictError,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
    RouteModeratorReplyTransactionalUseCase,
    SetSupportTicketStatusCommand,
    SetSupportTicketStatusTransactionalUseCase,
    SUPPORTED_PLATFORMS,
    SupportTicketStatus,
    build_about_screen,
    build_business_lunch_screen,
    build_delivery_screen,
    build_first_name_input_screen,
    build_help_screen,
    build_iiko_sync_retry_screen,
    build_main_menu_screen,
    build_profile_edit_screen,
    build_profile_gender_screen,
    build_profile_not_found_screen,
    build_profile_screen,
    build_start_rules_screen,
    build_support_contacts_screen,
    build_support_feedback_screen,
    build_support_menu_screen,
    build_support_question_screen,
    build_table_booking_screen,
    build_virtual_card_result_screen,
    build_vacancies_screen,
    normalize_email,
    normalize_menu_text,
    normalize_person_name,
    parse_birth_date,
    resolve_guest_menu_action,
)

from .menu import (
    MOD_CLOSE_PREFIX,
    MOD_LIST_PREFIX,
    MOD_MAIN_CALLBACK,
    MOD_PAGE_PREFIX,
    MOD_REPLY_PREFIX,
    MOD_TAKE_PREFIX,
    MOD_TICKET_PREFIX,
    USER_TICKETS_PAGE_PREFIX,
    USER_TICKETS_PREV_PAGE_PREFIX,
    USER_TICKETS_NEXT_PAGE_PREFIX,
    USER_TICKET_DETAILS_PREFIX,
    USER_TICKET_REPLY_PREFIX,
    build_user_tickets_pagination_keyboard,
)


@dataclass(frozen=True, slots=True)
class TelegramRegistrationResult:
    """Результат обработки регистрации/привязки из Telegram."""

    is_success: bool
    status: str
    message: str
    person_id: UUID | None = None
    parse_mode: str | None = None
    virtual_card_numbers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TelegramMenuActionResult:
    """Результат обработки пункта меню Telegram."""

    status: str
    message: str
    requires_contact_keyboard: bool = False
    parse_mode: str | None = None
    has_support_tickets: bool = False
    can_edit_birth_date: bool | None = None
    virtual_card_numbers: tuple[str, ...] = ()
    current_page: int | None = None
    total_pages: int | None = None
    tickets: tuple[PersonSupportTicketSummary, ...] = ()
    ticket_id: UUID | None = None
    ticket_status: str | None = None
    moderation_filter: str | None = None
    moderation_page: int | None = None
    moderation_total_pages: int | None = None
    moderation_ticket_id: UUID | None = None
    moderation_ticket_status: str | None = None
    moderation_tickets: tuple[OpenSupportTicketSummary, ...] = ()


_STATE_WAITING_SUPPORT_QUESTION = "waiting_support_question"
_STATE_WAITING_SUPPORT_REPLY = "waiting_support_reply"
_STATE_PROFILE_EDIT_CHOICE = "profile_edit_choice"
_STATE_PROFILE_EDIT_FIRST_NAME = "profile_edit_first_name"
_STATE_PROFILE_EDIT_LAST_NAME = "profile_edit_last_name"
_STATE_PROFILE_EDIT_GENDER = "profile_edit_gender"
_STATE_PROFILE_EDIT_BIRTH_DATE = "profile_edit_birth_date"
_STATE_PROFILE_EDIT_EMAIL = "profile_edit_email"
_STATE_MOD_MENU = "moderation_menu"
_STATE_MOD_WAIT_TICKET_FOR_REPLY = "moderation_wait_ticket_for_reply"
_STATE_MOD_WAIT_REPLY_TEXT = "moderation_wait_reply_text"
_STATE_MOD_WAIT_TICKET_FOR_DETAILS = "moderation_wait_ticket_for_details"
_STATE_MOD_WAIT_TICKET_FOR_CLOSE = "moderation_wait_ticket_for_close"
_STATE_MOD_WAIT_TICKET_FOR_IN_PROGRESS = "moderation_wait_ticket_for_in_progress"

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


@dataclass(slots=True)
class _OnboardingDraft:
    """Промежуточные данные сокращенной регистрации до финальной фиксации."""

    rules_accepted_at: datetime | None = None
    phone_e164: str | None = None
    phone_verified_at: datetime | None = None
    phone_verification_method: str | None = None
    first_name_input: str | None = None
    is_legacy_upgrade: bool = False


class TelegramIdentityAdapter:
    """Сервисный адаптер Telegram -> use-case strict identity."""

    def __init__(
        self,
        registration_use_case: RegisterOrAttachAccountTransactionalUseCase,
        person_lookup_use_case: GetPersonByAccountTransactionalUseCase,
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
    ) -> None:
        self._logger = logger.bind(platform="telegram", component="identity_adapter")
        self._registration_use_case = registration_use_case
        self._person_lookup_use_case = person_lookup_use_case
        self._onboarding_flow = OnboardingFlowService(platform="telegram")
        self._onboarding_state_by_user_id: dict[int, OnboardingState] = {}
        self._onboarding_draft_by_user_id: dict[int, _OnboardingDraft] = {}
        self._dialog_state_by_user_id: dict[int, str] = {}
        self._reply_ticket_id_by_user_id: dict[int, UUID] = {}
        self._moderator_state_by_user_id: dict[int, str] = {}
        self._moderator_context_by_user_id: dict[int, dict[str, str]] = {}
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

    def start_interaction(
        self,
        telegram_user_id: int,
        *,
        force_legacy_upgrade: bool = False,
    ) -> TelegramMenuActionResult:
        """Запускает стартовый сценарий onboarding/меню для пользователя."""

        method_logger = self._logger.bind(stage="start_interaction", user_id=str(telegram_user_id))
        method_logger.debug(
            "Запуск start_interaction. force_legacy_upgrade={force_legacy_upgrade}.",
            force_legacy_upgrade=force_legacy_upgrade,
        )
        current_state = self._onboarding_state_by_user_id.get(telegram_user_id)
        if current_state == OnboardingState.WAITING_IIKO_SYNC:
            method_logger.info("Продолжаем шаг ожидания синхронизации iiko.")
            retry_screen = build_iiko_sync_retry_screen()
            return TelegramMenuActionResult(
                status="iiko_sync_retry",
                message=retry_screen.text,
            )

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(
                platform="telegram",
                external_id=str(telegram_user_id),
            )
        )

        if person is None:
            method_logger.info("Пользователь не найден, запускаем onboarding для нового пользователя.")
            transition = self._onboarding_flow.begin_new_user()
            self._onboarding_state_by_user_id[telegram_user_id] = transition.state
            self._onboarding_draft_by_user_id[telegram_user_id] = _OnboardingDraft()
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            self._clear_moderator_state(telegram_user_id)
            return TelegramMenuActionResult(
                status=transition.status,
                message=transition.message,
                requires_contact_keyboard=transition.requires_contact_keyboard,
            )

        if force_legacy_upgrade:
            method_logger.info("Запрошен legacy-flow обновления профиля.")
            transition = self._onboarding_flow.begin_legacy_upgrade()
            self._onboarding_state_by_user_id[telegram_user_id] = transition.state
            self._onboarding_draft_by_user_id[telegram_user_id] = _OnboardingDraft(is_legacy_upgrade=True)
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            self._clear_moderator_state(telegram_user_id)
            return TelegramMenuActionResult(
                status=transition.status,
                message=transition.message,
                requires_contact_keyboard=transition.requires_contact_keyboard,
            )

        if not person.is_registered_for_platform("telegram"):
            method_logger.info("Найден незавершенный профиль, восстанавливаем onboarding.")
            draft = _OnboardingDraft(
                rules_accepted_at=person.get_rules_accepted_at_for_platform("telegram"),
                phone_e164=person.phone_e164,
                phone_verified_at=person.phone_verified_at,
                phone_verification_method=person.phone_verification_method,
                first_name_input=person.first_name_input,
                is_legacy_upgrade=person.is_legacy,
            )
            self._onboarding_draft_by_user_id[telegram_user_id] = draft
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            self._clear_moderator_state(telegram_user_id)

            if not person.get_rules_accepted_for_platform("telegram"):
                transition = self._onboarding_flow.begin_new_user()
                self._onboarding_state_by_user_id[telegram_user_id] = transition.state
                return TelegramMenuActionResult(
                    status=transition.status,
                    message=transition.message,
                    requires_contact_keyboard=transition.requires_contact_keyboard,
                )

            if not person.first_name_input:
                transition = self._onboarding_flow.begin_first_name_step()
                self._onboarding_state_by_user_id[telegram_user_id] = transition.state
                return TelegramMenuActionResult(status=transition.status, message=transition.message)

            transition = self._onboarding_flow.begin_notifications_consent_step(
                phone_e164=person.phone_e164,
                accounts_count=len(person.accounts),
                first_name_input=person.first_name_input,
            )
            self._onboarding_state_by_user_id[telegram_user_id] = transition.state
            return TelegramMenuActionResult(status=transition.status, message=transition.message)

        # Проверяем, собраны ли все согласия для платформы Telegram
        platform_consents_complete = (
            person.get_rules_accepted_for_platform("telegram") is True
            and person.get_notifications_allowed_at_for_platform("telegram") is not None
        )
        if not platform_consents_complete:
            method_logger.info(
                "Пользователь зарегистрирован, но согласия для Telegram неполные, продолжаем onboarding."
            )
            draft = _OnboardingDraft(
                rules_accepted_at=person.get_rules_accepted_at_for_platform("telegram"),
                phone_e164=person.phone_e164,
                phone_verified_at=person.phone_verified_at,
                phone_verification_method=person.phone_verification_method,
                first_name_input=person.first_name_input,
                is_legacy_upgrade=person.is_legacy,
            )
            self._onboarding_draft_by_user_id[telegram_user_id] = draft
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            self._clear_moderator_state(telegram_user_id)

            if not person.get_rules_accepted_for_platform("telegram"):
                transition = self._onboarding_flow.begin_new_user()
                self._onboarding_state_by_user_id[telegram_user_id] = transition.state
                return TelegramMenuActionResult(
                    status=transition.status,
                    message=transition.message,
                    requires_contact_keyboard=transition.requires_contact_keyboard,
                )

            if not person.first_name_input:
                transition = self._onboarding_flow.begin_first_name_step()
                self._onboarding_state_by_user_id[telegram_user_id] = transition.state
                return TelegramMenuActionResult(status=transition.status, message=transition.message)

            transition = self._onboarding_flow.begin_notifications_consent_step(
                phone_e164=person.phone_e164,
                accounts_count=len(person.accounts),
                first_name_input=person.first_name_input,
            )
            self._onboarding_state_by_user_id[telegram_user_id] = transition.state
            return TelegramMenuActionResult(status=transition.status, message=transition.message)

        self._onboarding_state_by_user_id.pop(telegram_user_id, None)
        self._onboarding_draft_by_user_id.pop(telegram_user_id, None)
        self._dialog_state_by_user_id.pop(telegram_user_id, None)
        self._clear_moderator_state(telegram_user_id)
        method_logger.info("Пользователь найден, открываем главное меню.")
        return TelegramMenuActionResult(
            status="menu",
            message=self.build_menu_overview_message(
                user_name=self._resolve_menu_user_name(telegram_user_id=telegram_user_id, person=person)
            ),
        )

    def register_contact(self, telegram_user_id: int, raw_phone: str) -> TelegramRegistrationResult:
        """Регистрирует Telegram-аккаунт пользователя по переданному телефону."""

        method_logger = self._logger.bind(stage="register_contact", user_id=str(telegram_user_id))
        method_logger.debug("Начата регистрация контакта.")
        previous_state = self._onboarding_state_by_user_id.get(telegram_user_id, OnboardingState.IDLE)
        if previous_state == OnboardingState.WAITING_IIKO_SYNC:
            retry_screen = build_iiko_sync_retry_screen()
            return TelegramRegistrationResult(
                is_success=False,
                status="iiko_sync_retry",
                message=retry_screen.text,
            )
        draft = self._onboarding_draft_by_user_id.setdefault(telegram_user_id, _OnboardingDraft())
        phone_verified_at = datetime.now(timezone.utc)

        try:
            person = self._registration_use_case.execute(
                RegisterOrAttachAccountCommand(
                    platform="telegram",
                    external_id=str(telegram_user_id),
                    raw_phone=raw_phone,
                    rules_accepted=True if draft.rules_accepted_at is not None else None,
                    rules_accepted_at=draft.rules_accepted_at,
                    phone_verified_at=phone_verified_at,
                    phone_verification_method="telegram_contact",
                )
            )
        except IdentityConflictError:
            method_logger.warning("Конфликт strict identity при регистрации контакта.")
            return TelegramRegistrationResult(
                is_success=False,
                status="conflict",
                message=(
                    "Обнаружен конфликт идентификации: этот Telegram-аккаунт уже привязан к другому "
                    "телефону или телефон связан с другим аккаунтом."
                ),
            )
        except ValueError:
            method_logger.warning("Ошибка валидации телефона при регистрации контакта.")
            return TelegramRegistrationResult(
                is_success=False,
                status="validation_error",
                message="Не удалось обработать контакт. Нажмите кнопку отправки контакта и попробуйте снова.",
            )

        draft.phone_e164 = person.phone_e164
        draft.phone_verified_at = phone_verified_at
        draft.phone_verification_method = "telegram_contact"

        if previous_state == OnboardingState.WAITING_PHONE and person.first_name_input and not person.is_legacy:
            # Проверяем, собраны ли все согласия для платформы Telegram
            platform_consents_complete = (
                person.get_rules_accepted_for_platform("telegram") is True
                and person.get_notifications_allowed_at_for_platform("telegram") is not None
            )
            if platform_consents_complete:
                self._onboarding_state_by_user_id.pop(telegram_user_id, None)
                self._onboarding_draft_by_user_id.pop(telegram_user_id, None)
                self._dialog_state_by_user_id.pop(telegram_user_id, None)
                self._clear_moderator_state(telegram_user_id)
                method_logger.info(
                    "Телефон найден в зарегистрированном профиле, согласия для Telegram собраны, открываем главное меню. person_id={person_id}.",
                    person_id=person.person_id,
                )
                return TelegramRegistrationResult(
                    is_success=True,
                    status="menu",
                    message=self.build_menu_overview_message(
                        user_name=self._resolve_menu_user_name(
                            telegram_user_id=telegram_user_id,
                            person=person,
                        )
                    ),
                    person_id=person.person_id,
                )
            else:
                method_logger.info(
                    "Телефон найден в зарегистрированном профиле, но согласия для Telegram неполные, продолжаем onboarding. person_id={person_id}.",
                    person_id=person.person_id,
                )
                draft = self._onboarding_draft_by_user_id.setdefault(telegram_user_id, _OnboardingDraft())
                draft.phone_e164 = person.phone_e164
                draft.phone_verified_at = person.phone_verified_at
                draft.phone_verification_method = person.phone_verification_method
                draft.rules_accepted_at = person.get_rules_accepted_at_for_platform("telegram")
                draft.first_name_input = person.first_name_input
                draft.is_legacy_upgrade = person.is_legacy

                if not person.get_rules_accepted_for_platform("telegram"):
                    transition = self._onboarding_flow.begin_new_user()
                    self._onboarding_state_by_user_id[telegram_user_id] = transition.state
                    return TelegramRegistrationResult(
                        is_success=False,
                        status=transition.status,
                        message=transition.message,
                        person_id=person.person_id,
                    )

                if not person.first_name_input:
                    self._onboarding_state_by_user_id[telegram_user_id] = OnboardingState.WAITING_FIRST_NAME
                    self._dialog_state_by_user_id.pop(telegram_user_id, None)
                    self._clear_moderator_state(telegram_user_id)
                    method_logger.info(
                        "Переходим к шагу ввода имени. person_id={person_id}.",
                        person_id=person.person_id,
                    )
                    return TelegramRegistrationResult(
                        is_success=False,
                        status="first_name_required",
                        message=build_first_name_input_screen().text,
                        person_id=person.person_id,
                    )

                transition = self._onboarding_flow.begin_notifications_consent_step(
                    phone_e164=person.phone_e164,
                    accounts_count=len(person.accounts),
                    first_name_input=person.first_name_input,
                )
                self._onboarding_state_by_user_id[telegram_user_id] = transition.state
                self._dialog_state_by_user_id.pop(telegram_user_id, None)
                self._clear_moderator_state(telegram_user_id)
                return TelegramRegistrationResult(
                    is_success=False,
                    status=transition.status,
                    message=transition.message,
                    person_id=person.person_id,
                )

        if previous_state == OnboardingState.WAITING_PHONE:
            self._onboarding_state_by_user_id[telegram_user_id] = OnboardingState.WAITING_FIRST_NAME
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            self._clear_moderator_state(telegram_user_id)
            method_logger.info(
                "Телефон подтвержден, переходим к шагу ввода имени. person_id={person_id}.",
                person_id=person.person_id,
            )
            return TelegramRegistrationResult(
                is_success=False,
                status="first_name_required",
                message=build_first_name_input_screen().text,
                person_id=person.person_id,
            )

        if previous_state == OnboardingState.WAITING_LEGACY_PHONE:
            person = self._prefill_profile_from_loyalty(
                telegram_user_id=telegram_user_id,
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
                self._onboarding_state_by_user_id[telegram_user_id] = transition.state
                self._dialog_state_by_user_id.pop(telegram_user_id, None)
                self._clear_moderator_state(telegram_user_id)
                method_logger.info(
                    "Legacy: телефон подтвержден, переходим к шагу согласия на рассылку. person_id={person_id}.",
                    person_id=person.person_id,
                )
                return TelegramRegistrationResult(
                    is_success=False,
                    status=transition.status,
                    message=transition.message,
                    person_id=person.person_id,
                )

            self._onboarding_state_by_user_id[telegram_user_id] = OnboardingState.WAITING_FIRST_NAME
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            self._clear_moderator_state(telegram_user_id)
            method_logger.info(
                "Legacy: телефон подтвержден, переходим к шагу ввода имени. person_id={person_id}.",
                person_id=person.person_id,
            )
            return TelegramRegistrationResult(
                is_success=False,
                status="first_name_required",
                message=build_first_name_input_screen().text,
                person_id=person.person_id,
            )

        self._onboarding_state_by_user_id.pop(telegram_user_id, None)
        self._onboarding_draft_by_user_id.pop(telegram_user_id, None)
        self._dialog_state_by_user_id.pop(telegram_user_id, None)
        self._clear_moderator_state(telegram_user_id)
        method_logger.info("Контакт успешно зарегистрирован. person_id={person_id}.", person_id=person.person_id)
        success_message = (
            "Регистрация успешно подтверждена. Ваш номер сохранен в единой базе.\n"
            "Откройте Главное меню и выберите нужный раздел."
        )

        return TelegramRegistrationResult(
            is_success=True,
            status="success",
            message=success_message,
            person_id=person.person_id,
        )

    def build_start_message(self) -> str:
        """Возвращает стартовый текст приветствия."""

        return build_start_rules_screen().text

    def expects_contact_input(self, telegram_user_id: int) -> bool:
        """Проверяет, что сейчас ожидается ввод контакта в onboarding-сценарии."""

        state = self._onboarding_state_by_user_id.get(telegram_user_id, OnboardingState.IDLE)
        return state in {OnboardingState.WAITING_PHONE, OnboardingState.WAITING_LEGACY_PHONE}

    def build_menu_overview_message(self, *, user_name: str = "Гость") -> str:
        """Возвращает текст обзора главного меню."""

        return build_main_menu_screen(user_name=user_name).text

    def handle_menu_action(self, telegram_user_id: int, action_text: str) -> TelegramMenuActionResult:
        """Обрабатывает текстовые действия главного меню Telegram."""

        method_logger = self._logger.bind(stage="menu_action", user_id=str(telegram_user_id))
        method_logger.debug("Обработка действия меню. action_text={action_text}.", action_text=action_text)
        onboarding_state = self._onboarding_state_by_user_id.get(telegram_user_id, OnboardingState.IDLE)
        if onboarding_state == OnboardingState.WAITING_RULES_CONSENT:
            transition = self._onboarding_flow.handle_rules_input(action_text)
            next_transition = transition
            if transition.state == OnboardingState.WAITING_PHONE:
                draft = self._onboarding_draft_by_user_id.setdefault(telegram_user_id, _OnboardingDraft())
                draft.rules_accepted_at = datetime.now(timezone.utc)
                if draft.is_legacy_upgrade:
                    next_transition = self._onboarding_flow.begin_legacy_upgrade()
            self._onboarding_state_by_user_id[telegram_user_id] = next_transition.state
            method_logger.info(
                "Обработано подтверждение правил. status={status}.",
                status=next_transition.status,
            )
            return TelegramMenuActionResult(
                status=next_transition.status,
                message=next_transition.message,
                requires_contact_keyboard=next_transition.requires_contact_keyboard,
            )

        if onboarding_state == OnboardingState.WAITING_PHONE:
            return TelegramMenuActionResult(
                status="phone_required",
                message=(
                    "Следующий шаг регистрации: отправьте номер телефона через кнопку "
                    f"«{BUTTON_SEND_PHONE}»."
                ),
                requires_contact_keyboard=True,
            )

        if onboarding_state == OnboardingState.WAITING_FIRST_NAME:
            normalized_name = self._normalize_first_name(action_text)
            if normalized_name is None:
                return TelegramMenuActionResult(
                    status="first_name_required",
                    message=(
                        "Пожалуйста, укажите имя текстом (только буквы, пробел и дефис, "
                        "от 2 до 50 символов)."
                    ),
                )
            draft = self._onboarding_draft_by_user_id.get(telegram_user_id)
            if draft is None or not draft.phone_e164:
                self._onboarding_state_by_user_id[telegram_user_id] = OnboardingState.WAITING_PHONE
                return TelegramMenuActionResult(
                    status="phone_required",
                    message=(
                        "Потерян шаг подтверждения телефона. Отправьте номер через кнопку "
                        f"«{BUTTON_SEND_PHONE}»."
                    ),
                    requires_contact_keyboard=True,
                )

            draft.first_name_input = normalized_name
            transition = self._onboarding_flow.begin_notifications_consent_step(
                phone_e164=draft.phone_e164,
                accounts_count=1,
                first_name_input=normalized_name,
            )
            self._onboarding_state_by_user_id[telegram_user_id] = transition.state
            return TelegramMenuActionResult(
                status=transition.status,
                message=transition.message,
            )

        if onboarding_state == OnboardingState.WAITING_NOTIFICATIONS_CONSENT:
            notifications_choice = self._onboarding_flow.handle_notifications_input(action_text)
            if notifications_choice is None:
                return TelegramMenuActionResult(
                    status="notifications_consent_pending",
                    message=(
                        "Пожалуйста, выберите один из вариантов согласия на рассылку "
                        "(кнопка «Да» или «Нет»)."
                    ),
                )

            draft = self._onboarding_draft_by_user_id.get(telegram_user_id)
            if draft is None or not draft.phone_e164 or not draft.first_name_input:
                self._onboarding_state_by_user_id[telegram_user_id] = OnboardingState.WAITING_PHONE
                return TelegramMenuActionResult(
                    status="phone_required",
                    message=(
                        "Потеряны промежуточные данные регистрации. "
                        f"Повторите отправку телефона через «{BUTTON_SEND_PHONE}»."
                    ),
                    requires_contact_keyboard=True,
                )

            notifications_fixed_at = datetime.now(timezone.utc)
            # Определяем, давал ли пользователь согласие с правилами для Telegram
            rules_accepted = True if draft.rules_accepted_at is not None else None
            rules_accepted_at = draft.rules_accepted_at
            try:
                person = self._registration_use_case.execute(
                    RegisterOrAttachAccountCommand(
                        platform="telegram",
                        external_id=str(telegram_user_id),
                        raw_phone=draft.phone_e164,
                        rules_accepted=rules_accepted,
                        rules_accepted_at=rules_accepted_at,
                        notifications_allowed=notifications_choice,
                        notifications_allowed_at=notifications_fixed_at,
                        first_name_input=draft.first_name_input,
                        is_legacy=False,
                        is_registered=True,
                        phone_verified_at=draft.phone_verified_at or notifications_fixed_at,
                        phone_verification_method=draft.phone_verification_method or "telegram_contact",
                    )
                )
            except IdentityConflictError:
                return TelegramMenuActionResult(
                    status="conflict",
                    message=(
                        "Обнаружен конфликт идентификации при сохранении анкеты. "
                        "Повторите регистрацию через /start."
                    ),
                )
            except ValueError:
                return TelegramMenuActionResult(
                    status="validation_error",
                    message="Не удалось завершить регистрацию из-за ошибки в данных. Повторите /start.",
                )

            self._onboarding_state_by_user_id[telegram_user_id] = OnboardingState.WAITING_IIKO_SYNC
            draft.phone_e164 = person.phone_e164
            draft.first_name_input = person.first_name_input or draft.first_name_input
            return self._finalize_iiko_sync_step(
                telegram_user_id=telegram_user_id,
                phone_e164=person.phone_e164,
                first_name=draft.first_name_input or "Гость",
            )

        if onboarding_state == OnboardingState.WAITING_IIKO_SYNC:
            action = resolve_guest_menu_action(action_text)
            if action != GuestMenuAction.RETRY_IIKO_SYNC:
                retry_screen = build_iiko_sync_retry_screen()
                return TelegramMenuActionResult(
                    status="iiko_sync_retry_pending",
                    message=(
                        f"{retry_screen.text}\n\n"
                        f"Нажмите кнопку «{BUTTON_RETRY_IIKO_SYNC}», чтобы повторить попытку."
                    ),
                )

            draft = self._onboarding_draft_by_user_id.get(telegram_user_id)
            if draft is None or not draft.phone_e164:
                self._onboarding_state_by_user_id[telegram_user_id] = OnboardingState.WAITING_PHONE
                return TelegramMenuActionResult(
                    status="phone_required",
                    message=(
                        "Не удалось восстановить шаг синхронизации. "
                        f"Повторите отправку телефона через «{BUTTON_SEND_PHONE}»."
                    ),
                    requires_contact_keyboard=True,
                )

            return self._finalize_iiko_sync_step(
                telegram_user_id=telegram_user_id,
                phone_e164=draft.phone_e164,
                first_name=draft.first_name_input or "Гость",
            )

        if onboarding_state == OnboardingState.WAITING_LEGACY_PHONE:
            return TelegramMenuActionResult(
                status="legacy_phone_required",
                message=(
                    "Для обновления legacy-профиля отправьте номер телефона через кнопку "
                    f"«{BUTTON_SEND_PHONE}»."
                ),
                requires_contact_keyboard=True,
            )

        moderation_callback_result = self._try_handle_moderation_callback(
            telegram_user_id=telegram_user_id,
            action_text=action_text,
        )
        if moderation_callback_result is not None:
            return moderation_callback_result

        moderator_result = self._try_handle_moderator_command(
            action_text=action_text,
            telegram_user_id=telegram_user_id,
        )
        if moderator_result is not None:
            return moderator_result

        moderator_state = self._moderator_state_by_user_id.get(telegram_user_id)
        if moderator_state is not None:
            return self._handle_moderator_state_input(
                telegram_user_id=telegram_user_id,
                action_text=action_text,
            )

        dialog_state = self._dialog_state_by_user_id.get(telegram_user_id)
        if dialog_state == _STATE_WAITING_SUPPORT_QUESTION:
            action = resolve_guest_menu_action(action_text)
            if action in {
                GuestMenuAction.BACK_TO_MAIN,
                GuestMenuAction.BACK_TO_SUPPORT,
                GuestMenuAction.SUPPORT,
                GuestMenuAction.MAIN_MENU,
                GuestMenuAction.MY_TICKETS,
            }:
                self._dialog_state_by_user_id.pop(telegram_user_id, None)
                return self.handle_menu_action(telegram_user_id=telegram_user_id, action_text=action_text)
            if action_text.startswith(
                (
                    USER_TICKETS_PREV_PAGE_PREFIX,
                    USER_TICKETS_NEXT_PAGE_PREFIX,
                    USER_TICKETS_PAGE_PREFIX,
                    USER_TICKET_DETAILS_PREFIX,
                    USER_TICKET_REPLY_PREFIX,
                    "mod_",
                )
            ):
                self._dialog_state_by_user_id.pop(telegram_user_id, None)
                return self.handle_menu_action(telegram_user_id=telegram_user_id, action_text=action_text)
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            # Если пользователь ввел что-то неожиданное в состоянии ожидания вопроса,
            # обрабатываем это как вопрос
            return self._handle_support_question_input(
                telegram_user_id=telegram_user_id,
                question_text=action_text,
            )
        if dialog_state == _STATE_WAITING_SUPPORT_REPLY:
            action = resolve_guest_menu_action(action_text)
            if action in {
                GuestMenuAction.BACK_TO_MAIN,
                GuestMenuAction.BACK_TO_SUPPORT,
                GuestMenuAction.SUPPORT,
                GuestMenuAction.MAIN_MENU,
                GuestMenuAction.MY_TICKETS,
            }:
                self._dialog_state_by_user_id.pop(telegram_user_id, None)
                self._reply_ticket_id_by_user_id.pop(telegram_user_id, None)
                return self.handle_menu_action(telegram_user_id=telegram_user_id, action_text=action_text)
            if action_text.startswith(
                (
                    USER_TICKETS_PREV_PAGE_PREFIX,
                    USER_TICKETS_NEXT_PAGE_PREFIX,
                    USER_TICKETS_PAGE_PREFIX,
                    USER_TICKET_DETAILS_PREFIX,
                    USER_TICKET_REPLY_PREFIX,
                    "mod_",
                )
            ):
                self._dialog_state_by_user_id.pop(telegram_user_id, None)
                self._reply_ticket_id_by_user_id.pop(telegram_user_id, None)
                return self.handle_menu_action(telegram_user_id=telegram_user_id, action_text=action_text)
            return self._handle_support_reply_input(
                telegram_user_id=telegram_user_id,
                message_text=action_text,
            )
        if dialog_state == _STATE_PROFILE_EDIT_CHOICE:
            return self._handle_profile_edit_choice_input(
                telegram_user_id=telegram_user_id,
                action_text=action_text,
            )
        if dialog_state == _STATE_PROFILE_EDIT_FIRST_NAME:
            return self._handle_profile_edit_first_name_input(
                telegram_user_id=telegram_user_id,
                action_text=action_text,
            )
        if dialog_state == _STATE_PROFILE_EDIT_LAST_NAME:
            return self._handle_profile_edit_last_name_input(
                telegram_user_id=telegram_user_id,
                action_text=action_text,
            )
        if dialog_state == _STATE_PROFILE_EDIT_GENDER:
            return self._handle_profile_edit_gender_input(
                telegram_user_id=telegram_user_id,
                action_text=action_text,
            )
        if dialog_state == _STATE_PROFILE_EDIT_BIRTH_DATE:
            return self._handle_profile_edit_birth_date_input(
                telegram_user_id=telegram_user_id,
                action_text=action_text,
            )
        if dialog_state == _STATE_PROFILE_EDIT_EMAIL:
            return self._handle_profile_edit_email_input(
                telegram_user_id=telegram_user_id,
                action_text=action_text,
            )

        # Обработка callback'ов пагинации тикетов
        if action_text.startswith(USER_TICKETS_PREV_PAGE_PREFIX):
            try:
                page = int(action_text[len(USER_TICKETS_PREV_PAGE_PREFIX):])
            except ValueError:
                page = 1
            return self._show_user_tickets_page(
                telegram_user_id=telegram_user_id,
                page=page,
                per_page=5,
            )
        if action_text.startswith(USER_TICKETS_NEXT_PAGE_PREFIX):
            try:
                page = int(action_text[len(USER_TICKETS_NEXT_PAGE_PREFIX):])
            except ValueError:
                page = 1
            return self._show_user_tickets_page(
                telegram_user_id=telegram_user_id,
                page=page,
                per_page=5,
            )

        if action_text.startswith(USER_TICKET_REPLY_PREFIX):
            try:
                ticket_id_str = action_text[len(USER_TICKET_REPLY_PREFIX):]
                ticket_id = UUID(ticket_id_str)
            except ValueError:
                return TelegramMenuActionResult(
                    status="ticket_details_error",
                    message="Неверный идентификатор тикета.",
                )
            return self._begin_support_reply(
                telegram_user_id=telegram_user_id,
                ticket_id=ticket_id,
            )

        # Обработка нажатия на конкретный тикет для просмотра деталей
        if action_text.startswith(USER_TICKET_DETAILS_PREFIX):
            try:
                ticket_id_str = action_text[len(USER_TICKET_DETAILS_PREFIX):]
                ticket_id = UUID(ticket_id_str)
            except ValueError:
                return TelegramMenuActionResult(
                    status="ticket_details_error",
                    message="Неверный идентификатор тикета.",
                )
            return self._handle_view_ticket_details(
                telegram_user_id=telegram_user_id,
                ticket_id=ticket_id,
            )

        action = resolve_guest_menu_action(action_text)
        if action is None:
            method_logger.debug("Не удалось распознать действие меню.")
            if not normalize_menu_text(action_text):
                return TelegramMenuActionResult(
                    status="empty_action",
                    message="Пожалуйста, выберите действие через кнопки меню.",
                )
            return TelegramMenuActionResult(
                status="unknown_action",
                message=(
                    "Команда не распознана. Используйте кнопки меню: "
                    f"'{BUTTON_BALANCE}', '{BUTTON_VIRTUAL_CARD}', '{BUTTON_DELIVERY}', '{BUTTON_SUPPORT}', '{BUTTON_VACANCIES}', "
                    f"'{BUTTON_PROFILE}', '{BUTTON_HELP}', '{BUTTON_ABOUT}', '{BUTTON_MAIN_MENU}', "
                    f"'{BUTTON_SEND_PHONE}', '{BUTTON_ACCEPT_RULES}'."
                ),
            )

        if action in {GuestMenuAction.MAIN_MENU, GuestMenuAction.BACK_TO_MAIN}:
            return TelegramMenuActionResult(
                status="menu",
                message=self.build_menu_overview_message(
                    user_name=self._resolve_menu_user_name(telegram_user_id=telegram_user_id)
                ),
            )

        if action == GuestMenuAction.HELP:
            screen = build_help_screen()
            return TelegramMenuActionResult(
                status="help",
                message=screen.text,
                parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
            )

        if action == GuestMenuAction.ABOUT:
            screen = build_about_screen()
            return TelegramMenuActionResult(
                status="about",
                message=screen.text,
            )

        if action == GuestMenuAction.SHARE_CONTACT:
            return TelegramMenuActionResult(
                status="request_contact",
                message="Нажмите кнопку отправки контакта ниже и подтвердите ваш номер.",
                requires_contact_keyboard=True,
            )

        if action == GuestMenuAction.PROFILE:
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            return self._render_profile_screen(telegram_user_id=telegram_user_id)

        if action == GuestMenuAction.PROFILE_EDIT:
            return self._open_profile_edit_choice(telegram_user_id=telegram_user_id)

        if action == GuestMenuAction.PROFILE_EDIT_CANCEL:
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            return self._render_profile_screen(telegram_user_id=telegram_user_id)

        if action in {
            GuestMenuAction.PROFILE_EDIT_FIRST_NAME,
            GuestMenuAction.PROFILE_EDIT_LAST_NAME,
            GuestMenuAction.PROFILE_EDIT_GENDER,
            GuestMenuAction.PROFILE_EDIT_BIRTH_DATE,
            GuestMenuAction.PROFILE_EDIT_EMAIL,
            GuestMenuAction.PROFILE_EDIT_GENDER_MALE,
            GuestMenuAction.PROFILE_EDIT_GENDER_FEMALE,
        }:
            return self._open_profile_edit_choice(telegram_user_id=telegram_user_id)

        if action in {GuestMenuAction.SUPPORT, GuestMenuAction.BACK_TO_SUPPORT}:
            has_tickets = self._has_user_tickets(
                platform="telegram",
                external_id=str(telegram_user_id),
            )
            screen = build_support_menu_screen(has_tickets=has_tickets)
            return TelegramMenuActionResult(
                status="support",
                message=screen.text,
                parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
                has_support_tickets=has_tickets,
            )

        if action == GuestMenuAction.VACANCIES:
            screen = build_vacancies_screen()
            return TelegramMenuActionResult(
                status="vacancies",
                message=screen.text,
                parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
            )

        if action == GuestMenuAction.DELIVERY:
            screen = build_delivery_screen()
            return TelegramMenuActionResult(
                status="delivery",
                message=screen.text,
                parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
            )

        if action == GuestMenuAction.BUSINESS_LUNCH:
            screen = build_business_lunch_screen()
            return TelegramMenuActionResult(
                status="business_lunch",
                message=screen.text,
                parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
            )

        if action == GuestMenuAction.TABLE_BOOKING:
            screen = build_table_booking_screen()
            return TelegramMenuActionResult(
                status="table_booking",
                message=screen.text,
                parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
            )

        if action == GuestMenuAction.SUPPORT_FEEDBACK:
            screen = build_support_feedback_screen()
            has_tickets = self._has_user_tickets(
                platform="telegram",
                external_id=str(telegram_user_id),
            )
            return TelegramMenuActionResult(
                status="support_feedback",
                message=screen.text,
                parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
                has_support_tickets=has_tickets,
            )

        if action == GuestMenuAction.SUPPORT_QUESTION:
            has_tickets = self._has_user_tickets(
                platform="telegram",
                external_id=str(telegram_user_id),
            )
            
            if not has_tickets:
                # Если тикетов нет, переходим к созданию нового тикета
                self._dialog_state_by_user_id[telegram_user_id] = _STATE_WAITING_SUPPORT_QUESTION
                self._reply_ticket_id_by_user_id.pop(telegram_user_id, None)
                screen = build_support_question_screen()
                return TelegramMenuActionResult(
                    status="support_question_input",
                    message=screen.text,
                    parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
                    has_support_tickets=False,
                )
            else:
                # Если тикеты есть, показываем первую страницу списка тикетов
                return self._show_user_tickets_page(
                    telegram_user_id=telegram_user_id,
                    page=1,
                    per_page=5,
                )

        if action == GuestMenuAction.SUPPORT_QUESTION_FROM_LIST:
            # Всегда переходим к созданию нового тикета, независимо от наличия тикетов
            has_tickets = self._has_user_tickets(
                platform="telegram",
                external_id=str(telegram_user_id),
            )
            self._dialog_state_by_user_id[telegram_user_id] = _STATE_WAITING_SUPPORT_QUESTION
            self._reply_ticket_id_by_user_id.pop(telegram_user_id, None)
            screen = build_support_question_screen()
            return TelegramMenuActionResult(
                status="support_question_input",
                message=screen.text,
                parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
                has_support_tickets=has_tickets,
            )

        if action == GuestMenuAction.SUPPORT_CONTACTS:
            screen = build_support_contacts_screen()
            has_tickets = self._has_user_tickets(
                platform="telegram",
                external_id=str(telegram_user_id),
            )
            return TelegramMenuActionResult(
                status="support_contacts",
                message=screen.text,
                has_support_tickets=has_tickets,
            )

        if action == GuestMenuAction.BALANCE:
            return self._handle_balance_action(telegram_user_id=telegram_user_id)

        if action == GuestMenuAction.VIRTUAL_CARD:
            return self._handle_virtual_card_action(telegram_user_id=telegram_user_id)

        if action == GuestMenuAction.MY_TICKETS:
            # Показываем первую страницу тикетов с пагинацией
            return self._show_user_tickets_page(
                telegram_user_id=telegram_user_id,
                page=1,
                per_page=5,
            )

        return TelegramMenuActionResult(
            status="unknown_action",
            message=(
                "Команда не распознана. Используйте кнопки меню: "
                f"'{BUTTON_BALANCE}', '{BUTTON_VIRTUAL_CARD}', '{BUTTON_DELIVERY}', '{BUTTON_SUPPORT}', '{BUTTON_VACANCIES}', "
                f"'{BUTTON_PROFILE}', '{BUTTON_HELP}', '{BUTTON_ABOUT}', '{BUTTON_MAIN_MENU}', "
                f"'{BUTTON_SEND_PHONE}', '{BUTTON_ACCEPT_RULES}'."
            ),
        )

    def _handle_support_question_input(
        self,
        telegram_user_id: int,
        question_text: str,
    ) -> TelegramMenuActionResult:
        """Обрабатывает текст вопроса после шага `SUPPORT_QUESTION`."""

        question = str(question_text).strip()
        has_tickets = self._has_user_tickets(
            platform="telegram",
            external_id=str(telegram_user_id),
        )
        if not question:
            return TelegramMenuActionResult(
                status="support_question_empty",
                has_support_tickets=has_tickets,
                message="Пожалуйста, введите вопрос текстом, чтобы мы передали его модератору.",
            )

        self._dialog_state_by_user_id.pop(telegram_user_id, None)
        if self._create_support_ticket_use_case is None:
            return TelegramMenuActionResult(
                status="support_question_submitted",
                message=(
                    "📨 Ваш вопрос принят!\n"
                    "Модератор рассмотрит обращение в ближайшее время."
                ),
            )

        try:
            created = self._create_support_ticket_use_case.execute(
                CreateSupportTicketCommand(
                    platform="telegram",
                    external_id=str(telegram_user_id),
                    question_text=question,
                )
            )
        except ValueError as error:
            return TelegramMenuActionResult(
                status="support_question_error",
                has_support_tickets=has_tickets,
                message=(
                    "Не удалось зарегистрировать обращение в системе модерации.\n"
                    f"Причина: {error}"
                ),
            )

        short_id = self._format_ticket_id_short(created.ticket_id)
        return TelegramMenuActionResult(
            status="support_question_submitted",
            message=(
                "📨 Ваш вопрос принят!\n"
                f"🎫 Создан тикет #{short_id}\n"
                "Канал обращения: telegram\n"
                "Модератор рассмотрит обращение в ближайшее время."
            ),
        )

    def _begin_support_reply(
        self,
        *,
        telegram_user_id: int,
        ticket_id: UUID,
    ) -> TelegramMenuActionResult:
        """Переводит пользователя в режим ответа по выбранному тикету."""

        if self._add_guest_message_to_ticket_use_case is None:
            return TelegramMenuActionResult(
                status="support_reply_error",
                has_support_tickets=True,
                message="Функция ответа по обращению временно недоступна.",
            )

        if self._ticket_details_use_case is None:
            return TelegramMenuActionResult(
                status="ticket_details_error",
                message="Функционал просмотра деталей тикета временно недоступен.",
            )

        try:
            details, _messages = self._get_ticket_details_with_history(ticket_id)
        except ValueError as error:
            return TelegramMenuActionResult(
                status="ticket_details_error",
                message=f"Тикет не найден: {error}",
            )

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="telegram", external_id=str(telegram_user_id))
        )
        if person is None or person.person_id != details.person_id:
            return TelegramMenuActionResult(
                status="ticket_details_error",
                message="У вас нет доступа к этому тикету.",
            )

        if details.status == SupportTicketStatus.CLOSED:
            return TelegramMenuActionResult(
                status="support_reply_closed",
                has_support_tickets=True,
                message="Обращение уже закрыто. Откройте новое через пункт «❓ Мне только спросить».",
            )

        self._dialog_state_by_user_id[telegram_user_id] = _STATE_WAITING_SUPPORT_REPLY
        self._reply_ticket_id_by_user_id[telegram_user_id] = ticket_id
        short_id = self._format_ticket_id_short(ticket_id)
        return TelegramMenuActionResult(
            status="support_reply_input",
            has_support_tickets=True,
            message=(
                f"✍️ Введите ответ для обращения #{short_id}.\n"
                "Минимальная длина ответа: 10 символов."
            ),
        )

    def _handle_support_reply_input(
        self,
        *,
        telegram_user_id: int,
        message_text: str,
    ) -> TelegramMenuActionResult:
        """Обрабатывает ответ гостя в существующем обращении."""

        ticket_id = self._reply_ticket_id_by_user_id.get(telegram_user_id)
        if ticket_id is None:
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            return TelegramMenuActionResult(
                status="support_reply_error",
                has_support_tickets=True,
                message="Потерян контекст обращения. Откройте «📋 Мои обращения» и выберите тикет снова.",
            )

        reply_text = str(message_text).strip()
        if not reply_text:
            return TelegramMenuActionResult(
                status="support_reply_empty",
                has_support_tickets=True,
                message="Ответ не может быть пустым. Введите текст сообщения для модератора.",
            )

        if self._add_guest_message_to_ticket_use_case is None:
            return TelegramMenuActionResult(
                status="support_reply_error",
                has_support_tickets=True,
                message="Функция ответа по обращению временно недоступна.",
            )

        try:
            self._add_guest_message_to_ticket_use_case.execute(
                AddGuestMessageToTicketCommand(
                    platform="telegram",
                    external_id=str(telegram_user_id),
                    ticket_id=ticket_id,
                    message_text=reply_text,
                )
            )
        except ValueError as error:
            error_text = str(error)
            if "закрыт" in error_text.lower():
                self._dialog_state_by_user_id.pop(telegram_user_id, None)
                self._reply_ticket_id_by_user_id.pop(telegram_user_id, None)
                return TelegramMenuActionResult(
                    status="support_reply_closed",
                    has_support_tickets=True,
                    message="Обращение уже закрыто. Откройте новое через пункт «❓ Мне только спросить».",
                )
            return TelegramMenuActionResult(
                status="support_reply_error",
                has_support_tickets=True,
                message=(
                    "Не удалось добавить сообщение в обращение.\n"
                    f"Причина: {error_text}"
                ),
            )

        self._dialog_state_by_user_id.pop(telegram_user_id, None)
        self._reply_ticket_id_by_user_id.pop(telegram_user_id, None)
        short_id = self._format_ticket_id_short(ticket_id)
        return TelegramMenuActionResult(
            status="support_reply_submitted",
            has_support_tickets=True,
            message=(
                f"✅ Ответ по обращению #{short_id} отправлен модератору.\n"
                "Мы уведомим вас, когда поступит новый ответ."
            ),
        )

    def _render_profile_screen(self, *, telegram_user_id: int) -> TelegramMenuActionResult:
        """Возвращает экран профиля с кнопкой перехода в режим редактирования."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="telegram", external_id=str(telegram_user_id))
        )
        if person is None:
            screen = build_profile_not_found_screen()
            return TelegramMenuActionResult(
                status="not_registered",
                message=screen.text,
                requires_contact_keyboard=True,
            )
        screen = build_profile_screen(
            phone_e164=person.phone_e164,
            accounts_count=len(person.accounts),
            accounts_platforms=self._collect_account_platforms(person.accounts),
            first_name_input=person.first_name_input,
            last_name_input=person.last_name_input,
            gender=person.gender,
            birth_date=person.birth_date,
            email=person.email,
            rules_accepted=person.get_rules_accepted_for_platform("telegram"),
            rules_accepted_at=person.get_rules_accepted_at_for_platform("telegram"),
            notifications_allowed=person.get_notifications_allowed_for_platform("telegram"),
            notifications_allowed_at=person.get_notifications_allowed_at_for_platform("telegram"),
        )
        return TelegramMenuActionResult(
            status="profile",
            message=screen.text,
            parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
        )

    def _open_profile_edit_choice(self, *, telegram_user_id: int) -> TelegramMenuActionResult:
        """Открывает меню выбора редактируемого поля профиля."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="telegram", external_id=str(telegram_user_id))
        )
        if person is None:
            return self._render_profile_screen(telegram_user_id=telegram_user_id)

        can_edit_birth_date = person.birth_date is None
        self._dialog_state_by_user_id[telegram_user_id] = _STATE_PROFILE_EDIT_CHOICE
        screen = build_profile_edit_screen(can_edit_birth_date=can_edit_birth_date)
        return TelegramMenuActionResult(
            status="profile_edit",
            message=screen.text,
            parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
            can_edit_birth_date=can_edit_birth_date,
        )

    def _handle_profile_edit_choice_input(
        self,
        *,
        telegram_user_id: int,
        action_text: str,
    ) -> TelegramMenuActionResult:
        """Обрабатывает выбор поля редактирования профиля."""

        action = resolve_guest_menu_action(action_text)
        if action in {GuestMenuAction.PROFILE_EDIT_CANCEL, GuestMenuAction.BACK_TO_MAIN}:
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            return self._render_profile_screen(telegram_user_id=telegram_user_id)
        if action == GuestMenuAction.PROFILE_EDIT_FIRST_NAME:
            self._dialog_state_by_user_id[telegram_user_id] = _STATE_PROFILE_EDIT_FIRST_NAME
            return TelegramMenuActionResult(
                status="profile_edit_first_name",
                message="👤 Введите новое имя.",
            )
        if action == GuestMenuAction.PROFILE_EDIT_LAST_NAME:
            self._dialog_state_by_user_id[telegram_user_id] = _STATE_PROFILE_EDIT_LAST_NAME
            return TelegramMenuActionResult(
                status="profile_edit_last_name",
                message="👥 Введите новую фамилию.",
            )
        if action == GuestMenuAction.PROFILE_EDIT_GENDER:
            self._dialog_state_by_user_id[telegram_user_id] = _STATE_PROFILE_EDIT_GENDER
            return TelegramMenuActionResult(
                status="profile_edit_gender",
                message=build_profile_gender_screen().text,
            )
        if action == GuestMenuAction.PROFILE_EDIT_BIRTH_DATE:
            person = self._person_lookup_use_case.execute(
                GetPersonByAccountCommand(platform="telegram", external_id=str(telegram_user_id))
            )
            if person is None:
                self._dialog_state_by_user_id.pop(telegram_user_id, None)
                return self._render_profile_screen(telegram_user_id=telegram_user_id)
            if person.birth_date is not None:
                self._dialog_state_by_user_id.pop(telegram_user_id, None)
                return TelegramMenuActionResult(
                    status="profile_edit_birth_date_forbidden",
                    message=(
                        "🎂 Дата рождения уже заполнена и может быть указана только один раз.\n\n"
                        "Телефон менять нельзя. Другие поля можно обновить в режиме редактирования профиля."
                    ),
                )
            self._dialog_state_by_user_id[telegram_user_id] = _STATE_PROFILE_EDIT_BIRTH_DATE
            return TelegramMenuActionResult(
                status="profile_edit_birth_date",
                message="🎂 Введите дату рождения в формате ДД.ММ.ГГГГ.",
            )
        if action == GuestMenuAction.PROFILE_EDIT_EMAIL:
            self._dialog_state_by_user_id[telegram_user_id] = _STATE_PROFILE_EDIT_EMAIL
            return TelegramMenuActionResult(
                status="profile_edit_email",
                message="📧 Введите новый email.",
            )
        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="telegram", external_id=str(telegram_user_id))
        )
        can_edit_birth_date = person.birth_date is None if person is not None else True
        screen = build_profile_edit_screen(can_edit_birth_date=can_edit_birth_date)
        return TelegramMenuActionResult(
            status="profile_edit_invalid_choice",
            message=(
                "Выберите поле кнопкой из меню редактирования профиля.\n\n"
                f"{screen.text}"
            ),
            parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
            can_edit_birth_date=can_edit_birth_date,
        )

    def _handle_profile_edit_first_name_input(
        self,
        *,
        telegram_user_id: int,
        action_text: str,
    ) -> TelegramMenuActionResult:
        """Обрабатывает ввод имени в режиме редактирования профиля."""

        normalized_name = normalize_person_name(action_text)
        if normalized_name is None:
            return TelegramMenuActionResult(
                status="profile_edit_first_name_invalid",
                message=(
                    "⚠️ Не удалось сохранить имя.\n"
                    "Используйте только буквы, пробел и дефис (от 2 до 50 символов)."
                ),
            )
        return self._apply_profile_patch(
            telegram_user_id=telegram_user_id,
            first_name_input=normalized_name,
            success_status="profile_edit_first_name_saved",
            success_message="✅ Имя обновлено.\n\n",
        )

    def _handle_profile_edit_last_name_input(
        self,
        *,
        telegram_user_id: int,
        action_text: str,
    ) -> TelegramMenuActionResult:
        """Обрабатывает ввод фамилии в режиме редактирования профиля."""

        normalized_last_name = normalize_person_name(action_text)
        if normalized_last_name is None:
            return TelegramMenuActionResult(
                status="profile_edit_last_name_invalid",
                message=(
                    "⚠️ Не удалось сохранить фамилию.\n"
                    "Используйте только буквы, пробел и дефис (от 2 до 50 символов)."
                ),
            )
        return self._apply_profile_patch(
            telegram_user_id=telegram_user_id,
            last_name_input=normalized_last_name,
            success_status="profile_edit_last_name_saved",
            success_message="✅ Фамилия обновлена.\n\n",
        )

    def _handle_profile_edit_gender_input(
        self,
        *,
        telegram_user_id: int,
        action_text: str,
    ) -> TelegramMenuActionResult:
        """Обрабатывает выбор пола в режиме редактирования профиля."""

        action = resolve_guest_menu_action(action_text)
        gender: str | None = None
        if action == GuestMenuAction.PROFILE_EDIT_GENDER_MALE:
            gender = "male"
        elif action == GuestMenuAction.PROFILE_EDIT_GENDER_FEMALE:
            gender = "female"
        else:
            lowered = normalize_menu_text(action_text)
            if lowered in {"мужской", "м", "male"}:
                gender = "male"
            if lowered in {"женский", "ж", "female"}:
                gender = "female"
        if gender is None:
            return TelegramMenuActionResult(
                status="profile_edit_gender_invalid",
                message="⚠️ Выберите пол кнопками «👨 Мужской» или «👩 Женский».",
            )
        return self._apply_profile_patch(
            telegram_user_id=telegram_user_id,
            gender=gender,
            success_status="profile_edit_gender_saved",
            success_message="✅ Пол обновлен.\n\n",
        )

    def _handle_profile_edit_birth_date_input(
        self,
        *,
        telegram_user_id: int,
        action_text: str,
    ) -> TelegramMenuActionResult:
        """Обрабатывает ввод даты рождения в режиме редактирования профиля."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="telegram", external_id=str(telegram_user_id))
        )
        if person is None:
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            return self._render_profile_screen(telegram_user_id=telegram_user_id)
        if person.birth_date is not None:
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            return TelegramMenuActionResult(
                status="profile_edit_birth_date_forbidden",
                message=(
                    "🎂 Дата рождения уже заполнена и может быть указана только один раз.\n"
                    "Если есть ошибка в данных, обратитесь к администратору."
                ),
            )

        parsed_birth_date = parse_birth_date(action_text)
        if parsed_birth_date is None:
            return TelegramMenuActionResult(
                status="profile_edit_birth_date_invalid",
                message=(
                    "⚠️ Некорректная дата рождения.\n"
                    "Введите дату в формате ДД.ММ.ГГГГ и убедитесь, что она не в будущем."
                ),
            )
        return self._apply_profile_patch(
            telegram_user_id=telegram_user_id,
            birth_date=parsed_birth_date,
            success_status="profile_edit_birth_date_saved",
            success_message="✅ Дата рождения сохранена.\n\n",
        )

    def _handle_profile_edit_email_input(
        self,
        *,
        telegram_user_id: int,
        action_text: str,
    ) -> TelegramMenuActionResult:
        """Обрабатывает ввод email в режиме редактирования профиля."""

        normalized = normalize_email(action_text)
        if normalized is None:
            return TelegramMenuActionResult(
                status="profile_edit_email_invalid",
                message="⚠️ Укажите корректный email, например `name@example.com`.",
                parse_mode="Markdown",
            )
        return self._apply_profile_patch(
            telegram_user_id=telegram_user_id,
            email=normalized,
            success_status="profile_edit_email_saved",
            success_message="✅ Email обновлен.\n\n",
        )

    def _apply_profile_patch(
        self,
        *,
        telegram_user_id: int,
        success_status: str,
        success_message: str,
        first_name_input: str | None = None,
        last_name_input: str | None = None,
        gender: str | None = None,
        birth_date: date | None = None,
        email: str | None = None,
    ) -> TelegramMenuActionResult:
        """Применяет частичное обновление профиля через общий registration use-case."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="telegram", external_id=str(telegram_user_id))
        )
        if person is None:
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            return self._render_profile_screen(telegram_user_id=telegram_user_id)

        try:
            self._registration_use_case.execute(
                RegisterOrAttachAccountCommand(
                    platform="telegram",
                    external_id=str(telegram_user_id),
                    raw_phone=person.phone_e164,
                    is_registered=True,
                    first_name_input=first_name_input,
                    last_name_input=last_name_input,
                    gender=gender,
                    birth_date=birth_date,
                    email=email,
                )
            )
        except (IdentityConflictError, ValueError):
            return TelegramMenuActionResult(
                status="profile_edit_save_error",
                message=(
                    "❌ Не удалось сохранить изменения профиля.\n"
                    "Попробуйте ещё раз чуть позже."
                ),
            )

        self._dialog_state_by_user_id.pop(telegram_user_id, None)
        profile_result = self._render_profile_screen(telegram_user_id=telegram_user_id)
        return TelegramMenuActionResult(
            status=success_status,
            message=f"{success_message}{profile_result.message}",
            parse_mode=profile_result.parse_mode,
        )

    def _try_handle_moderator_command(
        self,
        *,
        action_text: str,
        telegram_user_id: int,
    ) -> TelegramMenuActionResult | None:
        """Пытается обработать команды модератора."""

        raw = (action_text or "").strip()
        lowered = raw.lower()
        if lowered == "/mod":
            return self._open_moderator_menu(telegram_user_id=telegram_user_id)
        return None

    def _try_handle_moderation_callback(
        self,
        *,
        telegram_user_id: int,
        action_text: str,
    ) -> TelegramMenuActionResult | None:
        """Пытается обработать callback-кнопки меню модератора."""

        raw = (action_text or "").strip()
        if not raw.startswith("mod_"):
            return None

        if raw == MOD_MAIN_CALLBACK:
            return self._open_moderator_menu(telegram_user_id=telegram_user_id)

        if not self._is_moderator_account(telegram_user_id=telegram_user_id):
            self._clear_moderator_state(telegram_user_id)
            return TelegramMenuActionResult(
                status="moderation_forbidden",
                message="Команда /mod доступна только модераторам.",
            )

        if (
            self._moderator_reply_use_case is None
            or self._ticket_details_use_case is None
            or self._list_open_tickets_use_case is None
        ):
            return TelegramMenuActionResult(
                status="moderation_unavailable",
                message="Меню модератора недоступно: не подключены сценарии модерации.",
            )

        if raw.startswith(MOD_LIST_PREFIX):
            filter_key = self._normalize_moderation_filter(raw[len(MOD_LIST_PREFIX):])
            return self._show_moderation_tickets_page(
                telegram_user_id=telegram_user_id,
                filter_key=filter_key,
                page=1,
            )

        if raw.startswith(MOD_PAGE_PREFIX):
            parsed_page = self._parse_moderation_page_payload(raw[len(MOD_PAGE_PREFIX):])
            if parsed_page is None:
                return self._show_moderation_tickets_page(
                    telegram_user_id=telegram_user_id,
                    filter_key=_MOD_FILTER_NEW,
                    page=1,
                )
            filter_key, page = parsed_page
            return self._show_moderation_tickets_page(
                telegram_user_id=telegram_user_id,
                filter_key=filter_key,
                page=page,
            )

        parsed_details = self._parse_moderation_ticket_payload(raw, MOD_TICKET_PREFIX)
        if parsed_details is not None:
            ticket_id, filter_key, page = parsed_details
            return self._build_moderation_ticket_details_result(
                ticket_id=ticket_id,
                filter_key=filter_key,
                page=page,
            )

        parsed_reply = self._parse_moderation_ticket_payload(raw, MOD_REPLY_PREFIX)
        if parsed_reply is not None:
            ticket_id, filter_key, page = parsed_reply
            return self._start_moderation_reply_from_callback(
                telegram_user_id=telegram_user_id,
                ticket_id=ticket_id,
                filter_key=filter_key,
                page=page,
            )

        parsed_take = self._parse_moderation_ticket_payload(raw, MOD_TAKE_PREFIX)
        if parsed_take is not None:
            ticket_id, filter_key, page = parsed_take
            return self._set_moderation_status_from_callback(
                telegram_user_id=telegram_user_id,
                ticket_id=ticket_id,
                new_status=SupportTicketStatus.IN_PROGRESS,
                filter_key=filter_key,
                page=page,
            )

        parsed_close = self._parse_moderation_ticket_payload(raw, MOD_CLOSE_PREFIX)
        if parsed_close is not None:
            ticket_id, filter_key, page = parsed_close
            return self._set_moderation_status_from_callback(
                telegram_user_id=telegram_user_id,
                ticket_id=ticket_id,
                new_status=SupportTicketStatus.CLOSED,
                filter_key=filter_key,
                page=page,
            )

        return TelegramMenuActionResult(
            status="moderation_menu_unknown",
            message="Не удалось распознать действие меню модератора.",
        )

    @staticmethod
    def _normalize_moderation_filter(raw_filter: str) -> str:
        """Нормализует фильтр списка обращений модератора."""

        normalized = (raw_filter or "").strip().lower()
        if normalized in _MOD_FILTER_ORDER:
            return normalized
        return _MOD_FILTER_NEW

    def _parse_moderation_page_payload(self, raw_payload: str) -> tuple[str, int] | None:
        """Разбирает callback пагинации `mod_page_<filter>_<page>`."""

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
        raw_callback: str,
        prefix: str,
    ) -> tuple[UUID, str, int] | None:
        """Разбирает callback с ticket_id в формате `<prefix><uuid>_<filter>_<page>`."""

        if not raw_callback.startswith(prefix):
            return None
        payload = raw_callback[len(prefix) :].strip()
        parts = payload.rsplit("_", maxsplit=2)
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
        telegram_user_id: int,
        filter_key: str,
        page: int,
        per_page: int = 5,
    ) -> TelegramMenuActionResult:
        """Возвращает страницу списка обращений модератора по выбранному фильтру."""

        if self._list_open_tickets_use_case is None:
            return TelegramMenuActionResult(
                status="moderation_unavailable",
                message="Список обращений недоступен: list-open-use-case не подключен.",
            )

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
            message = f"{title}:\nСейчас обращений в этой категории нет."
        else:
            lines = [f"{title}:"]
            for index, ticket in enumerate(page_tickets, start=1):
                status_emoji, status_text = self._format_ticket_status(ticket.status.value)
                created = ticket.created_at.strftime("%d.%m.%Y %H:%M") if ticket.created_at else "—"
                lines.append(
                    f"{index}. {status_emoji} #{self._format_ticket_id_short(ticket.ticket_id)}"
                    f" • {status_text} • {ticket.source_platform} • {created}"
                )
            lines.append("")
            lines.append(f"Страница {safe_page}/{total_pages}. Всего обращений: {total_items}.")
            message = "\n".join(lines)

        self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id[telegram_user_id] = {
            "filter": normalized_filter,
            "page": str(safe_page),
        }
        return TelegramMenuActionResult(
            status="moderation_tickets_page",
            message=message,
            moderation_filter=normalized_filter,
            moderation_page=safe_page,
            moderation_total_pages=total_pages,
            moderation_tickets=page_tickets,
        )

    def _build_moderation_ticket_details_result(
        self,
        *,
        ticket_id: UUID,
        filter_key: str,
        page: int,
    ) -> TelegramMenuActionResult:
        """Формирует карточку тикета модератора для callback-навигации."""

        try:
            details, messages = self._get_ticket_details_with_history(ticket_id)
        except ValueError as error:
            return TelegramMenuActionResult(
                status="moderation_details_error",
                message=f"Не удалось загрузить тикет: {error}",
                moderation_filter=self._normalize_moderation_filter(filter_key),
                moderation_page=max(int(page), 1),
            )

        status_value = getattr(details.status, "value", str(details.status))
        status_emoji, status_text = self._format_ticket_status(status_value)
        linked = ", ".join(details.linked_platforms) or "-"
        message_lines = [
            f"{status_emoji} <b>Тикет #{self._format_ticket_id_short(details.ticket_id)}</b>",
            f"🧾 <b>ID:</b> <code>{html.escape(str(details.ticket_id))}</code>",
            f"📌 <b>Статус:</b> {html.escape(status_text)}",
            f"🧭 <b>Канал создания:</b> {html.escape(details.source_platform)}",
            f"🔁 <b>Последний канал гостя:</b> {html.escape(details.last_guest_platform or '-')}",
            f"🔗 <b>Каналы гостя:</b> {html.escape(linked)}",
            "",
        ]
        message_lines.extend(self._format_ticket_history_lines(messages, use_html=True))
        return TelegramMenuActionResult(
            status="moderation_ticket_details",
            message="\n".join(message_lines),
            parse_mode="HTML",
            moderation_filter=self._normalize_moderation_filter(filter_key),
            moderation_page=max(int(page), 1),
            moderation_ticket_id=ticket_id,
            moderation_ticket_status=status_value,
        )

    def _start_moderation_reply_from_callback(
        self,
        *,
        telegram_user_id: int,
        ticket_id: UUID,
        filter_key: str,
        page: int,
    ) -> TelegramMenuActionResult:
        """Переводит модератора в режим ввода ответа из карточки тикета."""

        if self._ticket_details_use_case is None:
            return TelegramMenuActionResult(
                status="moderation_details_unavailable",
                message="Карточка тикета недоступна: details-use-case не подключен.",
            )
        try:
            self._ticket_details_use_case.execute(ticket_id)
        except ValueError as error:
            return TelegramMenuActionResult(
                status="moderation_details_error",
                message=f"Не удалось найти тикет: {error}",
            )

        self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_WAIT_REPLY_TEXT
        self._moderator_context_by_user_id[telegram_user_id] = {
            "ticket_id": str(ticket_id),
            "filter": self._normalize_moderation_filter(filter_key),
            "page": str(max(int(page), 1)),
        }
        return TelegramMenuActionResult(
            status="moderation_wait_reply_text",
            message=(
                "Введите текст ответа модератора.\n"
                "Отправьте ответ одним сообщением."
            ),
        )

    def _set_moderation_status_from_callback(
        self,
        *,
        telegram_user_id: int,
        ticket_id: UUID,
        new_status: SupportTicketStatus,
        filter_key: str,
        page: int,
    ) -> TelegramMenuActionResult:
        """Меняет статус тикета из callback-кнопки карточки и возвращает обновленную карточку."""

        if self._set_ticket_status_use_case is None:
            return TelegramMenuActionResult(
                status="moderation_status_unavailable",
                message="Изменение статуса тикета временно недоступно.",
            )

        try:
            result = self._set_ticket_status_use_case.execute(
                SetSupportTicketStatusCommand(
                    ticket_id=ticket_id,
                    status=new_status,
                )
            )
        except ValueError as error:
            return TelegramMenuActionResult(
                status="moderation_status_error",
                message=f"Не удалось изменить статус тикета: {error}",
            )

        self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id[telegram_user_id] = {
            "filter": self._normalize_moderation_filter(filter_key),
            "page": str(max(int(page), 1)),
        }
        details_result = self._build_moderation_ticket_details_result(
            ticket_id=result.ticket_id,
            filter_key=filter_key,
            page=page,
        )
        _, previous_status_text = self._format_ticket_status(result.previous_status.value)
        _, new_status_text = self._format_ticket_status(result.new_status.value)
        return TelegramMenuActionResult(
            status=details_result.status,
            message=(
                f"✅ Статус обновлен: {previous_status_text} → {new_status_text}.\n\n"
                f"{details_result.message}"
            ),
            parse_mode=details_result.parse_mode,
            moderation_filter=details_result.moderation_filter,
            moderation_page=details_result.moderation_page,
            moderation_ticket_id=details_result.moderation_ticket_id,
            moderation_ticket_status=details_result.moderation_ticket_status,
        )

    def _open_moderator_menu(self, *, telegram_user_id: int) -> TelegramMenuActionResult:
        """Открывает единое меню модератора."""

        if not self._is_moderator_account(telegram_user_id=telegram_user_id):
            self._clear_moderator_state(telegram_user_id)
            return TelegramMenuActionResult(
                status="moderation_forbidden",
                message="Команда /mod доступна только модераторам.",
            )

        if self._moderator_reply_use_case is None or self._ticket_details_use_case is None:
            return TelegramMenuActionResult(
                status="moderation_unavailable",
                message="Меню модератора недоступно: не подключены сценарии модерации.",
            )

        self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id[telegram_user_id] = {
            "filter": _MOD_FILTER_NEW,
            "page": "1",
        }
        return TelegramMenuActionResult(
            status="moderation_menu",
            message=self._build_moderation_menu_text(),
        )

    def _handle_moderator_state_input(
        self,
        *,
        telegram_user_id: int,
        action_text: str,
    ) -> TelegramMenuActionResult:
        """Обрабатывает ввод модератора внутри FSM-режима."""

        state = self._moderator_state_by_user_id.get(telegram_user_id)
        if state is None:
            return TelegramMenuActionResult(
                status="moderation_state_missing",
                message=self._build_moderation_menu_text(),
            )

        raw = (action_text or "").strip()
        lowered = raw.lower()

        if lowered in {"отмена", "/cancel", "/mod", "меню"}:
            self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_MENU
            self._moderator_context_by_user_id.pop(telegram_user_id, None)
            return TelegramMenuActionResult(
                status="moderation_menu",
                message=self._build_moderation_menu_text(),
            )

        if lowered in {"выход", "0"}:
            self._clear_moderator_state(telegram_user_id)
            return TelegramMenuActionResult(
                status="moderation_closed",
                message="Режим модератора завершен. Для повторного входа используйте /mod.",
            )

        if state == _STATE_MOD_MENU:
            return self._handle_moderator_menu_choice(
                telegram_user_id=telegram_user_id,
                lowered_text=lowered,
            )

        if state == _STATE_MOD_WAIT_TICKET_FOR_REPLY:
            return self._handle_moderator_wait_ticket_for_reply(
                telegram_user_id=telegram_user_id,
                raw_ticket_id=raw,
            )

        if state == _STATE_MOD_WAIT_REPLY_TEXT:
            return self._handle_moderator_wait_reply_text(
                telegram_user_id=telegram_user_id,
                raw_message=raw,
            )

        if state == _STATE_MOD_WAIT_TICKET_FOR_DETAILS:
            return self._handle_moderator_wait_ticket_for_details(
                telegram_user_id=telegram_user_id,
                raw_ticket_id=raw,
            )
        if state == _STATE_MOD_WAIT_TICKET_FOR_CLOSE:
            return self._handle_moderator_wait_ticket_for_status_change(
                telegram_user_id=telegram_user_id,
                raw_ticket_id=raw,
                new_status=SupportTicketStatus.CLOSED,
            )
        if state == _STATE_MOD_WAIT_TICKET_FOR_IN_PROGRESS:
            return self._handle_moderator_wait_ticket_for_status_change(
                telegram_user_id=telegram_user_id,
                raw_ticket_id=raw,
                new_status=SupportTicketStatus.IN_PROGRESS,
            )

        self._clear_moderator_state(telegram_user_id)
        return TelegramMenuActionResult(
            status="moderation_state_error",
            message="Состояние модератора сброшено. Откройте меню заново через /mod.",
        )

    def _handle_moderator_menu_choice(
        self,
        *,
        telegram_user_id: int,
        lowered_text: str,
    ) -> TelegramMenuActionResult:
        """Обрабатывает выбор пункта главного меню модератора."""

        if lowered_text in {"1", "тикеты", "список"}:
            return self._show_moderation_tickets_page(
                telegram_user_id=telegram_user_id,
                filter_key=_MOD_FILTER_NEW,
                page=1,
            )

        if lowered_text in {"2", "ответ", "ответить"}:
            self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_WAIT_TICKET_FOR_REPLY
            self._moderator_context_by_user_id.pop(telegram_user_id, None)
            return TelegramMenuActionResult(
                status="moderation_wait_ticket_for_reply",
                message=(
                    "Введите UUID тикета, для которого нужно отправить ответ.\n"
                    "Для отмены отправьте «Отмена»."
                ),
            )

        if lowered_text in {"3", "карточка", "детали"}:
            self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_WAIT_TICKET_FOR_DETAILS
            self._moderator_context_by_user_id.pop(telegram_user_id, None)
            return TelegramMenuActionResult(
                status="moderation_wait_ticket_for_details",
                message=(
                    "Введите UUID тикета, чтобы показать карточку обращения.\n"
                    "Для отмены отправьте «Отмена»."
                ),
            )

        if lowered_text in {"4", "в работе", "работа", "активные"}:
            return self._show_moderation_tickets_page(
                telegram_user_id=telegram_user_id,
                filter_key=_MOD_FILTER_WORK,
                page=1,
            )

        if lowered_text in {"5", "закрытые", "архив"}:
            return self._show_moderation_tickets_page(
                telegram_user_id=telegram_user_id,
                filter_key=_MOD_FILTER_CLOSED,
                page=1,
            )

        if lowered_text in {"6", "закрыть", "close"}:
            self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_WAIT_TICKET_FOR_CLOSE
            self._moderator_context_by_user_id.pop(telegram_user_id, None)
            return TelegramMenuActionResult(
                status="moderation_wait_ticket_for_close",
                message=(
                    "Введите UUID тикета, который нужно закрыть.\n"
                    "Для отмены отправьте «Отмена»."
                ),
            )

        if lowered_text in {"7", "вработу", "в_работу", "take"}:
            self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_WAIT_TICKET_FOR_IN_PROGRESS
            self._moderator_context_by_user_id.pop(telegram_user_id, None)
            return TelegramMenuActionResult(
                status="moderation_wait_ticket_for_in_progress",
                message=(
                    "Введите UUID тикета, который нужно перевести в статус «В работе».\n"
                    "Для отмены отправьте «Отмена»."
                ),
            )

        return TelegramMenuActionResult(
            status="moderation_menu_unknown",
            message=(
                "Не удалось распознать пункт меню модератора.\n"
                f"{self._build_moderation_menu_text()}"
            ),
        )

    def _handle_moderator_wait_ticket_for_reply(
        self,
        *,
        telegram_user_id: int,
        raw_ticket_id: str,
    ) -> TelegramMenuActionResult:
        """Обрабатывает ввод ticket_id перед отправкой модераторского ответа."""

        ticket_id = self._parse_ticket_id(raw_ticket_id)
        if ticket_id is None:
            return TelegramMenuActionResult(
                status="moderation_bad_ticket",
                message="Некорректный ticket_id. Ожидается UUID.",
            )

        if self._ticket_details_use_case is None:
            return TelegramMenuActionResult(
                status="moderation_details_unavailable",
                message="Меню модератора недоступно: details-use-case не подключен.",
            )

        try:
            self._ticket_details_use_case.execute(ticket_id)
        except ValueError as error:
            return TelegramMenuActionResult(
                status="moderation_details_error",
                message=f"Не удалось найти тикет: {error}",
            )

        self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_WAIT_REPLY_TEXT
        self._moderator_context_by_user_id[telegram_user_id] = {"ticket_id": str(ticket_id)}
        return TelegramMenuActionResult(
            status="moderation_wait_reply_text",
            message=(
                "Введите текст ответа модератора.\n"
                "Отправьте ответ одним сообщением."
            ),
        )

    def _handle_moderator_wait_reply_text(
        self,
        *,
        telegram_user_id: int,
        raw_message: str,
    ) -> TelegramMenuActionResult:
        """Обрабатывает ввод текста ответа модератора в FSM-режиме."""

        context = self._moderator_context_by_user_id.get(telegram_user_id, {})
        raw_ticket_id = context.get("ticket_id")
        if raw_ticket_id is None:
            self._clear_moderator_state(telegram_user_id)
            return TelegramMenuActionResult(
                status="moderation_state_error",
                message="Потерян ticket_id в состоянии модератора. Откройте /mod заново.",
            )

        parsed = self._parse_target_and_reply_text(raw_message)
        if parsed is None:
            return TelegramMenuActionResult(
                status="moderation_empty_reply",
                message="Текст ответа модератора не может быть пустым.",
            )
        preferred_target, message_text = parsed
        if preferred_target is not None and preferred_target not in SUPPORTED_PLATFORMS:
            return TelegramMenuActionResult(
                status="moderation_bad_platform",
                message="Недопустимая целевая платформа в --to.",
            )

        if self._moderator_reply_use_case is None:
            return TelegramMenuActionResult(
                status="moderation_unavailable",
                message="Маршрутизация ответа модератора пока недоступна.",
            )

        try:
            route = self._moderator_reply_use_case.execute(
                ModeratorReplyCommand(
                    ticket_id=UUID(raw_ticket_id),
                    moderator_platform="telegram",
                    reply_text=message_text,
                    preferred_target_platform=preferred_target,  # type: ignore[arg-type]
                )
            )
        except ValueError as error:
            return TelegramMenuActionResult(
                status="moderation_error",
                message=f"Не удалось маршрутизировать ответ: {error}",
            )

        filter_key = self._normalize_moderation_filter(context.get("filter", _MOD_FILTER_NEW))
        try:
            page = max(int(context.get("page", "1")), 1)
        except ValueError:
            page = 1
        self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id.pop(telegram_user_id, None)

        details_result = self._build_moderation_ticket_details_result(
            ticket_id=route.ticket_id,
            filter_key=filter_key,
            page=page,
        )
        if details_result.status == "moderation_ticket_details":
            return TelegramMenuActionResult(
                status=details_result.status,
                message=(
                    "Ответ модератора зарегистрирован.\n"
                    f"Маршрут доставки: {route.target_platform} ({route.target_external_id})\n\n"
                    f"{details_result.message}"
                ),
                parse_mode=details_result.parse_mode,
                moderation_filter=details_result.moderation_filter,
                moderation_page=details_result.moderation_page,
                moderation_ticket_id=details_result.moderation_ticket_id,
                moderation_ticket_status=details_result.moderation_ticket_status,
            )

        return TelegramMenuActionResult(
            status="moderation_routed",
            message=(
                "Ответ модератора зарегистрирован.\n"
                f"Тикет: {route.ticket_id}\n"
                f"Канал исходного обращения: {route.guest_source_platform}\n"
                f"Маршрут доставки: {route.target_platform} ({route.target_external_id})\n"
                f"ID сообщения: {route.message_id}\n\n"
                f"{self._build_moderation_menu_text()}"
            ),
        )

    def _handle_moderator_wait_ticket_for_details(
        self,
        *,
        telegram_user_id: int,
        raw_ticket_id: str,
    ) -> TelegramMenuActionResult:
        """Обрабатывает ввод ticket_id для показа карточки тикета."""

        ticket_id = self._parse_ticket_id(raw_ticket_id)
        if ticket_id is None:
            return TelegramMenuActionResult(
                status="moderation_details_bad_ticket",
                message="Некорректный ticket_id. Ожидается UUID.",
            )

        if self._ticket_details_use_case is None:
            return TelegramMenuActionResult(
                status="moderation_details_unavailable",
                message="Команда карточки тикета пока недоступна: details-use-case не подключен.",
            )

        try:
            details, messages = self._get_ticket_details_with_history(ticket_id)
        except ValueError as error:
            return TelegramMenuActionResult(
                status="moderation_details_error",
                message=f"Не удалось загрузить тикет: {error}",
            )

        self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id.pop(telegram_user_id, None)
        status_value = getattr(details.status, "value", str(details.status))
        status_emoji, status_text = self._format_ticket_status(status_value)
        linked = ", ".join(details.linked_platforms) or "-"
        message_lines = [
            f"{status_emoji} <b>Тикет #{self._format_ticket_id_short(details.ticket_id)}</b>",
            f"🧾 <b>ID:</b> <code>{html.escape(str(details.ticket_id))}</code>",
            f"📌 <b>Статус:</b> {html.escape(status_text)}",
            f"🧭 <b>Канал создания:</b> {html.escape(details.source_platform)}",
            f"🔁 <b>Последний канал гостя:</b> {html.escape(details.last_guest_platform or '-')}",
            f"🔗 <b>Каналы гостя:</b> {html.escape(linked)}",
            "",
        ]
        message_lines.extend(self._format_ticket_history_lines(messages, use_html=True))
        message_lines.extend(["", self._build_moderation_menu_text()])
        return TelegramMenuActionResult(
            status="moderation_details",
            message="\n".join(message_lines),
            parse_mode="HTML",
        )

    def _handle_moderator_wait_ticket_for_status_change(
        self,
        *,
        telegram_user_id: int,
        raw_ticket_id: str,
        new_status: SupportTicketStatus,
    ) -> TelegramMenuActionResult:
        """Обрабатывает ввод ticket_id для смены статуса тикета."""

        ticket_id = self._parse_ticket_id(raw_ticket_id)
        if ticket_id is None:
            return TelegramMenuActionResult(
                status="moderation_status_bad_ticket",
                message="Некорректный ticket_id. Ожидается UUID.",
            )

        if self._set_ticket_status_use_case is None:
            return TelegramMenuActionResult(
                status="moderation_status_unavailable",
                message="Изменение статуса тикета временно недоступно.",
            )

        try:
            result = self._set_ticket_status_use_case.execute(
                SetSupportTicketStatusCommand(
                    ticket_id=ticket_id,
                    status=new_status,
                )
            )
        except ValueError as error:
            return TelegramMenuActionResult(
                status="moderation_status_error",
                message=f"Не удалось изменить статус тикета: {error}",
            )

        self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id.pop(telegram_user_id, None)
        _, previous_status_text = self._format_ticket_status(result.previous_status.value)
        _, new_status_text = self._format_ticket_status(result.new_status.value)
        short_id = self._format_ticket_id_short(result.ticket_id)
        return TelegramMenuActionResult(
            status="moderation_status_updated",
            message=(
                f"✅ Статус тикета #{short_id} обновлен: {previous_status_text} → {new_status_text}.\n\n"
                f"{self._build_moderation_menu_text()}"
            ),
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
                f"канал={ticket.source_platform} | "
                f"последний={ticket.last_guest_platform or '-'} | "
                f"статус={status_text}"
            )
        return "\n".join(lines)

    def _handle_balance_action(self, *, telegram_user_id: int) -> TelegramMenuActionResult:
        """Обрабатывает пункт меню «Мой баланс» через общий use-case лояльности."""

        if self._balance_use_case is None:
            return TelegramMenuActionResult(
                status="balance_unavailable",
                message=(
                    "❌ Сервис бонусов временно недоступен.\n"
                    "Код ошибки: IIKO-BAL-000.\n"
                    "Покажите это сообщение сотруднику и попробуйте позже."
                ),
            )

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(
                platform="telegram",
                external_id=str(telegram_user_id),
            )
        )
        if person is None:
            screen = build_profile_not_found_screen()
            return TelegramMenuActionResult(
                status="not_registered",
                message=screen.text,
                requires_contact_keyboard=True,
            )

        result = self._balance_use_case.execute(phone_e164=person.phone_e164)
        return TelegramMenuActionResult(
            status=result.status,
            message=result.message,
            parse_mode="Markdown" if result.parse_mode == "markdown" else None,
        )

    def _handle_virtual_card_action(self, *, telegram_user_id: int) -> TelegramMenuActionResult:
        """Обрабатывает пункт меню «Виртуальная карта» через общий use-case лояльности."""

        if self._virtual_card_use_case is None:
            return TelegramMenuActionResult(
                status="virtual_card_unavailable",
                message=(
                    "❌ Сервис виртуальной карты временно недоступен.\n"
                    "Код ошибки: IIKO-CARD-000.\n"
                    "Покажите это сообщение сотруднику и попробуйте позже."
                ),
            )

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(
                platform="telegram",
                external_id=str(telegram_user_id),
            )
        )
        if person is None:
            screen = build_profile_not_found_screen()
            return TelegramMenuActionResult(
                status="not_registered",
                message=screen.text,
                requires_contact_keyboard=True,
            )

        result = self._virtual_card_use_case.execute(phone_e164=person.phone_e164)
        if result.status == "virtual_card" and result.card_numbers:
            followup_screen = build_virtual_card_result_screen()
            return TelegramMenuActionResult(
                status=result.status,
                message=followup_screen.text,
                parse_mode=None,
                virtual_card_numbers=result.card_numbers,
            )

        return TelegramMenuActionResult(
            status=result.status,
            message=result.message,
            parse_mode="Markdown" if result.parse_mode == "markdown" else None,
            virtual_card_numbers=result.card_numbers,
        )

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

    def _resolve_menu_user_name(self, *, telegram_user_id: int, person: object | None = None) -> str:
        """Возвращает имя для приветствия в главном меню."""

        resolved_person = person
        if resolved_person is None:
            resolved_person = self._person_lookup_use_case.execute(
                GetPersonByAccountCommand(platform="telegram", external_id=str(telegram_user_id))
            )
        first_name = getattr(resolved_person, "first_name_input", None)
        if isinstance(first_name, str):
            normalized = first_name.strip()
            if normalized:
                return normalized
        return "Гость"

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

    def _handle_modreply_command(self, raw: str) -> TelegramMenuActionResult:
        """Обрабатывает команду `/modreply`."""

        if self._moderator_reply_use_case is None:
            return TelegramMenuActionResult(
                status="moderation_unavailable",
                message=(
                    "Команда модерации пока недоступна: сценарий маршрутизации не подключен."
                ),
            )

        parts = raw.split()
        if len(parts) < 3:
            return TelegramMenuActionResult(
                status="moderation_usage",
                message="Формат: /modreply <ticket_id> [--to=telegram|vk|max] <текст ответа>",
            )

        ticket_id = self._parse_ticket_id(parts[1])
        if ticket_id is None:
            return TelegramMenuActionResult(
                status="moderation_bad_ticket",
                message="Некорректный ticket_id. Ожидается UUID.",
            )

        preferred_target: str | None = None
        message_start_index = 2
        if len(parts) >= 4 and parts[2].lower().startswith("--to="):
            preferred_target = parts[2].split("=", maxsplit=1)[1].strip().lower()
            message_start_index = 3

        message_text = " ".join(parts[message_start_index:]).strip()
        if not message_text:
            return TelegramMenuActionResult(
                status="moderation_empty_reply",
                message="Текст ответа модератора не может быть пустым.",
            )

        if preferred_target is not None and preferred_target not in SUPPORTED_PLATFORMS:
            return TelegramMenuActionResult(
                status="moderation_bad_platform",
                message="Недопустимая целевая платформа в --to.",
            )

        try:
            route = self._moderator_reply_use_case.execute(
                ModeratorReplyCommand(
                    ticket_id=ticket_id,
                    moderator_platform="telegram",
                    reply_text=message_text,
                    preferred_target_platform=preferred_target,  # type: ignore[arg-type]
                )
            )
        except ValueError as error:
            return TelegramMenuActionResult(
                status="moderation_error",
                message=f"Не удалось маршрутизировать ответ: {error}",
            )

        return TelegramMenuActionResult(
            status="moderation_routed",
            message=(
                "Ответ модератора зарегистрирован.\n"
                f"Тикет: {route.ticket_id}\n"
                f"Канал исходного обращения: {route.guest_source_platform}\n"
                f"Маршрут доставки: {route.target_platform} ({route.target_external_id})\n"
                f"ID сообщения: {route.message_id}"
            ),
        )

    def _handle_modticket_command(self, raw: str) -> TelegramMenuActionResult:
        """Обрабатывает команду `/modticket`."""

        if self._ticket_details_use_case is None:
            return TelegramMenuActionResult(
                status="moderation_details_unavailable",
                message="Команда карточки тикета пока недоступна: details-use-case не подключен.",
            )

        parts = raw.split()
        if len(parts) != 2:
            return TelegramMenuActionResult(
                status="moderation_details_usage",
                message="Формат: /modticket <ticket_id>",
            )

        ticket_id = self._parse_ticket_id(parts[1])
        if ticket_id is None:
            return TelegramMenuActionResult(
                status="moderation_details_bad_ticket",
                message="Некорректный ticket_id. Ожидается UUID.",
            )

        try:
            details = self._ticket_details_use_case.execute(ticket_id)
        except ValueError as error:
            return TelegramMenuActionResult(
                status="moderation_details_error",
                message=f"Не удалось загрузить тикет: {error}",
            )

        linked = ", ".join(details.linked_platforms)
        return TelegramMenuActionResult(
            status="moderation_details",
            message=(
                f"Тикет: {details.ticket_id}\n"
                f"Статус: {details.status}\n"
                f"Канал создания: {details.source_platform}\n"
                f"Последний канал гостя: {details.last_guest_platform or '-'}\n"
                f"Каналы гостя: {linked}"
            ),
        )

    def _clear_moderator_state(self, telegram_user_id: int) -> None:
        """Очищает модераторское FSM-состояние пользователя."""

        self._moderator_state_by_user_id.pop(telegram_user_id, None)
        self._moderator_context_by_user_id.pop(telegram_user_id, None)

    def _is_moderator_account(self, *, telegram_user_id: int) -> bool:
        """Проверяет признак модератора по профилю strict identity в БД."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(
                platform="telegram",
                external_id=str(telegram_user_id),
            )
        )
        if person is None:
            return False
        return bool(getattr(person, "is_moderator", False))

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
        telegram_user_id: int,
        page: int = 1,
        per_page: int = 5,
    ) -> TelegramMenuActionResult:
        """Показывает страницу тикетов пользователя с пагинацией."""

        if self._get_person_tickets_page_use_case is None:
            # Fallback: используем старый метод без пагинации
            tickets = self._list_user_tickets(
                platform="telegram",
                external_id=str(telegram_user_id),
                limit=10,
            )
            if not tickets:
                return TelegramMenuActionResult(
                    status="tickets_empty",
                    message=(
                        "📭 У вас пока нет обращений.\n\n"
                        "Нажмите «❓ Мне только спросить», чтобы задать вопрос."
                    ),
                    has_support_tickets=False,
                    current_page=1,
                    total_pages=1,
                    tickets=(),
                )
            return TelegramMenuActionResult(
                status="tickets_list",
                message=self._format_person_tickets_message(tickets),
                has_support_tickets=True,
                current_page=1,
                total_pages=1,
                tickets=tickets,
            )

        try:
            page_result = self._get_person_tickets_page_use_case.execute(
                platform="telegram",
                external_id=str(telegram_user_id),
                page=page,
                per_page=per_page,
            )
        except ValueError:
            return TelegramMenuActionResult(
                status="tickets_error",
                message="Произошла ошибка при загрузке обращений.",
                has_support_tickets=False,
                tickets=(),
            )

        if not page_result.tickets:
            return TelegramMenuActionResult(
                status="tickets_empty",
                message=(
                    "📭 У вас пока нет обращений.\n\n"
                    "Нажмите «❓ Мне только спросить», чтобы задать вопрос."
                ),
                has_support_tickets=False,
                current_page=page,
                total_pages=page_result.total_pages,
                tickets=(),
            )

        # Форматируем сообщение с пагинацией
        message = self._format_person_tickets_page_message(page_result)
        return TelegramMenuActionResult(
            status="tickets_list",
            message=message,
            has_support_tickets=True,
            current_page=page_result.page,
            total_pages=page_result.total_pages,
            tickets=page_result.tickets,
        )

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
    def _format_ticket_history_lines(messages: tuple[object, ...], *, use_html: bool = False) -> list[str]:
        """Форматирует блок истории переписки тикета."""

        lines: list[str] = ["📨 <b>История переписки:</b>" if use_html else "📨 История переписки:"]
        if not messages:
            lines.append("Сообщений в тикете пока нет.")
            return lines

        for message in messages:
            author_value = getattr(getattr(message, "author", None), "value", "")
            if use_html:
                author_label = "👤 <b>Гость</b>" if author_value == "guest" else "👨‍💼 <b>Модератор</b>"
            else:
                author_label = "👤 Гость" if author_value == "guest" else "👨‍💼 Модератор"
            source_platform = str(getattr(message, "source_platform", "-"))
            created_at = getattr(message, "created_at", None)
            created_at_text = created_at.strftime("%d.%m.%Y %H:%M") if created_at else "время не указано"
            body = str(getattr(message, "body", "")).strip() or "—"
            if use_html:
                lines.append(f"[{html.escape(created_at_text)}] {author_label} ({html.escape(source_platform)}):")
                lines.append(f"<blockquote>{html.escape(body)}</blockquote>")
                continue

            lines.append(f"[{created_at_text}] {author_label} ({source_platform}):")
            for line in body.splitlines():
                lines.append(f"» {line}" if line.strip() else "»")

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
            short_id = TelegramIdentityAdapter._format_ticket_id_short(ticket.ticket_id)
            lines.append(
                f"{i}. {status_emoji.get(ticket.status.value, '❓')} #{short_id} от {created_at}: {short_status}"
            )
        
        lines.append("\nℹ️ Для просмотра деталей тикета или ответа используйте кнопки ниже.")
        return "\n".join(lines)

    @staticmethod
    def _normalize_first_name(raw_text: str) -> str | None:
        """Проверяет и нормализует имя пользователя для шага сокращенной регистрации."""

        return normalize_person_name(raw_text)

    def _prefill_profile_from_loyalty(self, *, telegram_user_id: int, person):
        """Дозаполняет пустые поля профиля данными iiko в legacy-ветке, не перезаписывая локальные значения."""

        if self._loyalty_gateway is None:
            return person

        method_logger = self._logger.bind(stage="legacy_loyalty_prefill", user_id=str(telegram_user_id))
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
                    platform="telegram",
                    external_id=str(telegram_user_id),
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

    def _finalize_iiko_sync_step(
        self,
        *,
        telegram_user_id: int,
        phone_e164: str,
        first_name: str,
    ) -> TelegramMenuActionResult:
        """Выполняет синхронизацию с iiko и завершает onboarding только при успехе."""

        registration_card_numbers = self._sync_registration_with_loyalty(
            phone_e164=phone_e164,
            profile=self._build_loyalty_upsert_profile(telegram_user_id=telegram_user_id),
        )
        if not registration_card_numbers and self._virtual_card_use_case is not None:
            retry_screen = build_iiko_sync_retry_screen()
            self._onboarding_state_by_user_id[telegram_user_id] = OnboardingState.WAITING_IIKO_SYNC
            return TelegramMenuActionResult(
                status="iiko_sync_retry",
                message=retry_screen.text,
            )

        self._onboarding_state_by_user_id.pop(telegram_user_id, None)
        self._onboarding_draft_by_user_id.pop(telegram_user_id, None)
        self._dialog_state_by_user_id.pop(telegram_user_id, None)
        self._clear_moderator_state(telegram_user_id)
        completion_message = self._build_registration_completion_message(
            user_name=first_name,
            has_cards=bool(registration_card_numbers),
        )
        return TelegramMenuActionResult(
            status="menu",
            message=completion_message,
            virtual_card_numbers=registration_card_numbers,
        )

    def _build_registration_completion_message(self, *, user_name: str, has_cards: bool) -> str:
        """Формирует итоговый текст после успешной синхронизации с iiko."""

        completion_parts = ["✅ Регистрация успешно завершена."]
        if has_cards:
            completion_parts.append("🪪 Выше представлены QR-коды ваших карт.")
        completion_parts.extend(
            [
                "ℹ️ Подробности анкеты и информацию профиля можно посмотреть и изменить в разделе «👤 Профиль».",
                self.build_menu_overview_message(user_name=user_name),
            ]
        )
        return "\n\n".join(completion_parts)

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

    def _build_loyalty_upsert_profile(self, *, telegram_user_id: int) -> LoyaltyCustomerUpsertData | None:
        """Готовит профиль для create_or_update в iiko на шаге завершения регистрации."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="telegram", external_id=str(telegram_user_id))
        )
        if person is None:
            return None

        return LoyaltyCustomerUpsertData(
            first_name=person.first_name_input,
            last_name=person.last_name_input,
            gender=person.gender,
            birth_date=person.birth_date,
            email=person.email,
            rules_accepted=person.get_rules_accepted_for_platform("telegram"),
            notifications_allowed=person.get_notifications_allowed_for_platform("telegram"),
            rules_accepted_at=person.get_rules_accepted_at_for_platform("telegram"),
            notifications_allowed_at=person.get_notifications_allowed_at_for_platform("telegram"),
        )

    def _handle_view_ticket_details(
        self,
        telegram_user_id: int,
        ticket_id: UUID,
    ) -> TelegramMenuActionResult:
        """Показывает детали тикета (историю переписки) для пользователя."""
        
        method_logger = self._logger.bind(
            stage="view_ticket_details",
            user_id=str(telegram_user_id),
            ticket_id=str(ticket_id),
        )
        
        # Получаем информацию о тикете
        if self._ticket_details_use_case is None:
            method_logger.warning("Use-case деталей тикета недоступен.")
            return TelegramMenuActionResult(
                status="ticket_details_error",
                message="Функционал просмотра деталей тикета временно недоступен.",
            )
        
        try:
            details, messages = self._get_ticket_details_with_history(ticket_id)
        except ValueError as error:
            method_logger.warning("Тикет не найден или недоступен. error={error}", error=str(error))
            return TelegramMenuActionResult(
                status="ticket_details_error",
                message=f"Тикет не найден: {error}",
            )
        
        # Проверяем, принадлежит ли тикет текущему пользователю
        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="telegram", external_id=str(telegram_user_id))
        )
        if person is None or person.person_id != details.person_id:
            method_logger.warning(
                "Попытка просмотра чужого тикета. user_person_id={user_person_id}, ticket_person_id={ticket_person_id}",
                user_person_id=person.person_id if person else None,
                ticket_person_id=details.person_id,
            )
            return TelegramMenuActionResult(
                status="ticket_details_error",
                message="У вас нет доступа к этому тикету.",
            )
        
        # Форматируем сообщение с деталями тикета
        status_emoji, status_text = self._format_ticket_status(details.status.value)
        short_id = self._format_ticket_id_short(ticket_id)
        message_lines = [
            f"{status_emoji} <b>Тикет #{short_id}</b>",
            f"📌 <b>Статус:</b> {html.escape(status_text)}",
            f"🧭 <b>Создан в:</b> {html.escape(details.source_platform)}",
        ]

        if details.last_guest_platform:
            message_lines.append(f"🔁 <b>Последний ответ из:</b> {html.escape(details.last_guest_platform)}")

        message_lines.append("")
        message_lines.extend(self._format_ticket_history_lines(messages, use_html=True))
        message = "\n".join(message_lines)
        
        return TelegramMenuActionResult(
            status="ticket_details",
            message=message,
            has_support_tickets=True,
            parse_mode="HTML",
            ticket_id=ticket_id,
            ticket_status=details.status.value,
        )

    @staticmethod
    def _parse_ticket_id(raw_ticket_id: str) -> UUID | None:
        try:
            return UUID(raw_ticket_id)
        except ValueError:
            return None
