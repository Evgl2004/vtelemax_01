"""Use-case сценарии ядра strict identity."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from uuid import uuid4

from .errors import IdentityConflictError
from .models import Person, PersonProfilePatch, PlatformAccount, PlatformName, SUPPORTED_PLATFORMS
from .phone import normalize_phone
from .ports import IdentityRepository, IdentityUnitOfWork


@dataclass(frozen=True, slots=True)
class RegisterOrAttachAccountCommand:
    """Команда регистрации/привязки платформенного аккаунта.

    Args:
        platform: Платформа аккаунта (`telegram`, `vk`, `max`).
        external_id: Идентификатор аккаунта на платформе.
        raw_phone: Телефон в произвольном пользовательском формате.
        rules_accepted: Признак согласия с правилами и политикой ПДн.
        rules_accepted_at: Дата/время согласия с правилами.
        notifications_allowed: Выбор пользователя по уведомлениям.
        notifications_allowed_at: Дата/время фиксации выбора по уведомлениям.
        is_legacy: Признак legacy-профиля.
        is_registered: Признак завершенной регистрации.
        first_name_input: Имя пользователя из анкеты.
        last_name_input: Фамилия пользователя из анкеты.
        gender: Пол пользователя.
        birth_date: Дата рождения пользователя.
        email: E-mail пользователя.
        phone_verified_at: Дата/время подтверждения телефона.
        phone_verification_method: Способ подтверждения телефона.
    """

    platform: PlatformName
    external_id: str
    raw_phone: str
    rules_accepted: bool | None = None
    rules_accepted_at: datetime | None = None
    notifications_allowed: bool | None = None
    notifications_allowed_at: datetime | None = None
    is_legacy: bool | None = None
    is_registered: bool | None = None
    first_name_input: str | None = None
    last_name_input: str | None = None
    gender: str | None = None
    birth_date: date | None = None
    email: str | None = None
    phone_verified_at: datetime | None = None
    phone_verification_method: str | None = None

    def to_profile_patch(self) -> PersonProfilePatch:
        """Преобразует команду в объект частичного обновления профиля."""

        # Инициализируем все поля как None
        patch_kwargs = {
            "rules_accepted": self.rules_accepted,
            "rules_accepted_at": self.rules_accepted_at,
            "notifications_allowed": self.notifications_allowed,
            "notifications_allowed_at": self.notifications_allowed_at,
            "is_legacy": self.is_legacy,
            "is_registered": self.is_registered,
            "first_name_input": self.first_name_input,
            "last_name_input": self.last_name_input,
            "gender": self.gender,
            "birth_date": self.birth_date,
            "email": self.email,
            "phone_verified_at": self.phone_verified_at,
            "phone_verification_method": self.phone_verification_method,
        }

        # Добавляем платформо-специфичные поля на основе self.platform
        if self.platform == "telegram":
            patch_kwargs["rules_accepted_tg"] = self.rules_accepted
            patch_kwargs["rules_accepted_tg_at"] = self.rules_accepted_at
            patch_kwargs["notifications_allowed_tg"] = self.notifications_allowed
            patch_kwargs["notifications_allowed_tg_at"] = self.notifications_allowed_at
        elif self.platform == "vk":
            patch_kwargs["rules_accepted_vk"] = self.rules_accepted
            patch_kwargs["rules_accepted_vk_at"] = self.rules_accepted_at
            patch_kwargs["notifications_allowed_vk"] = self.notifications_allowed
            patch_kwargs["notifications_allowed_vk_at"] = self.notifications_allowed_at
        elif self.platform == "max":
            patch_kwargs["rules_accepted_max"] = self.rules_accepted
            patch_kwargs["rules_accepted_max_at"] = self.rules_accepted_at
            patch_kwargs["notifications_allowed_max"] = self.notifications_allowed
            patch_kwargs["notifications_allowed_max_at"] = self.notifications_allowed_at
        else:
            # Это не должно происходить, т.к. platform валидируется
            pass

        return PersonProfilePatch(**patch_kwargs)


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
        profile_patch = command.to_profile_patch()

        if person is None:
            person = Person(person_id=uuid4(), phone_e164=phone_e164)
            _apply_profile_patch(person, profile_patch)
            self._repository.add_person(person)
        elif person.phone_e164 != phone_e164:
            raise IdentityConflictError(
                "Конфликт strict identity: аккаунт уже связан с другим телефоном."
            )

        account = PlatformAccount(platform=command.platform, external_id=external_id_value)
        if account not in person.accounts:
            self._repository.attach_account(person.person_id, account)
            person.accounts.add(account)

        if profile_patch.has_updates():
            self._repository.update_person_profile(person.person_id, profile_patch)
            _apply_profile_patch(person, profile_patch)
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


@dataclass(frozen=True, slots=True)
class GetPersonByAccountCommand:
    """Команда получения человека по аккаунту платформы.

    Args:
        platform: Платформа аккаунта (`telegram`, `vk`, `max`).
        external_id: Идентификатор аккаунта на платформе.
    """

    platform: PlatformName
    external_id: str


class GetPersonByAccountUseCase:
    """Use-case чтения человека по платформенному аккаунту."""

    def __init__(self, repository: IdentityRepository) -> None:
        self._repository = repository

    def execute(self, command: GetPersonByAccountCommand) -> Person | None:
        """Возвращает человека по платформенному аккаунту или `None`."""

        if command.platform not in SUPPORTED_PLATFORMS:
            raise ValueError(
                "Платформа не поддерживается. Допустимые значения: telegram, vk, max."
            )

        external_id_value = str(command.external_id).strip()
        if not external_id_value:
            raise ValueError("Внешний идентификатор аккаунта не может быть пустым.")

        return self._repository.get_person_by_account(command.platform, external_id_value)


class GetPersonByAccountTransactionalUseCase:
    """Транзакционный use-case чтения по аккаунту через UnitOfWork."""

    def __init__(self, unit_of_work_factory: Callable[[], IdentityUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, command: GetPersonByAccountCommand) -> Person | None:
        """Читает данные внутри UoW-контекста без явного commit."""

        with self._unit_of_work_factory() as unit_of_work:
            use_case = GetPersonByAccountUseCase(unit_of_work.identity_repository)
            return use_case.execute(command)


def _apply_profile_patch(person: Person, patch: PersonProfilePatch) -> None:
    """Применяет частичное обновление профиля к доменной модели `Person`."""

    if patch.rules_accepted is not None:
        person.rules_accepted = patch.rules_accepted
    if patch.rules_accepted_at is not None:
        person.rules_accepted_at = patch.rules_accepted_at
    if patch.notifications_allowed is not None:
        person.notifications_allowed = patch.notifications_allowed
    if patch.notifications_allowed_at is not None:
        person.notifications_allowed_at = patch.notifications_allowed_at

    # Платформо-специфичные согласия Telegram
    if patch.rules_accepted_tg is not None:
        person.rules_accepted_tg = patch.rules_accepted_tg
    if patch.rules_accepted_tg_at is not None:
        person.rules_accepted_tg_at = patch.rules_accepted_tg_at
    if patch.notifications_allowed_tg is not None:
        person.notifications_allowed_tg = patch.notifications_allowed_tg
    if patch.notifications_allowed_tg_at is not None:
        person.notifications_allowed_tg_at = patch.notifications_allowed_tg_at

    # Платформо-специфичные согласия VK
    if patch.rules_accepted_vk is not None:
        person.rules_accepted_vk = patch.rules_accepted_vk
    if patch.rules_accepted_vk_at is not None:
        person.rules_accepted_vk_at = patch.rules_accepted_vk_at
    if patch.notifications_allowed_vk is not None:
        person.notifications_allowed_vk = patch.notifications_allowed_vk
    if patch.notifications_allowed_vk_at is not None:
        person.notifications_allowed_vk_at = patch.notifications_allowed_vk_at

    # Платформо-специфичные согласия MAX
    if patch.rules_accepted_max is not None:
        person.rules_accepted_max = patch.rules_accepted_max
    if patch.rules_accepted_max_at is not None:
        person.rules_accepted_max_at = patch.rules_accepted_max_at
    if patch.notifications_allowed_max is not None:
        person.notifications_allowed_max = patch.notifications_allowed_max
    if patch.notifications_allowed_max_at is not None:
        person.notifications_allowed_max_at = patch.notifications_allowed_max_at

    if patch.is_legacy is not None:
        person.is_legacy = patch.is_legacy
    if patch.is_registered is not None:
        person.is_registered = patch.is_registered
    if patch.first_name_input is not None:
        person.first_name_input = patch.first_name_input
    if patch.last_name_input is not None:
        person.last_name_input = patch.last_name_input
    if patch.gender is not None:
        person.gender = patch.gender
    if patch.birth_date is not None:
        person.birth_date = patch.birth_date
    if patch.email is not None:
        person.email = patch.email
    if patch.phone_verified_at is not None:
        person.phone_verified_at = patch.phone_verified_at
    if patch.phone_verification_method is not None:
        person.phone_verification_method = patch.phone_verification_method
