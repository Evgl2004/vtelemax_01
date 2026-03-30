"""Адаптер регистрации пользователя Telegram в strict identity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import UUID

from loguru import logger

from vtelemax.core import (
    BUTTON_ACCEPT_RULES,
    BUTTON_ABOUT,
    BUTTON_BALANCE,
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
    BUTTON_SEND_PHONE,
    BUTTON_SUPPORT,
    BUTTON_VACANCIES,
    BUTTON_VIRTUAL_CARD,
    CreateSupportTicketCommand,
    CreateSupportTicketTransactionalUseCase,
    GetLoyaltyBalanceUseCase,
    GuestMenuAction,
    GetSupportTicketDetailsTransactionalUseCase,
    GetVirtualCardUseCase,
    ListOpenSupportTicketsTransactionalUseCase,
    ListPersonSupportTicketsTransactionalUseCase,
    ModeratorReplyCommand,
    OnboardingFlowService,
    OnboardingState,
    PersonSupportTicketSummary,
    GetPersonByAccountCommand,
    GetPersonByAccountTransactionalUseCase,
    IdentityConflictError,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
    RouteModeratorReplyTransactionalUseCase,
    SUPPORTED_PLATFORMS,
    build_about_screen,
    build_first_name_input_screen,
    build_help_screen,
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
    build_virtual_card_result_screen,
    build_vacancies_screen,
    normalize_email,
    normalize_menu_text,
    normalize_person_name,
    parse_birth_date,
    resolve_guest_menu_action,
)


@dataclass(frozen=True, slots=True)
class TelegramRegistrationResult:
    """Результат обработки регистрации/привязки из Telegram."""

    is_success: bool
    status: str
    message: str
    person_id: UUID | None = None


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


_STATE_WAITING_SUPPORT_QUESTION = "waiting_support_question"
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


@dataclass(slots=True)
class _OnboardingDraft:
    """Промежуточные данные сокращенной регистрации до финальной фиксации."""

    rules_accepted_at: datetime | None = None
    phone_e164: str | None = None
    phone_verified_at: datetime | None = None
    phone_verification_method: str | None = None
    first_name_input: str | None = None


class TelegramIdentityAdapter:
    """Сервисный адаптер Telegram -> use-case strict identity."""

    def __init__(
        self,
        registration_use_case: RegisterOrAttachAccountTransactionalUseCase,
        person_lookup_use_case: GetPersonByAccountTransactionalUseCase,
        create_support_ticket_use_case: CreateSupportTicketTransactionalUseCase | None = None,
        moderator_reply_use_case: RouteModeratorReplyTransactionalUseCase | None = None,
        ticket_details_use_case: GetSupportTicketDetailsTransactionalUseCase | None = None,
        list_open_tickets_use_case: ListOpenSupportTicketsTransactionalUseCase | None = None,
        list_person_tickets_use_case: ListPersonSupportTicketsTransactionalUseCase | None = None,
        balance_use_case: GetLoyaltyBalanceUseCase | None = None,
        virtual_card_use_case: GetVirtualCardUseCase | None = None,
    ) -> None:
        self._logger = logger.bind(platform="telegram", component="identity_adapter")
        self._registration_use_case = registration_use_case
        self._person_lookup_use_case = person_lookup_use_case
        self._onboarding_flow = OnboardingFlowService(platform="telegram")
        self._onboarding_state_by_user_id: dict[int, OnboardingState] = {}
        self._onboarding_draft_by_user_id: dict[int, _OnboardingDraft] = {}
        self._dialog_state_by_user_id: dict[int, str] = {}
        self._moderator_state_by_user_id: dict[int, str] = {}
        self._moderator_context_by_user_id: dict[int, dict[str, str]] = {}
        self._create_support_ticket_use_case = create_support_ticket_use_case
        self._moderator_reply_use_case = moderator_reply_use_case
        self._ticket_details_use_case = ticket_details_use_case
        self._list_open_tickets_use_case = list_open_tickets_use_case
        self._list_person_tickets_use_case = list_person_tickets_use_case
        self._balance_use_case = balance_use_case
        self._virtual_card_use_case = virtual_card_use_case

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
            self._onboarding_draft_by_user_id[telegram_user_id] = _OnboardingDraft()
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            self._clear_moderator_state(telegram_user_id)
            return TelegramMenuActionResult(
                status=transition.status,
                message=transition.message,
                requires_contact_keyboard=transition.requires_contact_keyboard,
            )

        if not person.is_registered:
            method_logger.info("Найден незавершенный профиль, восстанавливаем onboarding.")
            draft = _OnboardingDraft(
                rules_accepted_at=person.rules_accepted_at,
                phone_e164=person.phone_e164,
                phone_verified_at=person.phone_verified_at,
                phone_verification_method=person.phone_verification_method,
                first_name_input=person.first_name_input,
            )
            self._onboarding_draft_by_user_id[telegram_user_id] = draft
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            self._clear_moderator_state(telegram_user_id)

            if not person.rules_accepted:
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
                message="Не удалось обработать телефон. Проверьте формат и отправьте контакт еще раз.",
            )

        draft.phone_e164 = person.phone_e164
        draft.phone_verified_at = phone_verified_at
        draft.phone_verification_method = "telegram_contact"

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
            self._onboarding_state_by_user_id[telegram_user_id] = transition.state
            if transition.state == OnboardingState.WAITING_PHONE:
                draft = self._onboarding_draft_by_user_id.setdefault(telegram_user_id, _OnboardingDraft())
                draft.rules_accepted_at = datetime.now(timezone.utc)
            method_logger.info(
                "Обработано подтверждение правил. status={status}.",
                status=transition.status,
            )
            return TelegramMenuActionResult(
                status=transition.status,
                message=transition.message,
                requires_contact_keyboard=transition.requires_contact_keyboard,
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
            try:
                person = self._registration_use_case.execute(
                    RegisterOrAttachAccountCommand(
                        platform="telegram",
                        external_id=str(telegram_user_id),
                        raw_phone=draft.phone_e164,
                        rules_accepted=True,
                        rules_accepted_at=draft.rules_accepted_at or notifications_fixed_at,
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

            self._onboarding_state_by_user_id.pop(telegram_user_id, None)
            self._onboarding_draft_by_user_id.pop(telegram_user_id, None)
            self._dialog_state_by_user_id.pop(telegram_user_id, None)
            self._clear_moderator_state(telegram_user_id)

            sync_message, registration_card_numbers = self._sync_registration_with_loyalty(phone_e164=person.phone_e164)
            completion_parts = [
                "✅ Регистрация успешно завершена.",
                sync_message,
            ]
            if registration_card_numbers:
                completion_parts.append("🪪 Сейчас отправлю QR-коды ваших карт.")
            completion_parts.extend(
                [
                    "ℹ️ Подробности анкеты и информацию профиля можно посмотреть и изменить в разделе «👤 Профиль».",
                    self.build_menu_overview_message(user_name=person.first_name_input or "Гость"),
                ]
            )
            return TelegramMenuActionResult(
                status="menu",
                message="\n\n".join(completion_parts),
                virtual_card_numbers=registration_card_numbers,
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
                GuestMenuAction.BACK_TO_SUPPORT,
                GuestMenuAction.BACK_TO_MAIN,
                GuestMenuAction.SUPPORT,
                GuestMenuAction.MAIN_MENU,
            }:
                self._dialog_state_by_user_id.pop(telegram_user_id, None)
                return self.handle_menu_action(telegram_user_id=telegram_user_id, action_text=action_text)
            return self._handle_support_question_input(telegram_user_id=telegram_user_id, question_text=action_text)
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
                    f"'{BUTTON_BALANCE}', '{BUTTON_VIRTUAL_CARD}', '{BUTTON_SUPPORT}', '{BUTTON_VACANCIES}', "
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
            self._dialog_state_by_user_id[telegram_user_id] = _STATE_WAITING_SUPPORT_QUESTION
            screen = build_support_question_screen()
            has_tickets = self._has_user_tickets(
                platform="telegram",
                external_id=str(telegram_user_id),
            )
            return TelegramMenuActionResult(
                status="support_question",
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
                        "Чтобы создать обращение, нажмите «❓ Мне только спросить» в меню отдела заботы."
                    ),
                    has_support_tickets=False,
                )
            return TelegramMenuActionResult(
                status="tickets_list",
                message=self._format_person_tickets_message(tickets),
                has_support_tickets=True,
            )

        return TelegramMenuActionResult(
            status="unknown_action",
            message=(
                "Команда не распознана. Используйте кнопки меню: "
                f"'{BUTTON_BALANCE}', '{BUTTON_VIRTUAL_CARD}', '{BUTTON_SUPPORT}', '{BUTTON_VACANCIES}', "
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
        if not question:
            return TelegramMenuActionResult(
                status="support_question_empty",
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
                message=(
                    "Не удалось зарегистрировать обращение в системе модерации.\n"
                    f"Причина: {error}"
                ),
            )

        return TelegramMenuActionResult(
            status="support_question_submitted",
            message=(
                "📨 Ваш вопрос принят!\n"
                f"🎫 Создан тикет #{created.ticket_id}\n"
                "Канал обращения: telegram\n"
                "Модератор рассмотрит обращение в ближайшее время."
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
            rules_accepted=person.rules_accepted,
            rules_accepted_at=person.rules_accepted_at,
            notifications_allowed=person.notifications_allowed,
            notifications_allowed_at=person.notifications_allowed_at,
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
                message="Имя должно содержать только буквы, пробел и дефис (от 2 до 50 символов).",
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
                message="Фамилия должна содержать только буквы, пробел и дефис (от 2 до 50 символов).",
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
                message="Выберите пол кнопками «👨 Мужской» или «👩 Женский».",
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
                message="🎂 Дата рождения уже заполнена и не может быть изменена.",
            )

        parsed_birth_date = parse_birth_date(action_text)
        if parsed_birth_date is None:
            return TelegramMenuActionResult(
                status="profile_edit_birth_date_invalid",
                message="Введите дату рождения в формате ДД.ММ.ГГГГ и не в будущем.",
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
                message="Введите корректный email, например `name@example.com`.",
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
                message="Не удалось сохранить изменения профиля. Попробуйте еще раз позже.",
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
        if lowered.startswith("/modreply"):
            return self._handle_modreply_command(raw)
        if lowered.startswith("/modticket"):
            return self._handle_modticket_command(raw)
        if lowered in {"/mod", "модератор", "moderator"}:
            return self._open_moderator_menu(telegram_user_id=telegram_user_id)
        return None

    def _open_moderator_menu(self, *, telegram_user_id: int) -> TelegramMenuActionResult:
        """Открывает единое меню модератора."""

        if self._moderator_reply_use_case is None or self._ticket_details_use_case is None:
            return TelegramMenuActionResult(
                status="moderation_unavailable",
                message="Меню модератора недоступно: не подключены сценарии modreply/modticket.",
            )

        self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id.pop(telegram_user_id, None)
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
            tickets_text = self._build_open_tickets_text(limit=10)
            return TelegramMenuActionResult(
                status="moderation_tickets",
                message=f"{tickets_text}\n\n{self._build_moderation_menu_text()}",
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
                "Можно указать целевой канал префиксом: --to=telegram|vk|max.\n"
                "Пример: --to=vk Добрый день, ответ готов."
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

        self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id.pop(telegram_user_id, None)
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
            details = self._ticket_details_use_case.execute(ticket_id)
        except ValueError as error:
            return TelegramMenuActionResult(
                status="moderation_details_error",
                message=f"Не удалось загрузить тикет: {error}",
            )

        self._moderator_state_by_user_id[telegram_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id.pop(telegram_user_id, None)
        linked = ", ".join(details.linked_platforms)
        return TelegramMenuActionResult(
            status="moderation_details",
            message=(
                f"Тикет: {details.ticket_id}\n"
                f"Статус: {details.status}\n"
                f"Канал создания: {details.source_platform}\n"
                f"Последний канал гостя: {details.last_guest_platform or '-'}\n"
                f"Каналы гостя: {linked}\n\n"
                f"{self._build_moderation_menu_text()}"
            ),
        )

    def _build_open_tickets_text(self, *, limit: int) -> str:
        """Формирует текст открытых тикетов для модераторского меню."""

        if self._list_open_tickets_use_case is None:
            return "Список тикетов недоступен: list-open-use-case не подключен."

        tickets = self._list_open_tickets_use_case.execute(limit=limit)
        if not tickets:
            return "Открытых тикетов сейчас нет."

        lines = ["Открытые тикеты:"]
        for index, ticket in enumerate(tickets, start=1):
            lines.append(
                f"{index}. #{ticket.ticket_id} | канал={ticket.source_platform} | "
                f"последний={ticket.last_guest_platform or '-'}"
            )
        return "\n".join(lines)

    def _handle_balance_action(self, *, telegram_user_id: int) -> TelegramMenuActionResult:
        """Обрабатывает пункт меню «Мой баланс» через общий use-case лояльности."""

        if self._balance_use_case is None:
            return TelegramMenuActionResult(
                status="balance_unavailable",
                message=(
                    "❌ Информация о бонусах временно недоступна.\n"
                    "Пожалуйста, попробуйте позже или обратитесь к администратору."
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
                    "❌ Раздел виртуальной карты временно недоступен.\n"
                    "Пожалуйста, попробуйте позже или обратитесь к администратору."
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
            "1 — Список открытых тикетов\n"
            "2 — Ответить на тикет\n"
            "3 — Показать карточку тикета\n"
            "0 — Выйти из режима модератора"
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

    @staticmethod
    def _format_person_tickets_message(tickets: tuple[PersonSupportTicketSummary, ...]) -> str:
        """Форматирует список тикетов пользователя в текстовое представление."""

        lines = ["📋 Ваши обращения:"]
        status_emoji = {"open": "🆕", "closed": "🔒"}
        for ticket in tickets:
            created_at = ticket.created_at.strftime("%d.%m.%Y %H:%M") if ticket.created_at else "—"
            lines.append(
                "\n".join(
                    (
                        f"{status_emoji.get(ticket.status.value, '❓')} Тикет #{ticket.ticket_id}",
                        f"Статус: {ticket.status.value}",
                        f"Канал создания: {ticket.source_platform}",
                        f"Последняя платформа: {ticket.last_guest_platform or '—'}",
                        f"Создан: {created_at}",
                    )
                )
            )
        lines.append("\nЧтобы добавить новое сообщение, выберите «❓ Мне только спросить».")
        return "\n\n".join(lines)

    @staticmethod
    def _normalize_first_name(raw_text: str) -> str | None:
        """Проверяет и нормализует имя пользователя для шага сокращенной регистрации."""

        return normalize_person_name(raw_text)

    def _sync_registration_with_loyalty(self, *, phone_e164: str) -> tuple[str, tuple[str, ...]]:
        """Запускает синхронизацию с iiko и возвращает текст + номера карт для отправки QR."""

        if self._virtual_card_use_case is None:
            return ("ℹ️ Синхронизация с iiko временно недоступна.", ())

        result = self._virtual_card_use_case.execute(phone_e164=phone_e164)
        if result.status == "virtual_card":
            return ("✅ Синхронизация с iiko выполнена успешно.", result.card_numbers)
        return ("⚠️ Синхронизация с iiko выполнена с ограничениями.", ())

    @staticmethod
    def _parse_ticket_id(raw_ticket_id: str) -> UUID | None:
        try:
            return UUID(raw_ticket_id)
        except ValueError:
            return None
