"""Доменное ядро vtelemax.

В ядре размещается логика, общая для всех мессенджеров:

1. Правила валидации и нормализации.
2. Сценарии идентификации и регистрации.
3. Use-case операции, не зависящие от SDK платформ.
"""

from .identity import IdentityConflictError, PlatformName, StrictIdentityService
from .phone import normalize_phone

__all__ = [
    "IdentityConflictError",
    "PlatformName",
    "StrictIdentityService",
    "normalize_phone",
]

