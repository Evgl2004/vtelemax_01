"""PostgreSQL-инфраструктура strict identity."""

from .repository import SQLAlchemyIdentityRepository
from .schema import (
    Base,
    PersonRow,
    PersonPlatformStateRow,
    PhoneRow,
    PlatformAccountRow,
    ProfileSyncQueueRow,
    SupportMessageRow,
    SupportTicketRow,
    VkPhoneVerificationSessionRow,
)
from .session import build_engine, build_session_factory
from .sagur_recipients_repository import SQLAlchemySagurRecipientsRepository
from .support_repository import SQLAlchemySupportRepository
from .uow import SQLAlchemyIdentityUnitOfWork

__all__ = [
    "Base",
    "PersonRow",
    "PersonPlatformStateRow",
    "PhoneRow",
    "PlatformAccountRow",
    "ProfileSyncQueueRow",
    "SupportTicketRow",
    "SupportMessageRow",
    "VkPhoneVerificationSessionRow",
    "SQLAlchemyIdentityRepository",
    "SQLAlchemySupportRepository",
    "SQLAlchemySagurRecipientsRepository",
    "SQLAlchemyIdentityUnitOfWork",
    "build_engine",
    "build_session_factory",
]
