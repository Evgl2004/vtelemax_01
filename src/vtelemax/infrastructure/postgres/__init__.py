"""PostgreSQL-инфраструктура strict identity."""

from .repository import SQLAlchemyIdentityRepository
from .schema import Base, PersonRow, PhoneRow, PlatformAccountRow
from .session import build_engine, build_session_factory
from .uow import SQLAlchemyIdentityUnitOfWork

__all__ = [
    "Base",
    "PersonRow",
    "PhoneRow",
    "PlatformAccountRow",
    "SQLAlchemyIdentityRepository",
    "SQLAlchemyIdentityUnitOfWork",
    "build_engine",
    "build_session_factory",
]
