"""Адаптер регистрации пользователя Telegram в strict identity."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from vtelemax.core import (
    IdentityConflictError,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
)


@dataclass(frozen=True, slots=True)
class TelegramRegistrationResult:
    """Результат обработки регистрации/привязки из Telegram."""

    is_success: bool
    status: str
    message: str
    person_id: UUID | None = None


class TelegramIdentityAdapter:
    """Сервисный адаптер Telegram -> use-case strict identity."""

    def __init__(self, transactional_use_case: RegisterOrAttachAccountTransactionalUseCase) -> None:
        self._transactional_use_case = transactional_use_case

    def register_contact(self, telegram_user_id: int, raw_phone: str) -> TelegramRegistrationResult:
        """Регистрирует Telegram-аккаунт пользователя по переданному телефону."""

        try:
            person = self._transactional_use_case.execute(
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
            message="Регистрация успешно подтверждена. Ваш номер сохранен в единой базе.",
            person_id=person.person_id,
        )
