"""Тесты use-case слоя очереди синхронизации профиля."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from vtelemax.core import (
    EnqueueProfileSyncCommand,
    EnqueueProfileSyncTransactionalUseCase,
    FinalizeProfileSyncTaskCommand,
    FinalizeProfileSyncTaskTransactionalUseCase,
    InMemoryIdentityRepository,
    Person,
    PlatformAccount,
    ProfileSyncStatus,
    PullPendingProfileSyncTasksTransactionalUseCase,
)


class _InMemoryIdentityUoW:
    """Минимальный in-memory UoW для тестов profile sync use-case."""

    def __init__(self, repository: InMemoryIdentityRepository) -> None:
        self.identity_repository = repository

    def __enter__(self) -> "_InMemoryIdentityUoW":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:  # type: ignore[no-untyped-def]
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def test_profile_sync_use_cases_enqueue_deduplicates_pending_task() -> None:
    """Повторная постановка должна переиспользовать pending-задачу для того же пользователя."""

    repository = InMemoryIdentityRepository()
    person = Person(
        person_id=uuid4(),
        phone_e164="+79129990000",
        accounts={PlatformAccount(platform="telegram", external_id="1001")},
    )
    repository.add_person(person)
    uow_factory = lambda: _InMemoryIdentityUoW(repository)
    enqueue_use_case = EnqueueProfileSyncTransactionalUseCase(unit_of_work_factory=uow_factory)

    first_sync_id = enqueue_use_case.execute(
        EnqueueProfileSyncCommand(
            person_id=person.person_id,
            source_platform="telegram",
            payload_json={"trigger": "profile_edit"},
        )
    )
    second_sync_id = enqueue_use_case.execute(
        EnqueueProfileSyncCommand(
            person_id=person.person_id,
            source_platform="vk",
            payload_json={"trigger": "profile_edit"},
        )
    )

    assert first_sync_id == second_sync_id


def test_profile_sync_use_cases_pull_and_finalize_lifecycle() -> None:
    """Проверяет базовый lifecycle: enqueue -> pull(processing) -> finalize(done)."""

    repository = InMemoryIdentityRepository()
    person = Person(
        person_id=uuid4(),
        phone_e164="+79129990001",
        accounts={PlatformAccount(platform="vk", external_id="2002")},
    )
    repository.add_person(person)
    uow_factory = lambda: _InMemoryIdentityUoW(repository)
    enqueue_use_case = EnqueueProfileSyncTransactionalUseCase(unit_of_work_factory=uow_factory)
    pull_use_case = PullPendingProfileSyncTasksTransactionalUseCase(unit_of_work_factory=uow_factory)
    finalize_use_case = FinalizeProfileSyncTaskTransactionalUseCase(unit_of_work_factory=uow_factory)

    sync_id = enqueue_use_case.execute(
        EnqueueProfileSyncCommand(
            person_id=person.person_id,
            source_platform="vk",
        )
    )
    pulled = pull_use_case.execute(limit=10)

    assert len(pulled) == 1
    assert pulled[0].sync_id == sync_id
    assert pulled[0].status == ProfileSyncStatus.PROCESSING
    assert pulled[0].attempts == 1
    assert pulled[0].source_platform == "vk"

    finalize_use_case.execute(
        FinalizeProfileSyncTaskCommand(
            sync_id=sync_id,
            status=ProfileSyncStatus.DONE,
        )
    )
    pulled_after_done = pull_use_case.execute(limit=10)
    assert pulled_after_done == ()


def test_profile_sync_use_cases_finalize_pending_respects_next_attempt() -> None:
    """Проверяет, что задача с next_attempt_at в будущем не выбирается до наступления срока."""

    repository = InMemoryIdentityRepository()
    person = Person(
        person_id=uuid4(),
        phone_e164="+79129990002",
        accounts={PlatformAccount(platform="max", external_id="3003")},
    )
    repository.add_person(person)
    uow_factory = lambda: _InMemoryIdentityUoW(repository)
    enqueue_use_case = EnqueueProfileSyncTransactionalUseCase(unit_of_work_factory=uow_factory)
    pull_use_case = PullPendingProfileSyncTasksTransactionalUseCase(unit_of_work_factory=uow_factory)
    finalize_use_case = FinalizeProfileSyncTaskTransactionalUseCase(unit_of_work_factory=uow_factory)

    sync_id = enqueue_use_case.execute(
        EnqueueProfileSyncCommand(
            person_id=person.person_id,
            source_platform="max",
        )
    )
    pulled = pull_use_case.execute(limit=10)
    assert len(pulled) == 1

    next_attempt_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    finalize_use_case.execute(
        FinalizeProfileSyncTaskCommand(
            sync_id=sync_id,
            status=ProfileSyncStatus.PENDING,
            error_text="temporary",
            next_attempt_at=next_attempt_at,
        )
    )

    pulled_too_early = pull_use_case.execute(limit=10, now_utc=datetime.now(timezone.utc))
    assert pulled_too_early == ()

