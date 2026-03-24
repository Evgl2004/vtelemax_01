"""Интеграционные тесты strict identity на реальном PostgreSQL.

Тесты запускаются только при явном флаге:

1. `VTELEMAX_RUN_POSTGRES_LIVE_TESTS=1`
2. установлен драйвер `psycopg`

Чтобы не затрагивать чужие данные, для каждого прогона создается
временная схема с уникальным именем и удаляется после тестов.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from vtelemax.core import (
    IdentityConflictError,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
)
from vtelemax.infrastructure.postgres import Base, SQLAlchemyIdentityUnitOfWork, build_engine
from vtelemax.infrastructure.postgres.session import build_session_factory


def _build_postgres_test_dsn() -> str:
    """Собирает DSN для живых PostgreSQL-тестов из env-переменных."""

    load_dotenv()

    explicit_dsn = os.getenv("VTELEMAX_TEST_POSTGRES_DSN")
    if explicit_dsn:
        return explicit_dsn

    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5433")
    database = os.getenv("POSTGRES_DB", "postgres")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "1234")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"


@pytest.fixture(scope="module")
def postgres_session_factory() -> sessionmaker[Session]:
    """Подготавливает изолированную тестовую схему в реальном PostgreSQL."""

    if os.getenv("VTELEMAX_RUN_POSTGRES_LIVE_TESTS") != "1":
        pytest.skip("Живые PostgreSQL-тесты отключены (VTELEMAX_RUN_POSTGRES_LIVE_TESTS != 1).")

    pytest.importorskip("psycopg")
    dsn = _build_postgres_test_dsn()
    base_engine: Engine = build_engine(dsn)

    schema_name = f"vtelemax_test_{uuid4().hex[:8]}"
    with base_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))

    engine = base_engine.execution_options(schema_translate_map={None: schema_name})
    Base.metadata.create_all(engine)

    try:
        yield build_session_factory(engine)
    finally:
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        base_engine.dispose()


@pytest.mark.postgres_live
def test_live_postgres_merges_accounts(postgres_session_factory: sessionmaker[Session]) -> None:
    """Проверяет объединение Telegram/VK аккаунтов по телефону на реальном PostgreSQL."""

    use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: SQLAlchemyIdentityUnitOfWork(postgres_session_factory)
    )

    first = use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="1001",
            raw_phone="+79123456789",
        )
    )
    second = use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="2002",
            raw_phone="8 (912) 345-67-89",
        )
    )

    assert first.person_id == second.person_id


@pytest.mark.postgres_live
def test_live_postgres_rejects_account_rebind(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    """Проверяет запрет перепривязки одного аккаунта на другой телефон."""

    use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: SQLAlchemyIdentityUnitOfWork(postgres_session_factory)
    )

    use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="3001",
            raw_phone="+79125555555",
        )
    )

    with pytest.raises(IdentityConflictError):
        use_case.execute(
            RegisterOrAttachAccountCommand(
                platform="telegram",
                external_id="3001",
                raw_phone="+79990001122",
            )
        )
