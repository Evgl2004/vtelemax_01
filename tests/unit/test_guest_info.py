"""Тесты инструмента получения детальной информации о госте."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from vtelemax.infrastructure.postgres import (
    Base,
    PersonPlatformStateRow,
    PersonRow,
    PhoneRow,
    PlatformAccountRow,
)
from vtelemax.tools.guest_info import (
    get_guest_info_by_phone,
    get_guest_info_rows_by_phone,
)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """Создает фабрику сессий на in-memory SQLite."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_get_guest_info_returns_none_for_unknown_phone(session_factory: sessionmaker[Session]) -> None:
    """При отсутствии телефона функция возвращает None."""

    with session_factory() as session:
        assert get_guest_info_by_phone(session, "+79129999999") is None


def test_get_guest_info_returns_three_platform_rows(session_factory: sessionmaker[Session]) -> None:
    """Проверяет, что в ответе всегда присутствуют telegram/vk/max."""

    person_id = uuid4()
    phone_e164 = "+79129923438"

    with session_factory() as session:
        session.add(
            PersonRow(
                person_id=person_id,
                is_legacy=False,
                is_registered=True,
                first_name_input="Иван",
                phone_verification_method="telegram_contact",
            )
        )
        session.add(
            PhoneRow(
                phone_id=uuid4(),
                person_id=person_id,
                phone_e164=phone_e164,
            )
        )
        session.add(
            PlatformAccountRow(
                account_id=uuid4(),
                person_id=person_id,
                platform="telegram",
                external_id="123456",
            )
        )
        session.add(
            PersonPlatformStateRow(
                person_id=person_id,
                platform="telegram",
                rules_accepted=True,
                rules_accepted_at=datetime(2025, 1, 1, 12, 0, 0),
                notifications_allowed=False,
                notifications_allowed_at=None,
                is_registered=True,
                registered_at=datetime(2025, 1, 2, 13, 0, 0),
            )
        )
        session.commit()

        info = get_guest_info_by_phone(session, phone_e164)
        assert info is not None
        assert info.person_id == person_id
        assert info.phone_e164 == phone_e164
        assert info.is_legacy is False
        assert info.profile_is_registered is True
        assert info.first_name_input == "Иван"
        assert info.phone_verification_method == "telegram_contact"

        assert len(info.platforms) == 3
        platforms = {item.platform: item for item in info.platforms}
        assert set(platforms.keys()) == {"telegram", "vk", "max"}

        tg = platforms["telegram"]
        assert tg.external_id == "123456"
        assert tg.rules_accepted is True
        assert tg.is_registered is True

        vk = platforms["vk"]
        assert vk.external_id is None
        assert vk.rules_accepted is None
        assert vk.is_registered is None

        max_platform = platforms["max"]
        assert max_platform.external_id is None
        assert max_platform.rules_accepted is None
        assert max_platform.is_registered is None


def test_get_guest_info_rows_match_platform_order(session_factory: sessionmaker[Session]) -> None:
    """Проверяет порядок строк в raw-выборке: telegram -> vk -> max."""

    person_id = uuid4()
    phone_e164 = "+79129923439"

    with session_factory() as session:
        session.add(
            PersonRow(
                person_id=person_id,
                is_legacy=True,
                is_registered=False,
                first_name_input=None,
                phone_verification_method=None,
            )
        )
        session.add(
            PhoneRow(
                phone_id=uuid4(),
                person_id=person_id,
                phone_e164=phone_e164,
            )
        )
        session.add(
            PlatformAccountRow(
                account_id=uuid4(),
                person_id=person_id,
                platform="vk",
                external_id="vk_user_1",
            )
        )
        session.add(
            PersonPlatformStateRow(
                person_id=person_id,
                platform="vk",
                rules_accepted=True,
                rules_accepted_at=datetime(2025, 2, 1, 10, 0, 0),
                notifications_allowed=True,
                notifications_allowed_at=datetime(2025, 2, 2, 11, 0, 0),
                is_registered=False,
                registered_at=None,
            )
        )
        session.commit()

        rows = get_guest_info_rows_by_phone(session, phone_e164)
        assert len(rows) == 3
        assert [row["platform"] for row in rows] == ["telegram", "vk", "max"]
        vk_row = rows[1]
        assert vk_row["external_id"] == "vk_user_1"
        assert vk_row["rules_accepted"] is True
        assert vk_row["notifications_allowed"] is True

