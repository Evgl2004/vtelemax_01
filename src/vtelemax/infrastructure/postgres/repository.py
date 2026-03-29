"""SQLAlchemy-репозиторий strict identity.

Репозиторий реализует порт `IdentityRepository` и переводит данные
между ORM-таблицами PostgreSQL и доменными моделями ядра.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from vtelemax.core.models import Person, PersonProfilePatch, PlatformAccount, PlatformName
from vtelemax.core.ports import IdentityRepository

from .schema import PersonRow, PhoneRow, PlatformAccountRow


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
                is_registered=person.is_registered,
                first_name_input=person.first_name_input,
                last_name_input=person.last_name_input,
                gender=person.gender,
                birth_date=person.birth_date,
                email=person.email,
                phone_verified_at=person.phone_verified_at,
                phone_verification_method=person.phone_verification_method,
            )
        )
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
        return Person(
            person_id=person_row.person_id,
            phone_e164=phone_e164,
            accounts=accounts,
            rules_accepted=person_row.rules_accepted,
            rules_accepted_at=person_row.rules_accepted_at,
            notifications_allowed=person_row.notifications_allowed,
            notifications_allowed_at=person_row.notifications_allowed_at,
            is_legacy=person_row.is_legacy,
            is_registered=person_row.is_registered,
            first_name_input=person_row.first_name_input,
            last_name_input=person_row.last_name_input,
            gender=person_row.gender,
            birth_date=person_row.birth_date,
            email=person_row.email,
            phone_verified_at=person_row.phone_verified_at,
            phone_verification_method=person_row.phone_verification_method,
        )
