"""PostgreSQL-инфраструктура strict identity."""

from .repository import SQLAlchemyIdentityRepository
from .schema import (
    Base,
    PersonCouponRow,
    PersonRow,
    PersonPlatformStateRow,
    PhoneRow,
    PlatformAccountRow,
    ProfileSyncQueueRow,
    SagurCouponEventRow,
    SupportMessageRow,
    SupportTicketRow,
    VkPhoneVerificationSessionRow,
)
from .sagur_coupons_repository import SQLAlchemySagurCouponsRepository
from .session import build_engine, build_session_factory
from .sagur_recipients_repository import SQLAlchemySagurRecipientsRepository
from .support_repository import SQLAlchemySupportRepository
from .uow import SQLAlchemyIdentityUnitOfWork

__all__ = [
    "Base",
    "PersonCouponRow",
    "PersonRow",
    "PersonPlatformStateRow",
    "PhoneRow",
    "PlatformAccountRow",
    "ProfileSyncQueueRow",
    "SagurCouponEventRow",
    "SupportTicketRow",
    "SupportMessageRow",
    "VkPhoneVerificationSessionRow",
    "SQLAlchemyIdentityRepository",
    "SQLAlchemySupportRepository",
    "SQLAlchemySagurRecipientsRepository",
    "SQLAlchemySagurCouponsRepository",
    "SQLAlchemyIdentityUnitOfWork",
    "build_engine",
    "build_session_factory",
]
