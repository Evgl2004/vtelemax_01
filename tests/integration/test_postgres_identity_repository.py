"""Интеграционные тесты SQLAlchemy-репозитория strict identity.

Тесты выполняются на SQLite in-memory через SQLAlchemy metadata.
Это быстрый способ проверить транзакционную семантику и контракты
репозитория до подключения реального PostgreSQL в окружении.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from vtelemax.core import (
    IdentityConflictError,
    Person,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
)
from vtelemax.infrastructure.postgres import Base, SQLAlchemyIdentityUnitOfWork, build_session_factory


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    """Создает фабрику сессий поверх in-memory SQLite для integration-тестов."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def test_transactional_use_case_merges_accounts_by_phone(
    session_factory: sessionmaker[Session],
) -> None:
    """Проверяет объединение Telegram/VK аккаунтов в одного человека по телефону."""

    use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: SQLAlchemyIdentityUnitOfWork(session_factory)
    )

    person_from_tg = use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="1001",
            raw_phone="+7 (912) 345-67-89",
        )
    )
    person_from_vk = use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="2002",
            raw_phone="8 (912) 345-67-89",
        )
    )

    assert person_from_tg.person_id == person_from_vk.person_id

    with SQLAlchemyIdentityUnitOfWork(session_factory) as unit_of_work:
        by_phone = unit_of_work.identity_repository.get_person_by_phone("+79123456789")
        by_tg = unit_of_work.identity_repository.get_person_by_account("telegram", "1001")
        by_vk = unit_of_work.identity_repository.get_person_by_account("vk", "2002")

    assert by_phone is not None
    assert by_tg is not None
    assert by_vk is not None
    assert by_phone.person_id == by_tg.person_id == by_vk.person_id
    assert len(by_phone.accounts) == 2


def test_transactional_use_case_raises_conflict_for_rebind(
    session_factory: sessionmaker[Session],
) -> None:
    """Проверяет запрет перепривязки существующего аккаунта на другой телефон."""

    use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: SQLAlchemyIdentityUnitOfWork(session_factory)
    )

    use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="1001",
            raw_phone="+79123456789",
        )
    )

    with pytest.raises(IdentityConflictError):
        use_case.execute(
            RegisterOrAttachAccountCommand(
                platform="telegram",
                external_id="1001",
                raw_phone="+79991234567",
            )
        )


def test_unit_of_work_rolls_back_if_commit_not_called(
    session_factory: sessionmaker[Session],
) -> None:
    """Проверяет автo rollback в `__exit__`, если commit не был вызван."""

    person_id = uuid4()
    with SQLAlchemyIdentityUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.identity_repository.add_person(
            Person(
                person_id=person_id,
                phone_e164="+79120000000",
            )
        )
        # commit не вызывается специально.

    with SQLAlchemyIdentityUnitOfWork(session_factory) as unit_of_work:
        person = unit_of_work.identity_repository.get_person_by_phone("+79120000000")

    assert person is None


def test_transactional_use_case_rejects_unknown_platform(
    session_factory: sessionmaker[Session],
) -> None:
    """Проверяет валидацию неизвестной платформы на уровне use-case."""

    use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: SQLAlchemyIdentityUnitOfWork(session_factory)
    )

    with pytest.raises(ValueError):
        use_case.execute(
            RegisterOrAttachAccountCommand(
                platform="discord",  # type: ignore[arg-type]
                external_id="1001",
                raw_phone="+79123456789",
            )
        )


def test_unit_of_work_converts_db_integrity_error_to_domain_conflict(
    session_factory: sessionmaker[Session],
) -> None:
    """Проверяет трансляцию DB-конфликта в `IdentityConflictError`."""

    with SQLAlchemyIdentityUnitOfWork(session_factory) as unit_of_work:
        unit_of_work.identity_repository.add_person(
            Person(
                person_id=uuid4(),
                phone_e164="+79121111111",
            )
        )
        unit_of_work.identity_repository.add_person(
            Person(
                person_id=uuid4(),
                phone_e164="+79121111111",
            )
        )
        with pytest.raises(IdentityConflictError):
            unit_of_work.commit()


def test_platform_state_update_keeps_legacy_platform_flags_in_sync(
    session_factory: sessionmaker[Session],
) -> None:
    """Checks legacy `persons.*_tg/vk/max` flags are synchronized on platform state updates."""

    use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: SQLAlchemyIdentityUnitOfWork(session_factory)
    )

    use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="max",
            external_id="max-1",
            raw_phone="+79129990011",
            rules_accepted=True,
            notifications_allowed=True,
            notifications_allowed_at=None,
            is_registered=True,
        )
    )
    use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="tg-1",
            raw_phone="+79129990011",
            rules_accepted=True,
            notifications_allowed=True,
            notifications_allowed_at=None,
            is_registered=True,
        )
    )

    with SQLAlchemyIdentityUnitOfWork(session_factory) as unit_of_work:
        person = unit_of_work.identity_repository.get_person_by_phone("+79129990011")

    assert person is not None
    assert person.rules_accepted_max is True
    assert person.notifications_allowed_max is True
    assert person.rules_accepted_tg is True
    assert person.notifications_allowed_tg is True
