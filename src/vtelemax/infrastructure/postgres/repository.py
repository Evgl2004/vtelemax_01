"""SQLAlchemy-репозиторий strict identity.

Репозиторий реализует порт `IdentityRepository` и переводит данные
между ORM-таблицами PostgreSQL и доменными моделями ядра.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from vtelemax.core.models import Person, PlatformAccount, PlatformName
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
        return self._build_person(person_id=person_row.person_id, phone_e164=phone_row.phone_e164)

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
        return self._build_person(person_id=person_row.person_id, phone_e164=phone_row.phone_e164)

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
        return self._build_person(person_id=person_row.person_id, phone_e164=phone_row.phone_e164)

    def add_person(self, person: Person) -> None:
        """Сохраняет нового человека с телефоном и уже известными аккаунтами."""

        self._session.add(PersonRow(person_id=person.person_id))
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

    def _build_person(self, person_id: UUID, phone_e164: str) -> Person:
        """Собирает доменную модель человека с полным набором аккаунтов."""

        account_statement = select(PlatformAccountRow).where(PlatformAccountRow.person_id == person_id)
        account_rows = self._session.execute(account_statement).scalars().all()
        accounts = {
            PlatformAccount(
                platform=account_row.platform,  # type: ignore[arg-type]
                external_id=account_row.external_id,
            )
            for account_row in account_rows
        }
        return Person(person_id=person_id, phone_e164=phone_e164, accounts=accounts)
