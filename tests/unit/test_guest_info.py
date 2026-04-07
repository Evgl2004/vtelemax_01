"""Тесты утилиты получения детальной информации о госте по телефону."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from vtelemax.infrastructure.postgres import Base, PersonRow, PhoneRow, PersonPlatformStateRow, PlatformAccountRow
from vtelemax.tools.guest_info import GuestInfo, GuestPlatformInfo, get_guest_info_by_phone


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """Создает фабрику сессий поверх in-memory SQLite для тестов."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_get_guest_info_by_phone_not_found(session_factory: sessionmaker[Session]) -> None:
    """Проверяет возврат None при отсутствии телефона."""
    with session_factory() as session:
        result = get_guest_info_by_phone(session, "+79129999999")
        assert result is None


def test_get_guest_info_by_phone_basic(session_factory: sessionmaker[Session]) -> None:
    """Проверяет получение информации о госте с одной платформой."""
    person_id = uuid4()
    phone_e164 = "+79129923438"
    with session_factory() as session:
        # Создаём person
        person = PersonRow(
            person_id=person_id,
            is_legacy=False,
            is_registered=True,
            first_name_input="Иван",
            phone_verification_method="vk_mini_app",
        )
        session.add(person)
        # Телефон
        phone = PhoneRow(
            phone_id=uuid4(),
            person_id=person_id,
            phone_e164=phone_e164,
        )
        session.add(phone)
        # Платформенный аккаунт и состояние для telegram
        account = PlatformAccountRow(
            account_id=uuid4(),
            person_id=person_id,
            platform="telegram",
            external_id="123456",
        )
        session.add(account)
        state = PersonPlatformStateRow(
            person_id=person_id,
            platform="telegram",
            rules_accepted=True,
            rules_accepted_at=datetime(2025, 1, 1),
            notifications_allowed=False,
            notifications_allowed_at=None,
            is_registered=True,
            registered_at=datetime(2025, 1, 2),
        )
        session.add(state)
        session.commit()

        # Вызов функции
        guest_info = get_guest_info_by_phone(session, phone_e164)
        assert guest_info is not None
        assert guest_info.person_id == person_id
        assert guest_info.phone_e164 == phone_e164
        assert guest_info.is_legacy is False
        assert guest_info.profile_is_registered is True
        assert guest_info.first_name_input == "Иван"
        assert guest_info.phone_verification_method == "vk_mini_app"
        assert len(guest_info.platforms) == 3  # telegram, vk, max

        # Находим платформу telegram
        telegram_info = next(p for p in guest_info.platforms if p.platform == "telegram")
        assert telegram_info.external_id == "123456"
        assert telegram_info.rules_accepted is True
        assert telegram_info.rules_accepted_at == datetime(2025, 1, 1)
        assert telegram_info.notifications_allowed is False
        assert telegram_info.notifications_allowed_at is None
        assert telegram_info.is_registered is True
        assert telegram_info.registered_at == datetime(2025, 1, 2)

        # Платформы vk и max должны быть NULL
        vk_info = next(p for p in guest_info.platforms if p.platform == "vk")
        assert vk_info.external_id is None
        assert vk_info.rules_accepted is None
        assert vk_info.rules_accepted_at is None
        assert vk_info.notifications_allowed is None
        assert vk_info.notifications_allowed_at is None
        assert vk_info.is_registered is None
        assert vk_info.registered_at is None

        max_info = next(p for p in guest_info.platforms if p.platform == "max")
        assert max_info.external_id is None
        assert max_info.rules_accepted is None
        assert max_info.rules_accepted_at is None
        assert max_info.notifications_allowed is None
        assert max_info.notifications_allowed_at is None
        assert max_info.is_registered is None
        assert max_info.registered_at is None


def test_get_guest_info_by_phone_multiple_platforms(session_factory: sessionmaker[Session]) -> None:
    """Проверяет корректность данных при наличии нескольких платформ."""
    person_id = uuid4()
    phone_e164 = "+79129923438"
    with session_factory() as session:
        person = PersonRow(
            person_id=person_id,
            is_legacy=True,
            is_registered=False,
            first_name_input=None,
            phone_verification_method=None,
        )
        session.add(person)
        phone = PhoneRow(
            phone_id=uuid4(),
            person_id=person_id,
            phone_e164=phone_e164,
        )
        session.add(phone)
        # Аккаунт vk
        account_vk = PlatformAccountRow(
            account_id=uuid4(),
            person_id=person_id,
            platform="vk",
            external_id="vk_user_1",
        )
        session.add(account_vk)
        # Состояние vk
        state_vk = PersonPlatformStateRow(
            person_id=person_id,
            platform="vk",
            rules_accepted=True,
            rules_accepted_at=datetime(2025, 2, 1),
            notifications_allowed=True,
            notifications_allowed_at=datetime(2025, 2, 2),
            is_registered=False,
            registered_at=None,
        )
        session.add(state_vk)
        # Аккаунт max без состояния
        account_max = PlatformAccountRow(
            account_id=uuid4(),
            person_id=person_id,
            platform="max",
            external_id="max_user_1",
        )
        session.add(account_max)
        # telegram отсутствует
        session.commit()

        guest_info = get_guest_info_by_phone(session, phone_e164)
        assert guest_info is not None
        assert guest_info.is_legacy is True
        assert guest_info.profile_is_registered is False

        platforms = {p.platform: p for p in guest_info.platforms}
        assert len(platforms) == 3

        # Проверяем vk
        vk = platforms["vk"]
        assert vk.external_id == "vk_user_1"
        assert vk.rules_accepted is True
        assert vk.notifications_allowed is True
        assert vk.is_registered is False

        # Проверяем max (есть аккаунт, но нет состояния)
        max_ = platforms["max"]
        assert max_.external_id == "max_user_1"
        assert max_.rules_accepted is None
        assert max_.notifications_allowed is None
        assert max_.is_registered is None

        # Проверяем telegram (нет ничего)
        tg = platforms["telegram"]
        assert tg.external_id is None
        assert tg.rules_accepted is None
        assert tg.notifications_allowed is None
        assert tg.is_registered is None