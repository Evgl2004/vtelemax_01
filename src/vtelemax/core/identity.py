"""Фасад strict identity и совместимость внешнего API.

Модуль оставляет удобную точку входа `StrictIdentityService`, но сама
бизнес-логика вынесена в use-case и репозиторные порты.
"""

from __future__ import annotations

from .errors import IdentityConflictError
from .in_memory_identity_repository import InMemoryIdentityRepository
from .models import Person, PlatformAccount, PlatformName
from .phone import normalize_phone
from .ports import IdentityRepository
from .use_cases import RegisterOrAttachAccountCommand, RegisterOrAttachAccountUseCase


class StrictIdentityService:
    """Сервис-обертка над use-case strict identity.

    Args:
        repository: Реализация порта `IdentityRepository`.
            Если не передана, используется in-memory репозиторий.
    """

    def __init__(self, repository: IdentityRepository | None = None) -> None:
        self._repository = repository or InMemoryIdentityRepository()
        self._register_use_case = RegisterOrAttachAccountUseCase(repository=self._repository)

    def register_or_attach_account(
        self,
        platform: PlatformName,
        external_id: str,
        raw_phone: str,
    ) -> Person:
        """Регистрирует или до-привязывает платформенный аккаунт к человеку."""

        command = RegisterOrAttachAccountCommand(
            platform=platform,
            external_id=external_id,
            raw_phone=raw_phone,
        )
        return self._register_use_case.execute(command)

    def get_person_by_phone(self, raw_phone: str) -> Person | None:
        """Возвращает человека по телефону, если он зарегистрирован."""

        phone_e164 = normalize_phone(raw_phone)
        return self._repository.get_person_by_phone(phone_e164)

    def get_person_by_account(self, platform: PlatformName, external_id: str) -> Person | None:
        """Возвращает человека по аккаунту платформы."""

        return self._repository.get_person_by_account(platform, str(external_id).strip())
