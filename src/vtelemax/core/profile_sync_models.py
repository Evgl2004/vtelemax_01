"""Доменные модели очереди синхронизации профиля с iiko."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from .models import PlatformName


class ProfileSyncStatus(StrEnum):
    """Статусы задач очереди синхронизации профиля."""

    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProfileSyncTask:
    """Задача очереди синхронизации профиля."""

    sync_id: UUID
    person_id: UUID
    source_platform: PlatformName
    status: ProfileSyncStatus
    attempts: int
    next_attempt_at: datetime
    payload_json: dict[str, object] | None
    created_at: datetime
    updated_at: datetime

