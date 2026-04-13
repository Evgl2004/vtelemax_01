"""In-memory реализация репозитория strict identity.

Модуль нужен для:

1. Юнит-тестов ядра без БД.
2. Прототипирования use-case до подключения PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from .models import Person, PersonProfilePatch, PlatformAccount, PlatformName
from .profile_sync_models import ProfileSyncStatus, ProfileSyncTask
from .ports import IdentityRepository


@dataclass(slots=True)
class _InMemoryProfileSyncRecord:
    """Внутренняя запись очереди profile_sync для in-memory репозитория."""

    sync_id: UUID
    person_id: UUID
    source_platform: PlatformName
    status: ProfileSyncStatus
    attempts: int
    next_attempt_at: datetime
    locked_at: datetime | None
    error_text: str | None
    payload_json: dict[str, object] | None
    created_at: datetime
    updated_at: datetime


class InMemoryIdentityRepository(IdentityRepository):
    """Репозиторий strict identity в оперативной памяти."""

    def __init__(self) -> None:
        self._persons_by_id: dict[UUID, Person] = {}
        self._person_id_by_phone: dict[str, UUID] = {}
        self._person_id_by_account: dict[tuple[PlatformName, str], UUID] = {}
        self._profile_sync_by_id: dict[UUID, _InMemoryProfileSyncRecord] = {}

    def get_person_by_phone(self, phone_e164: str) -> Person | None:
        """Возвращает человека по каноническому телефону."""

        person_id = self._person_id_by_phone.get(phone_e164)
        if person_id is None:
            return None
        return self._persons_by_id[person_id]

    def get_person_by_account(self, platform: PlatformName, external_id: str) -> Person | None:
        """Возвращает человека по платформенному аккаунту."""

        person_id = self._person_id_by_account.get((platform, external_id))
        if person_id is None:
            return None
        return self._persons_by_id[person_id]

    def get_person_by_id(self, person_id: UUID) -> Person | None:
        """Возвращает человека по внутреннему идентификатору."""

        return self._persons_by_id.get(person_id)

    def list_moderator_accounts(self) -> list[PlatformAccount]:
        """Возвращает аккаунты всех пользователей с признаком модератора."""

        accounts: list[PlatformAccount] = []
        for person in self._persons_by_id.values():
            if not person.is_moderator:
                continue
            accounts.extend(person.accounts)

        accounts.sort(key=lambda account: (account.platform, account.external_id))
        return accounts

    def add_person(self, person: Person) -> None:
        """Сохраняет нового человека и его индексы."""

        self._persons_by_id[person.person_id] = person
        self._person_id_by_phone[person.phone_e164] = person.person_id
        for account in person.accounts:
            self._person_id_by_account[(account.platform, account.external_id)] = person.person_id

    def attach_account(self, person_id: UUID, account: PlatformAccount) -> None:
        """Привязывает аккаунт к существующему человеку."""

        person = self._persons_by_id[person_id]
        person.accounts.add(account)
        self._person_id_by_account[(account.platform, account.external_id)] = person.person_id
        self._person_id_by_phone[person.phone_e164] = person.person_id

    def update_person_profile(self, person_id: UUID, patch: PersonProfilePatch) -> None:
        """Частично обновляет профиль человека в памяти."""

        person = self._persons_by_id[person_id]
        if patch.rules_accepted is not None:
            person.rules_accepted = patch.rules_accepted
        if patch.rules_accepted_at is not None:
            person.rules_accepted_at = patch.rules_accepted_at
        if patch.notifications_allowed is not None:
            person.notifications_allowed = patch.notifications_allowed
        if patch.notifications_allowed_at is not None:
            person.notifications_allowed_at = patch.notifications_allowed_at
        if patch.is_legacy is not None:
            person.is_legacy = patch.is_legacy
        if patch.is_moderator is not None:
            person.is_moderator = patch.is_moderator
        if patch.is_registered is not None:
            person.is_registered = patch.is_registered
        if patch.first_name_input is not None:
            person.first_name_input = patch.first_name_input
        if patch.last_name_input is not None:
            person.last_name_input = patch.last_name_input
        if patch.gender is not None:
            person.gender = patch.gender
        if patch.birth_date is not None:
            person.birth_date = patch.birth_date
        if patch.email is not None:
            person.email = patch.email
        if patch.phone_verified_at is not None:
            person.phone_verified_at = patch.phone_verified_at
        if patch.phone_verification_method is not None:
            person.phone_verification_method = patch.phone_verification_method
        if patch.rules_accepted_tg is not None:
            person.rules_accepted_tg = patch.rules_accepted_tg
        if patch.rules_accepted_tg_at is not None:
            person.rules_accepted_tg_at = patch.rules_accepted_tg_at
        if patch.rules_accepted_vk is not None:
            person.rules_accepted_vk = patch.rules_accepted_vk
        if patch.rules_accepted_vk_at is not None:
            person.rules_accepted_vk_at = patch.rules_accepted_vk_at
        if patch.rules_accepted_max is not None:
            person.rules_accepted_max = patch.rules_accepted_max
        if patch.rules_accepted_max_at is not None:
            person.rules_accepted_max_at = patch.rules_accepted_max_at
        if patch.notifications_allowed_tg is not None:
            person.notifications_allowed_tg = patch.notifications_allowed_tg
        if patch.notifications_allowed_tg_at is not None:
            person.notifications_allowed_tg_at = patch.notifications_allowed_tg_at
        if patch.notifications_allowed_vk is not None:
            person.notifications_allowed_vk = patch.notifications_allowed_vk
        if patch.notifications_allowed_vk_at is not None:
            person.notifications_allowed_vk_at = patch.notifications_allowed_vk_at
        if patch.notifications_allowed_max is not None:
            person.notifications_allowed_max = patch.notifications_allowed_max
        if patch.notifications_allowed_max_at is not None:
            person.notifications_allowed_max_at = patch.notifications_allowed_max_at

        if patch.platform is not None:
            state = person.get_platform_state(patch.platform)
            if patch.platform_rules_accepted is not None:
                state.rules_accepted = patch.platform_rules_accepted
            if patch.platform_rules_accepted_at is not None:
                state.rules_accepted_at = patch.platform_rules_accepted_at
            if patch.platform_notifications_allowed is not None:
                state.notifications_allowed = patch.platform_notifications_allowed
            if patch.platform_notifications_allowed_at is not None:
                state.notifications_allowed_at = patch.platform_notifications_allowed_at
            if patch.platform_is_registered is not None:
                state.is_registered = patch.platform_is_registered
            if patch.platform_registered_at is not None:
                state.registered_at = patch.platform_registered_at
            person.set_platform_state(state)

    def enqueue_profile_sync(
        self,
        *,
        person_id: UUID,
        source_platform: PlatformName,
        payload_json: dict[str, object] | None = None,
    ) -> UUID:
        """Ставит профиль пользователя в очередь синхронизации (in-memory)."""

        now_utc = datetime.now(timezone.utc)
        for record in self._profile_sync_by_id.values():
            if record.person_id == person_id and record.status == ProfileSyncStatus.PENDING:
                record.source_platform = source_platform
                record.payload_json = payload_json
                record.next_attempt_at = now_utc
                record.error_text = None
                record.updated_at = now_utc
                return record.sync_id

        sync_id = uuid4()
        self._profile_sync_by_id[sync_id] = _InMemoryProfileSyncRecord(
            sync_id=sync_id,
            person_id=person_id,
            source_platform=source_platform,
            status=ProfileSyncStatus.PENDING,
            attempts=0,
            next_attempt_at=now_utc,
            locked_at=None,
            error_text=None,
            payload_json=payload_json,
            created_at=now_utc,
            updated_at=now_utc,
        )
        return sync_id

    def pull_pending_profile_sync_tasks(
        self,
        *,
        limit: int,
        now_utc: datetime | None = None,
    ) -> tuple[ProfileSyncTask, ...]:
        """Выбирает pending-задачи и переводит их в processing (in-memory)."""

        safe_now = now_utc or datetime.now(timezone.utc)
        safe_limit = max(int(limit), 1)
        pending_records = sorted(
            (
                record
                for record in self._profile_sync_by_id.values()
                if record.status == ProfileSyncStatus.PENDING
                and record.next_attempt_at <= safe_now
            ),
            key=lambda record: (record.next_attempt_at, record.created_at),
        )[:safe_limit]

        processing_started_at = datetime.now(timezone.utc)
        tasks: list[ProfileSyncTask] = []
        for record in pending_records:
            record.status = ProfileSyncStatus.PROCESSING
            record.attempts += 1
            record.locked_at = processing_started_at
            record.updated_at = processing_started_at
            tasks.append(
                ProfileSyncTask(
                    sync_id=record.sync_id,
                    person_id=record.person_id,
                    source_platform=record.source_platform,
                    status=record.status,
                    attempts=record.attempts,
                    next_attempt_at=record.next_attempt_at,
                    payload_json=record.payload_json,
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
            )

        return tuple(tasks)

    def finalize_profile_sync_task(
        self,
        *,
        sync_id: UUID,
        status: ProfileSyncStatus,
        error_text: str | None = None,
        next_attempt_at: datetime | None = None,
    ) -> None:
        """Фиксирует финальный статус задачи синхронизации (in-memory)."""

        record = self._profile_sync_by_id.get(sync_id)
        if record is None:
            return

        record.status = status
        record.error_text = error_text
        if next_attempt_at is not None:
            record.next_attempt_at = next_attempt_at
        record.locked_at = None
        record.updated_at = datetime.now(timezone.utc)
