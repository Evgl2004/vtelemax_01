"""Адаптер регистрации пользователя Telegram в strict identity."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from vtelemax.core import (
    BUTTON_ACCEPT_RULES,
    BUTTON_ABOUT,
    BUTTON_BALANCE,
    BUTTON_HELP,
    BUTTON_MAIN_MENU,
    BUTTON_PROFILE,
    BUTTON_SEND_PHONE,
    BUTTON_SUPPORT,
    BUTTON_VACANCIES,
    BUTTON_VIRTUAL_CARD,
    GuestMenuAction,
    OnboardingFlowService,
    OnboardingState,
    GetPersonByAccountCommand,
    GetPersonByAccountTransactionalUseCase,
    IdentityConflictError,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
    build_about_screen,
    build_help_screen,
    build_main_menu_screen,
    build_profile_not_found_screen,
    build_profile_screen,
    build_start_rules_screen,
    build_support_contacts_screen,
    build_support_feedback_screen,
    build_support_menu_screen,
    build_support_question_screen,
    build_vacancies_screen,
    normalize_menu_text,
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


class TelegramIdentityAdapter:
    """Сервисный адаптер Telegram -> use-case strict identity."""

    def __init__(
        self,
        registration_use_case: RegisterOrAttachAccountTransactionalUseCase,
        person_lookup_use_case: GetPersonByAccountTransactionalUseCase,
    ) -> None:
        self._registration_use_case = registration_use_case
        self._person_lookup_use_case = person_lookup_use_case
        self._onboarding_flow = OnboardingFlowService()
        self._onboarding_state_by_user_id: dict[int, OnboardingState] = {}

    def start_interaction(
        self,
        telegram_user_id: int,
        *,
        force_legacy_upgrade: bool = False,
    ) -> TelegramMenuActionResult:
        """Запускает стартовый сценарий onboarding/меню для пользователя."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(
                platform="telegram",
                external_id=str(telegram_user_id),
            )
        )

        if person is None:
            transition = self._onboarding_flow.begin_new_user()
            self._onboarding_state_by_user_id[telegram_user_id] = transition.state
            return TelegramMenuActionResult(
                status=transition.status,
                message=transition.message,
                requires_contact_keyboard=transition.requires_contact_keyboard,
            )

        if force_legacy_upgrade:
            transition = self._onboarding_flow.begin_legacy_upgrade()
            self._onboarding_state_by_user_id[telegram_user_id] = transition.state
            return TelegramMenuActionResult(
                status=transition.status,
                message=transition.message,
                requires_contact_keyboard=transition.requires_contact_keyboard,
            )

        self._onboarding_state_by_user_id.pop(telegram_user_id, None)
        return TelegramMenuActionResult(
            status="menu",
            message=self.build_menu_overview_message(),
        )

    def register_contact(self, telegram_user_id: int, raw_phone: str) -> TelegramRegistrationResult:
        """Регистрирует Telegram-аккаунт пользователя по переданному телефону."""

        previous_state = self._onboarding_state_by_user_id.get(telegram_user_id, OnboardingState.IDLE)

        try:
            person = self._registration_use_case.execute(
                RegisterOrAttachAccountCommand(
                    platform="telegram",
                    external_id=str(telegram_user_id),
                    raw_phone=raw_phone,
                )
            )
        except IdentityConflictError:
            return TelegramRegistrationResult(
                is_success=False,
                status="conflict",
                message=(
                    "Обнаружен конфликт идентификации: этот Telegram-аккаунт уже привязан к другому "
                    "телефону или телефон связан с другим аккаунтом."
                ),
            )
        except ValueError:
            return TelegramRegistrationResult(
                is_success=False,
                status="validation_error",
                message="Не удалось обработать телефон. Проверьте формат и отправьте контакт еще раз.",
            )

        self._onboarding_state_by_user_id.pop(telegram_user_id, None)
        if previous_state == OnboardingState.WAITING_LEGACY_PHONE:
            success_message = (
                "Профиль legacy успешно обновлен. Ваш номер подтвержден в единой базе.\n"
                "Откройте Главное меню и выберите нужный раздел."
            )
        else:
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

    def build_menu_overview_message(self) -> str:
        """Возвращает текст обзора главного меню."""

        return build_main_menu_screen().text

    def handle_menu_action(self, telegram_user_id: int, action_text: str) -> TelegramMenuActionResult:
        """Обрабатывает текстовые действия главного меню Telegram."""

        onboarding_state = self._onboarding_state_by_user_id.get(telegram_user_id, OnboardingState.IDLE)
        if onboarding_state == OnboardingState.WAITING_RULES_CONSENT:
            transition = self._onboarding_flow.handle_rules_input(action_text)
            self._onboarding_state_by_user_id[telegram_user_id] = transition.state
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

        if onboarding_state == OnboardingState.WAITING_LEGACY_PHONE:
            return TelegramMenuActionResult(
                status="legacy_phone_required",
                message=(
                    "Для обновления legacy-профиля отправьте номер телефона через кнопку "
                    f"«{BUTTON_SEND_PHONE}»."
                ),
                requires_contact_keyboard=True,
            )

        action = resolve_guest_menu_action(action_text)
        if action is None:
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
                message=self.build_menu_overview_message(),
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

            screen = build_profile_screen(phone_e164=person.phone_e164, accounts_count=len(person.accounts))
            return TelegramMenuActionResult(
                status="profile",
                message=screen.text,
            )

        if action in {GuestMenuAction.SUPPORT, GuestMenuAction.BACK_TO_SUPPORT}:
            screen = build_support_menu_screen(has_tickets=False)
            return TelegramMenuActionResult(
                status="support",
                message=screen.text,
                parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
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
            return TelegramMenuActionResult(
                status="support_feedback",
                message=screen.text,
                parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
            )

        if action == GuestMenuAction.SUPPORT_QUESTION:
            screen = build_support_question_screen()
            return TelegramMenuActionResult(
                status="support_question",
                message=screen.text,
                parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
            )

        if action == GuestMenuAction.SUPPORT_CONTACTS:
            screen = build_support_contacts_screen()
            return TelegramMenuActionResult(
                status="support_contacts",
                message=screen.text,
            )

        if action == GuestMenuAction.BALANCE:
            return TelegramMenuActionResult(
                status="balance_unavailable",
                message=(
                    "❌ Информация о бонусах временно недоступна.\n"
                    "Пожалуйста, попробуйте позже или обратитесь к администратору."
                ),
            )

        if action == GuestMenuAction.VIRTUAL_CARD:
            return TelegramMenuActionResult(
                status="virtual_card_unavailable",
                message=(
                    "🪪 Раздел виртуальной карты пока недоступен в этом адаптере.\n"
                    "Скоро подключим полный сценарий выпуска и показа QR."
                ),
            )

        if action == GuestMenuAction.MY_TICKETS:
            return TelegramMenuActionResult(
                status="tickets_unavailable",
                message=(
                    "📋 Раздел 'Мои обращения' пока в разработке для Telegram-адаптера.\n"
                    "Мы подключим его следующим этапом."
                ),
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
