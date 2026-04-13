"""SQLAlchemy-репозиторий strict identity.

Репозиторий реализует порт `IdentityRepository` и переводит данные
между ORM-таблицами PostgreSQL и доменными моделями ядра.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from vtelemax.core.models import (
    Person,
    PersonProfilePatch,
    PlatformAccount,
    PlatformName,
    PlatformRegistrationState,
    SUPPORTED_PLATFORMS,
)
from vtelemax.core.profile_sync_models import ProfileSyncStatus, ProfileSyncTask
from vtelemax.core.ports import IdentityRepository

from .schema import (
    PersonPlatformStateRow,
    PersonRow,
    PhoneRow,
    PlatformAccountRow,
    ProfileSyncQueueRow,
)


class SQLAlchemyIdentityRepository(IdentityRepository):
    """Репозиторий strict identity на базе SQLAlchemy Session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_person_by_phone(self, phone_e164: str) -> Person | None:
        """Возвращает человека по каноническому телефону."""

        statement = (
            select(PersonRow, PhoneRow)
            .join(PhoneRow, PhoneRow.person_id == PersonRow.person_id)
            .where(PhoneRow.phone_e164 == phone_e164)
        )
        row = self._session.execute(statement).first()
        if row is None:
            return None

        person_row, phone_row = row
        return self._build_person(person_row=person_row, phone_e164=phone_row.phone_e164)

    def get_person_by_account(self, platform: PlatformName, external_id: str) -> Person | None:
        """Возвращает человека по аккаунту платформы."""

        statement = (
            select(PersonRow, PhoneRow, PlatformAccountRow)
            .join(PhoneRow, PhoneRow.person_id == PersonRow.person_id)
            .join(PlatformAccountRow, PlatformAccountRow.person_id == PersonRow.person_id)
            .where(
                PlatformAccountRow.platform == platform,
                PlatformAccountRow.external_id == external_id,
            )
        )
        row = self._session.execute(statement).first()
        if row is None:
            return None

        person_row, phone_row, _ = row
        return self._build_person(person_row=person_row, phone_e164=phone_row.phone_e164)

    def get_person_by_id(self, person_id: UUID) -> Person | None:
        """Возвращает человека по внутреннему идентификатору."""

        statement = (
            select(PersonRow, PhoneRow)
            .join(PhoneRow, PhoneRow.person_id == PersonRow.person_id)
            .where(PersonRow.person_id == person_id)
        )
        row = self._session.execute(statement).first()
        if row is None:
            return None

        person_row, phone_row = row
        return self._build_person(person_row=person_row, phone_e164=phone_row.phone_e164)

    def list_moderator_accounts(self) -> list[PlatformAccount]:
        """Возвращает аккаунты пользователей, отмеченных как модераторы."""

        statement = (
            select(PlatformAccountRow.platform, PlatformAccountRow.external_id)
            .join(PersonRow, PersonRow.person_id == PlatformAccountRow.person_id)
            .where(PersonRow.is_moderator.is_(True))
        )
        rows = self._session.execute(statement).all()
        accounts = [
            PlatformAccount(
                platform=row.platform,  # type: ignore[arg-type]
                external_id=row.external_id,
            )
            for row in rows
        ]
        accounts.sort(key=lambda account: (account.platform, account.external_id))
        return accounts

    def add_person(self, person: Person) -> None:
        """Сохраняет нового человека с телефоном и уже известными аккаунтами."""

        self._session.add(
            PersonRow(
                person_id=person.person_id,
                rules_accepted=person.rules_accepted,
                rules_accepted_at=person.rules_accepted_at,
                notifications_allowed=person.notifications_allowed,
                notifications_allowed_at=person.notifications_allowed_at,
                is_legacy=person.is_legacy,
                is_moderator=person.is_moderator,
                is_registered=person.is_registered,
                first_name_input=person.first_name_input,
                last_name_input=person.last_name_input,
                gender=person.gender,
                birth_date=person.birth_date,
                email=person.email,
                phone_verified_at=person.phone_verified_at,
                phone_verification_method=person.phone_verification_method,
                rules_accepted_tg=person.rules_accepted_tg,
                rules_accepted_tg_at=person.rules_accepted_tg_at,
                rules_accepted_vk=person.rules_accepted_vk,
                rules_accepted_vk_at=person.rules_accepted_vk_at,
                rules_accepted_max=person.rules_accepted_max,
                rules_accepted_max_at=person.rules_accepted_max_at,
                notifications_allowed_tg=person.notifications_allowed_tg,
                notifications_allowed_tg_at=person.notifications_allowed_tg_at,
                notifications_allowed_vk=person.notifications_allowed_vk,
                notifications_allowed_vk_at=person.notifications_allowed_vk_at,
                notifications_allowed_max=person.notifications_allowed_max,
                notifications_allowed_max_at=person.notifications_allowed_max_at,
            )
        )
        # В SQLite (интеграционные тесты) insertmany может нарушить ожидаемый порядок
        # вставки без явного flush; фиксируем родительскую запись заранее.
        self._session.flush()
        self._session.add(
            PhoneRow(
                phone_id=uuid4(),
                person_id=person.person_id,
                phone_e164=person.phone_e164,
            )
        )
        for account in person.accounts:
            self._session.add(
                PlatformAccountRow(
                    account_id=uuid4(),
                    person_id=person.person_id,
                    platform=account.platform,
                    external_id=account.external_id,
                )
            )
        for platform in SUPPORTED_PLATFORMS:
            state = person.get_platform_state(platform)
            self._session.add(
                PersonPlatformStateRow(
                    person_id=person.person_id,
                    platform=platform,
                    rules_accepted=state.rules_accepted,
                    rules_accepted_at=state.rules_accepted_at,
                    notifications_allowed=state.notifications_allowed,
                    notifications_allowed_at=state.notifications_allowed_at,
                    is_registered=state.is_registered,
                    registered_at=state.registered_at,
                )
            )

    def attach_account(self, person_id: UUID, account: PlatformAccount) -> None:
        """Привязывает платформенный аккаунт к существующему человеку."""

        self._session.add(
            PlatformAccountRow(
                account_id=uuid4(),
                person_id=person_id,
                platform=account.platform,
                external_id=account.external_id,
            )
        )

    def update_person_profile(self, person_id: UUID, patch: PersonProfilePatch) -> None:
        """Частично обновляет профиль пользователя в таблице `persons`."""

        person_row = self._session.get(PersonRow, person_id)
        if person_row is None:
            return

        if patch.rules_accepted is not None:
            person_row.rules_accepted = patch.rules_accepted
        if patch.rules_accepted_at is not None:
            person_row.rules_accepted_at = patch.rules_accepted_at
        if patch.notifications_allowed is not None:
            person_row.notifications_allowed = patch.notifications_allowed
        if patch.notifications_allowed_at is not None:
            person_row.notifications_allowed_at = patch.notifications_allowed_at
        if patch.is_legacy is not None:
            person_row.is_legacy = patch.is_legacy
        if patch.is_moderator is not None:
            person_row.is_moderator = patch.is_moderator
        if patch.is_registered is not None:
            person_row.is_registered = patch.is_registered
        if patch.first_name_input is not None:
            person_row.first_name_input = patch.first_name_input
        if patch.last_name_input is not None:
            person_row.last_name_input = patch.last_name_input
        if patch.gender is not None:
            person_row.gender = patch.gender
        if patch.birth_date is not None:
            person_row.birth_date = patch.birth_date
        if patch.email is not None:
            person_row.email = patch.email
        if patch.phone_verified_at is not None:
            person_row.phone_verified_at = patch.phone_verified_at
        if patch.phone_verification_method is not None:
            person_row.phone_verification_method = patch.phone_verification_method
        if patch.rules_accepted_tg is not None:
            person_row.rules_accepted_tg = patch.rules_accepted_tg
        if patch.rules_accepted_tg_at is not None:
            person_row.rules_accepted_tg_at = patch.rules_accepted_tg_at
        if patch.rules_accepted_vk is not None:
            person_row.rules_accepted_vk = patch.rules_accepted_vk
        if patch.rules_accepted_vk_at is not None:
            person_row.rules_accepted_vk_at = patch.rules_accepted_vk_at
        if patch.rules_accepted_max is not None:
            person_row.rules_accepted_max = patch.rules_accepted_max
        if patch.rules_accepted_max_at is not None:
            person_row.rules_accepted_max_at = patch.rules_accepted_max_at
        if patch.notifications_allowed_tg is not None:
            person_row.notifications_allowed_tg = patch.notifications_allowed_tg
        if patch.notifications_allowed_tg_at is not None:
            person_row.notifications_allowed_tg_at = patch.notifications_allowed_tg_at
        if patch.notifications_allowed_vk is not None:
            person_row.notifications_allowed_vk = patch.notifications_allowed_vk
        if patch.notifications_allowed_vk_at is not None:
            person_row.notifications_allowed_vk_at = patch.notifications_allowed_vk_at
        if patch.notifications_allowed_max is not None:
            person_row.notifications_allowed_max = patch.notifications_allowed_max
        if patch.notifications_allowed_max_at is not None:
            person_row.notifications_allowed_max_at = patch.notifications_allowed_max_at
        if patch.platform is not None:
            platform_row = self._session.get(PersonPlatformStateRow, (person_id, patch.platform))
            if platform_row is None:
                platform_row = PersonPlatformStateRow(
                    person_id=person_id,
                    platform=patch.platform,
                )
                self._session.add(platform_row)
            if patch.platform_rules_accepted is not None:
                platform_row.rules_accepted = patch.platform_rules_accepted
            if patch.platform_rules_accepted_at is not None:
                platform_row.rules_accepted_at = patch.platform_rules_accepted_at
            if patch.platform_notifications_allowed is not None:
                platform_row.notifications_allowed = patch.platform_notifications_allowed
            if patch.platform_notifications_allowed_at is not None:
                platform_row.notifications_allowed_at = patch.platform_notifications_allowed_at
            if patch.platform_is_registered is not None:
                platform_row.is_registered = patch.platform_is_registered
            if patch.platform_registered_at is not None:
                platform_row.registered_at = patch.platform_registered_at

            self._sync_legacy_platform_fields(person_row=person_row, platform_row=platform_row)
            self._sync_global_registration_flag(person_row=person_row, person_id=person_id)

    def enqueue_profile_sync(
        self,
        *,
        person_id: UUID,
        source_platform: PlatformName,
        payload_json: dict[str, object] | None = None,
    ) -> UUID:
        """Ставит профиль пользователя в очередь синхронизации."""

        now_utc = datetime.now(timezone.utc)
        pending_statement = (
            select(ProfileSyncQueueRow)
            .where(
                ProfileSyncQueueRow.person_id == person_id,
                ProfileSyncQueueRow.status == ProfileSyncStatus.PENDING.value,
            )
            .order_by(ProfileSyncQueueRow.updated_at.desc())
            .limit(1)
        )
        pending_row = self._session.execute(pending_statement).scalars().first()
        if pending_row is not None:
            pending_row.source_platform = source_platform
            pending_row.payload_json = payload_json
            pending_row.next_attempt_at = now_utc
            pending_row.error_text = None
            pending_row.updated_at = now_utc
            return pending_row.sync_id

        sync_id = uuid4()
        self._session.add(
            ProfileSyncQueueRow(
                sync_id=sync_id,
                person_id=person_id,
                source_platform=source_platform,
                status=ProfileSyncStatus.PENDING.value,
                attempts=0,
                next_attempt_at=now_utc,
                locked_at=None,
                error_text=None,
                payload_json=payload_json,
            )
        )
        return sync_id

    def pull_pending_profile_sync_tasks(
        self,
        *,
        limit: int,
        now_utc: datetime | None = None,
    ) -> tuple[ProfileSyncTask, ...]:
        """Выбирает pending-задачи и переводит их в processing."""

        safe_now = now_utc or datetime.now(timezone.utc)
        safe_limit = max(int(limit), 1)

        statement = (
            select(ProfileSyncQueueRow)
            .where(
                ProfileSyncQueueRow.status == ProfileSyncStatus.PENDING.value,
                ProfileSyncQueueRow.next_attempt_at <= safe_now,
            )
            .order_by(ProfileSyncQueueRow.next_attempt_at.asc(), ProfileSyncQueueRow.created_at.asc())
            .limit(safe_limit)
            .with_for_update(skip_locked=True)
        )
        rows = self._session.execute(statement).scalars().all()
        if not rows:
            return ()

        processing_started_at = datetime.now(timezone.utc)
        tasks: list[ProfileSyncTask] = []
        for row in rows:
            row.status = ProfileSyncStatus.PROCESSING.value
            row.attempts += 1
            row.locked_at = processing_started_at
            row.updated_at = processing_started_at
            tasks.append(
                ProfileSyncTask(
                    sync_id=row.sync_id,
                    person_id=row.person_id,
                    source_platform=row.source_platform,  # type: ignore[arg-type]
                    status=ProfileSyncStatus.PROCESSING,
                    attempts=row.attempts,
                    next_attempt_at=row.next_attempt_at,
                    payload_json=row.payload_json,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
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
        """Фиксирует результат обработки задачи очереди синхронизации."""

        row = self._session.get(ProfileSyncQueueRow, sync_id)
        if row is None:
            return

        row.status = status.value
        row.error_text = error_text
        if next_attempt_at is not None:
            row.next_attempt_at = next_attempt_at
        row.locked_at = None
        row.updated_at = datetime.now(timezone.utc)

    def _build_person(self, person_row: PersonRow, phone_e164: str) -> Person:
        """Собирает доменную модель человека с полным набором аккаунтов."""

        account_statement = select(PlatformAccountRow).where(PlatformAccountRow.person_id == person_row.person_id)
        account_rows = self._session.execute(account_statement).scalars().all()
        accounts = {
            PlatformAccount(
                platform=account_row.platform,  # type: ignore[arg-type]
                external_id=account_row.external_id,
            )
            for account_row in account_rows
        }
        state_statement = select(PersonPlatformStateRow).where(
            PersonPlatformStateRow.person_id == person_row.person_id
        )
        state_rows = self._session.execute(state_statement).scalars().all()
        platform_states = {
            state_row.platform: PlatformRegistrationState(
                platform=state_row.platform,  # type: ignore[arg-type]
                rules_accepted=state_row.rules_accepted,
                rules_accepted_at=state_row.rules_accepted_at,
                notifications_allowed=state_row.notifications_allowed,
                notifications_allowed_at=state_row.notifications_allowed_at,
                is_registered=state_row.is_registered,
                registered_at=state_row.registered_at,
            )
            for state_row in state_rows
        }

        person = Person(
            person_id=person_row.person_id,
            phone_e164=phone_e164,
            accounts=accounts,
            rules_accepted=person_row.rules_accepted,
            rules_accepted_at=person_row.rules_accepted_at,
            notifications_allowed=person_row.notifications_allowed,
            notifications_allowed_at=person_row.notifications_allowed_at,
            is_legacy=person_row.is_legacy,
            is_moderator=person_row.is_moderator,
            is_registered=person_row.is_registered,
            first_name_input=person_row.first_name_input,
            last_name_input=person_row.last_name_input,
            gender=person_row.gender,
            birth_date=person_row.birth_date,
            email=person_row.email,
            phone_verified_at=person_row.phone_verified_at,
            phone_verification_method=person_row.phone_verification_method,
            rules_accepted_tg=person_row.rules_accepted_tg,
            rules_accepted_tg_at=person_row.rules_accepted_tg_at,
            rules_accepted_vk=person_row.rules_accepted_vk,
            rules_accepted_vk_at=person_row.rules_accepted_vk_at,
            rules_accepted_max=person_row.rules_accepted_max,
            rules_accepted_max_at=person_row.rules_accepted_max_at,
            notifications_allowed_tg=person_row.notifications_allowed_tg,
            notifications_allowed_tg_at=person_row.notifications_allowed_tg_at,
            notifications_allowed_vk=person_row.notifications_allowed_vk,
            notifications_allowed_vk_at=person_row.notifications_allowed_vk_at,
            notifications_allowed_max=person_row.notifications_allowed_max,
            notifications_allowed_max_at=person_row.notifications_allowed_max_at,
            platform_states=platform_states,
        )
        person.is_registered = any(
            person.get_platform_state(platform).is_registered for platform in SUPPORTED_PLATFORMS
        )
        return person

    def _sync_global_registration_flag(self, *, person_row: PersonRow, person_id: UUID) -> None:
        """Обновляет агрегированный флаг `persons.is_registered` из платформенных состояний."""

        state_statement = select(PersonPlatformStateRow).where(PersonPlatformStateRow.person_id == person_id)
        state_rows = self._session.execute(state_statement).scalars().all()
        person_row.is_registered = any(state_row.is_registered for state_row in state_rows)


    def _sync_legacy_platform_fields(
        self,
        *,
        person_row: PersonRow,
        platform_row: PersonPlatformStateRow,
    ) -> None:
        """Synchronizes legacy platform consent fields in `persons` from platform state row."""

        if platform_row.platform == "telegram":
            person_row.rules_accepted_tg = platform_row.rules_accepted
            person_row.rules_accepted_tg_at = platform_row.rules_accepted_at
            person_row.notifications_allowed_tg = platform_row.notifications_allowed
            person_row.notifications_allowed_tg_at = platform_row.notifications_allowed_at
            return
        if platform_row.platform == "vk":
            person_row.rules_accepted_vk = platform_row.rules_accepted
            person_row.rules_accepted_vk_at = platform_row.rules_accepted_at
            person_row.notifications_allowed_vk = platform_row.notifications_allowed
            person_row.notifications_allowed_vk_at = platform_row.notifications_allowed_at
            return
        if platform_row.platform == "max":
            person_row.rules_accepted_max = platform_row.rules_accepted
            person_row.rules_accepted_max_at = platform_row.rules_accepted_at
            person_row.notifications_allowed_max = platform_row.notifications_allowed
            person_row.notifications_allowed_max_at = platform_row.notifications_allowed_at
            return
        raise ValueError(f"Unsupported platform value: {platform_row.platform}")
