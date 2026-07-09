"""Модели исходящего события регистрации гостя для SAGUR."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from .models import PlatformName

SAGUR_GUEST_REGISTERED_EVENT_TYPE = "guest_registered"

RegistrationOrigin = Literal["new_registration", "legacy_upgrade"]


class SagurRegistrationIikoStatus(StrEnum):
    """Статусы iikoCard-части единого регистра SAGUR-регистрации."""

    LOOKUP_STARTED = "lookup_started"
    CREATE_STARTED = "create_started"
    CREATED = "created"
    EXISTING = "existing"
    RESULT_UNKNOWN = "result_unknown"
    NOT_REQUIRED = "not_required"
    MANUAL_REVIEW = "manual_review"
    FAILED_TERMINAL = "failed_terminal"


class SagurRegistrationDeliveryStatus(StrEnum):
    """Статусы доставки события регистрации в SAGUR."""

    NOT_READY = "not_ready"
    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    RETRY_SCHEDULED = "retry_scheduled"
    CONFLICT = "conflict"
    NOT_REQUIRED = "not_required"
    MANUAL_REVIEW = "manual_review"
    FAILED_TERMINAL = "failed_terminal"


SAGUR_REGISTRATION_TERMINAL_DELIVERY_STATUSES = frozenset(
    {
        SagurRegistrationDeliveryStatus.SENT.value,
        SagurRegistrationDeliveryStatus.CONFLICT.value,
        SagurRegistrationDeliveryStatus.NOT_REQUIRED.value,
        SagurRegistrationDeliveryStatus.MANUAL_REVIEW.value,
        SagurRegistrationDeliveryStatus.FAILED_TERMINAL.value,
    }
)


@dataclass(frozen=True, slots=True)
class SagurRegistrationContext:
    """Контекст текущего финального шага регистрации в боте."""

    person_id: UUID
    platform: PlatformName
    external_id: str
    phone_e164: str
    registration_origin: RegistrationOrigin


@dataclass(frozen=True, slots=True)
class SagurRegistrationEventTask:
    """Задача отправки уже собранного события регистрации в SAGUR."""

    record_id: UUID
    event_id: str
    request_id: str
    payload_body: bytes
    attempts: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SagurRegistrationRecoveryTask:
    """Задача контрольного поиска iikoCard для неизвестного результата создания."""

    record_id: UUID
    person_id: UUID
    platform: PlatformName
    external_id: str
    phone_e164: str
    registration_origin: RegistrationOrigin
    recovery_attempts: int
    created_at: datetime
    updated_at: datetime
