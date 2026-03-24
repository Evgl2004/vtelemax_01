"""Доменное ядро vtelemax.

В ядре размещается логика, общая для всех мессенджеров:

1. Правила валидации и нормализации.
2. Сценарии идентификации и регистрации.
3. Use-case операции, не зависящие от SDK платформ.
"""

from .errors import IdentityConflictError
from .identity import StrictIdentityService
from .in_memory_identity_repository import InMemoryIdentityRepository
from .models import Person, PlatformAccount, PlatformName, SUPPORTED_PLATFORMS
from .phone import normalize_phone
from .ports import IdentityRepository, IdentityUnitOfWork
from .use_cases import (
    GetPersonByAccountCommand,
    GetPersonByAccountTransactionalUseCase,
    GetPersonByAccountUseCase,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
    RegisterOrAttachAccountUseCase,
)

__all__ = [
    "IdentityConflictError",
    "IdentityRepository",
    "IdentityUnitOfWork",
    "InMemoryIdentityRepository",
    "Person",
    "PlatformAccount",
    "PlatformName",
    "SUPPORTED_PLATFORMS",
    "GetPersonByAccountCommand",
    "GetPersonByAccountUseCase",
    "GetPersonByAccountTransactionalUseCase",
    "RegisterOrAttachAccountCommand",
    "RegisterOrAttachAccountTransactionalUseCase",
    "RegisterOrAttachAccountUseCase",
    "StrictIdentityService",
    "normalize_phone",
]
