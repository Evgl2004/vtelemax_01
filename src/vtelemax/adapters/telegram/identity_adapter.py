"""Адаптер регистрации пользователя Telegram в strict identity."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from vtelemax.core import (
    GetPersonByAccountCommand,
    GetPersonByAccountTransactionalUseCase,
    IdentityConflictError,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
)

from .menu import BUTTON_ABOUT, BUTTON_HELP, BUTTON_MAIN_MENU, BUTTON_PROFILE, BUTTON_SEND_PHONE


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


class TelegramIdentityAdapter:
    """Сервисный адаптер Telegram -> use-case strict identity."""

    def __init__(
        self,
        registration_use_case: RegisterOrAttachAccountTransactionalUseCase,
        person_lookup_use_case: GetPersonByAccountTransactionalUseCase,
    ) -> None:
        self._registration_use_case = registration_use_case
        self._person_lookup_use_case = person_lookup_use_case

    def register_contact(self, telegram_user_id: int, raw_phone: str) -> TelegramRegistrationResult:
        """Регистрирует Telegram-аккаунт пользователя по переданному телефону."""

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

        return TelegramRegistrationResult(
            is_success=True,
            status="success",
            message=(
                "Регистрация успешно подтверждена. Ваш номер сохранен в единой базе.\n"
                "Откройте Главное меню и выберите нужный раздел."
            ),
            person_id=person.person_id,
        )

    def build_start_message(self) -> str:
        """Возвращает стартовый текст приветствия."""

        return (
            "Здравствуйте. Для регистрации в единой базе нажмите кнопку и отправьте ваш номер телефона."
        )

    def build_menu_overview_message(self) -> str:
        """Возвращает текст обзора главного меню."""

        return (
            "Главное меню:\n"
            "1. Мой профиль\n"
            "2. Помощь\n"
            "3. О проекте"
        )

    def handle_menu_action(self, telegram_user_id: int, action_text: str) -> TelegramMenuActionResult:
        """Обрабатывает текстовые действия главного меню Telegram."""

        normalized_action = " ".join((action_text or "").strip().split()).lower()
        if not normalized_action:
            return TelegramMenuActionResult(
                status="empty_action",
                message="Пожалуйста, выберите действие через кнопки меню.",
            )

        if normalized_action in {BUTTON_MAIN_MENU.lower(), "меню", "/menu"}:
            return TelegramMenuActionResult(
                status="menu",
                message=self.build_menu_overview_message(),
            )

        if normalized_action in {BUTTON_HELP.lower(), "/help"}:
            return TelegramMenuActionResult(
                status="help",
                message=(
                    "Раздел помощи:\n"
                    "1. Для регистрации отправьте свой контакт.\n"
                    "2. Для проверки данных откройте пункт 'Мой профиль'.\n"
                    "3. При ошибке повторите отправку номера в корректном формате."
                ),
            )

        if normalized_action in {BUTTON_ABOUT.lower(), "/about"}:
            return TelegramMenuActionResult(
                status="about",
                message=(
                    "vtelemax — единая платформа для Telegram, VK и MAX с общей строгой "
                    "идентификацией пользователей по телефону."
                ),
            )

        if normalized_action == BUTTON_SEND_PHONE.lower():
            return TelegramMenuActionResult(
                status="request_contact",
                message="Нажмите кнопку отправки контакта ниже и подтвердите ваш номер.",
                requires_contact_keyboard=True,
            )

        if normalized_action in {BUTTON_PROFILE.lower(), "/profile"}:
            person = self._person_lookup_use_case.execute(
                GetPersonByAccountCommand(
                    platform="telegram",
                    external_id=str(telegram_user_id),
                )
            )
            if person is None:
                return TelegramMenuActionResult(
                    status="not_registered",
                    message=(
                        "Профиль пока не найден. Сначала отправьте свой номер телефона "
                        "через кнопку контакта."
                    ),
                    requires_contact_keyboard=True,
                )

            return TelegramMenuActionResult(
                status="profile",
                message=(
                    "Ваш профиль:\n"
                    f"Телефон: {person.phone_e164}\n"
                    f"Привязанных аккаунтов: {len(person.accounts)}"
                ),
            )

        return TelegramMenuActionResult(
            status="unknown_action",
            message=(
                "Команда не распознана. Используйте кнопки меню: "
                f"'{BUTTON_PROFILE}', '{BUTTON_HELP}', '{BUTTON_ABOUT}', '{BUTTON_MAIN_MENU}'."
            ),
        )
