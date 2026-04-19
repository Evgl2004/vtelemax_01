"""Инфраструктурный слой vtelemax.

В этом пакете размещаются реализации портов ядра:

1. Работа с PostgreSQL (репозитории, unit-of-work, модели БД).
2. Работа с Redis и другими внешними сервисами.
3. Технические детали, которые не должны попадать в `core`.
"""

from .logging_config import configure_logging, normalize_log_level
from .iiko_client import IikoLoyaltyGateway
from .migrations import apply_migrations, list_migration_files, read_sql_statements
from .qr import QrGenerationError, generate_qr_png_bytes
from .vk_phone_verification_gateway import (
    HttpVkPhoneVerificationGateway,
    VkPhoneVerificationGatewayError,
    VkPhoneVerificationStatus,
)

__all__ = [
    "configure_logging",
    "normalize_log_level",
    "IikoLoyaltyGateway",
    "apply_migrations",
    "list_migration_files",
    "read_sql_statements",
    "generate_qr_png_bytes",
    "QrGenerationError",
    "HttpVkPhoneVerificationGateway",
    "VkPhoneVerificationGatewayError",
    "VkPhoneVerificationStatus",
]
