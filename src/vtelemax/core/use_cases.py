"""Use-case сценарии ядра strict identity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from .errors import IdentityConflictError
from .models import Person, PlatformAccount, PlatformName, SUPPORTED_PLATFORMS
from .phone import normalize_phone
from .ports import IdentityRepository, IdentityUnitOfWork


@dataclass(frozen=True, slots=True)
class RegisterOrAttachAccountCommand:
    """Команда регистрации/привязки платформенного аккаунта.

    Args:
        platform: Платформа аккаунта (`telegram`, `vk`, `max`).
        external_id: Идентификатор аккаунта на платформе.
        raw_phone: Телефон в произвольном пользовательском формате.
    """

    platform: PlatformName
    external_id: str
    raw_phone: str


class RegisterOrAttachAccountUseCase:
    """Use-case strict identity для регистрации и привязки аккаунтов.

    Бизнес-правила:

    1. Один канонический телефон принадлежит только одному `Person`.
    2. Одна пара (`platform`, `external_id`) принадлежит только одному `Person`.
    3. Конфликтные перепривязки блокируются доменной ошибкой.
    """

    def __init__(self, repository: IdentityRepository) -> None:
        self._repository = repository

    def execute(self, command: RegisterOrAttachAccountCommand) -> Person:
        """Выполняет сценарий регистрации/привязки аккаунта."""

        if command.platform not in SUPPORTED_PLATFORMS:
            raise ValueError(
                "Платформа не поддерживается. Допустимые значения: telegram, vk, max."
            )

        external_id_value = str(command.external_id).strip()
        if not external_id_value:
            raise ValueError("Внешний идентификатор аккаунта не может быть пустым.")

        phone_e164 = normalize_phone(command.raw_phone)
        person_by_phone = self._repository.get_person_by_phone(phone_e164)
        person_by_account = self._repository.get_person_by_account(command.platform, external_id_value)

        if (
            person_by_phone is not None
            and person_by_account is not None
            and person_by_phone.person_id != person_by_account.person_id
        ):
            raise IdentityConflictError(
                "Конфликт strict identity: телефон и аккаунт уже привязаны к разным людям."
            )

        person = person_by_phone or person_by_account
        if person is None:
            person = Person(person_id=uuid4(), phone_e164=phone_e164)
            self._repository.add_person(person)
        elif person.phone_e164 != phone_e164:
            raise IdentityConflictError(
                "Конфликт strict identity: аккаунт уже связан с другим телефоном."
            )

        account = PlatformAccount(platform=command.platform, external_id=external_id_value)
        if account in person.accounts:
            # Идемпотентное поведение: повторная привязка того же аккаунта не изменяет состояние.
            return person

        self._repository.attach_account(person.person_id, account)
        person.accounts.add(account)
        return person


class RegisterOrAttachAccountTransactionalUseCase:
    """Транзакционный use-case strict identity через UnitOfWork.

    Используется в инфраструктурных окружениях (например, PostgreSQL),
    где важна атомарность нескольких операций в одной транзакции.
    """

    def __init__(self, unit_of_work_factory: Callable[[], IdentityUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, command: RegisterOrAttachAccountCommand) -> Person:
        """Выполняет сценарий внутри транзакции с commit/rollback."""

        with self._unit_of_work_factory() as unit_of_work:
            use_case = RegisterOrAttachAccountUseCase(unit_of_work.identity_repository)
            person = use_case.execute(command)
            unit_of_work.commit()
            return person
