"""Use-case сценарии очереди синхронизации профиля с iiko."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .models import PlatformName, SUPPORTED_PLATFORMS
from .ports import IdentityUnitOfWork
from .profile_sync_models import ProfileSyncStatus, ProfileSyncTask


@dataclass(frozen=True, slots=True)
class EnqueueProfileSyncCommand:
    """Команда постановки профиля пользователя в очередь синхронизации."""

    person_id: UUID
    source_platform: PlatformName
    payload_json: dict[str, object] | None = None


class EnqueueProfileSyncTransactionalUseCase:
    """Транзакционно ставит профиль пользователя в очередь синхронизации."""

    def __init__(self, unit_of_work_factory: Callable[[], IdentityUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, command: EnqueueProfileSyncCommand) -> UUID:
        """Ставит задачу в очередь и возвращает идентификатор sync-задачи."""

        if command.source_platform not in SUPPORTED_PLATFORMS:
            raise ValueError("Платформа синхронизации не поддерживается.")

        with self._unit_of_work_factory() as unit_of_work:
            sync_id = unit_of_work.identity_repository.enqueue_profile_sync(
                person_id=command.person_id,
                source_platform=command.source_platform,
                payload_json=command.payload_json,
            )
            unit_of_work.commit()
            return sync_id


class PullPendingProfileSyncTasksTransactionalUseCase:
    """Транзакционно выбирает pending-задачи и переводит их в processing."""

    def __init__(self, unit_of_work_factory: Callable[[], IdentityUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(
        self,
        *,
        limit: int = 20,
        now_utc: datetime | None = None,
    ) -> tuple[ProfileSyncTask, ...]:
        """Выбирает пачку pending-задач для обработки воркером."""

        safe_limit = max(int(limit), 1)
        with self._unit_of_work_factory() as unit_of_work:
            tasks = unit_of_work.identity_repository.pull_pending_profile_sync_tasks(
                limit=safe_limit,
                now_utc=now_utc,
            )
            unit_of_work.commit()
            return tasks


@dataclass(frozen=True, slots=True)
class FinalizeProfileSyncTaskCommand:
    """Команда финализации задачи очереди синхронизации."""

    sync_id: UUID
    status: ProfileSyncStatus
    error_text: str | None = None
    next_attempt_at: datetime | None = None


class FinalizeProfileSyncTaskTransactionalUseCase:
    """Фиксирует результат обработки задачи очереди синхронизации."""

    def __init__(self, unit_of_work_factory: Callable[[], IdentityUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, command: FinalizeProfileSyncTaskCommand) -> None:
        """Сохраняет финальный статус задачи (`pending`/`done`/`failed`)."""

        if command.status not in {
            ProfileSyncStatus.PENDING,
            ProfileSyncStatus.DONE,
            ProfileSyncStatus.FAILED,
        }:
            raise ValueError("Для финализации задачи допустимы статусы pending/done/failed.")

        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.identity_repository.finalize_profile_sync_task(
                sync_id=command.sync_id,
                status=command.status,
                error_text=command.error_text,
                next_attempt_at=command.next_attempt_at,
            )
            unit_of_work.commit()
