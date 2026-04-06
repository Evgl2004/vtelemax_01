"""PostgreSQL-инфраструктура strict identity."""

from .repository import SQLAlchemyIdentityRepository
from .schema import (
    Base,
    PersonRow,
    PersonPlatformStateRow,
    PhoneRow,
    PlatformAccountRow,
    SupportMessageRow,
    SupportTicketRow,
)
from .session import build_engine, build_session_factory
from .support_repository import SQLAlchemySupportRepository
from .uow import SQLAlchemyIdentityUnitOfWork

__all__ = [
    "Base",
    "PersonRow",
    "PersonPlatformStateRow",
    "PhoneRow",
    "PlatformAccountRow",
    "SupportTicketRow",
    "SupportMessageRow",
    "SQLAlchemyIdentityRepository",
    "SQLAlchemySupportRepository",
    "SQLAlchemyIdentityUnitOfWork",
    "build_engine",
    "build_session_factory",
]
