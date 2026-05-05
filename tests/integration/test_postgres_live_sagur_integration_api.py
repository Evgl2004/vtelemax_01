"""Живые PostgreSQL-тесты snapshot/delta логики SAGUR integration API."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from vtelemax.apps.sagur_integration_api_app import (
    _decode_delta_cursor,
    _decode_snapshot_cursor,
    _fetch_delta_page,
    _fetch_snapshot_page,
)
from vtelemax.infrastructure.postgres import (
    Base,
    PersonPlatformStateRow,
    PersonRow,
    PhoneRow,
    PlatformAccountRow,
    build_engine,
)
from vtelemax.infrastructure.postgres.session import build_session_factory


def _build_postgres_test_dsn() -> str:
    """Собирает DSN для живых PostgreSQL-тестов из env."""

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


def _utc(y: int, m: int, d: int, hh: int, mm: int, ss: int) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)


def _add_person_with_channel(
    session: Session,
    *,
    person_id: UUID,
    phone_e164: str,
    platform: str,
    external_id: str,
    account_created_at: datetime,
    state_updated_at: datetime | None,
    rules_accepted: bool,
    notifications_allowed: bool,
    is_registered: bool,
) -> None:
    """Добавляет гостя с каналом платформы и (опционально) platform state."""

    session.add(PersonRow(person_id=person_id))
    session.add(
        PhoneRow(
            phone_id=uuid4(),
            person_id=person_id,
            phone_e164=phone_e164,
            created_at=account_created_at,
        )
    )
    session.add(
        PlatformAccountRow(
            account_id=uuid4(),
            person_id=person_id,
            platform=platform,
            external_id=external_id,
            created_at=account_created_at,
        )
    )
    # На live PostgreSQL фиксируем родительские записи до platform state,
    # чтобы исключить нарушение FK из-за порядка пакетной вставки.
    session.flush()
    if state_updated_at is None:
        return
    session.add(
        PersonPlatformStateRow(
            person_id=person_id,
            platform=platform,
            rules_accepted=rules_accepted,
            rules_accepted_at=state_updated_at if rules_accepted else None,
            notifications_allowed=notifications_allowed,
            notifications_allowed_at=state_updated_at if notifications_allowed else None,
            is_registered=is_registered,
            registered_at=state_updated_at if is_registered else None,
            created_at=state_updated_at,
            updated_at=state_updated_at,
        )
    )


@pytest.fixture(scope="function")
def postgres_session_factory() -> sessionmaker[Session]:
    """Подготавливает изолированную схему в реальном PostgreSQL."""

    if os.getenv("VTELEMAX_RUN_POSTGRES_LIVE_TESTS") != "1":
        pytest.skip("Живые PostgreSQL-тесты отключены (VTELEMAX_RUN_POSTGRES_LIVE_TESTS != 1).")

    pytest.importorskip("psycopg")
    dsn = _build_postgres_test_dsn()
    base_engine: Engine = build_engine(dsn)

    schema_name = f"vtelemax_sagur_test_{uuid4().hex[:8]}"
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
def test_live_snapshot_fetches_all_rows_without_duplicates(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    """Проверяет snapshot пагинацию без пропусков/дублей на реальном PostgreSQL."""

    with postgres_session_factory() as session:
        _add_person_with_channel(
            session,
            person_id=UUID("00000000-0000-0000-0000-000000000001"),
            phone_e164="+79990000001",
            platform="telegram",
            external_id="tg-1",
            account_created_at=_utc(2026, 5, 5, 10, 1, 0),
            state_updated_at=_utc(2026, 5, 5, 10, 6, 0),
            rules_accepted=True,
            notifications_allowed=True,
            is_registered=True,
        )
        _add_person_with_channel(
            session,
            person_id=UUID("00000000-0000-0000-0000-000000000002"),
            phone_e164="+79990000002",
            platform="vk",
            external_id="vk-2",
            account_created_at=_utc(2026, 5, 5, 10, 2, 0),
            state_updated_at=_utc(2026, 5, 5, 10, 7, 0),
            rules_accepted=True,
            notifications_allowed=False,
            is_registered=True,
        )
        _add_person_with_channel(
            session,
            person_id=UUID("00000000-0000-0000-0000-000000000003"),
            phone_e164="+79990000003",
            platform="max",
            external_id="max-3",
            account_created_at=_utc(2026, 5, 5, 10, 3, 0),
            state_updated_at=None,
            rules_accepted=False,
            notifications_allowed=False,
            is_registered=False,
        )
        session.commit()

    first_items, first_cursor = _fetch_snapshot_page(
        session_factory=postgres_session_factory,
        limit=2,
        cursor=None,
    )
    assert len(first_items) == 2
    assert first_cursor is not None

    second_items, second_cursor = _fetch_snapshot_page(
        session_factory=postgres_session_factory,
        limit=2,
        cursor=_decode_snapshot_cursor(first_cursor),
    )
    assert len(second_items) == 1
    assert second_cursor is None

    all_items = first_items + second_items
    channel_keys = {(item["person_id"], item["platform"]) for item in all_items}
    assert len(all_items) == 3
    assert len(channel_keys) == 3


@pytest.mark.postgres_live
def test_live_delta_filters_by_since_and_preserves_stable_pagination(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    """Проверяет отбор delta по since и стабильность cursor-пагинации."""

    since = _utc(2026, 5, 5, 10, 0, 0)

    with postgres_session_factory() as session:
        # Входит в delta по updated_at (> since).
        _add_person_with_channel(
            session,
            person_id=UUID("00000000-0000-0000-0000-000000000011"),
            phone_e164="+79990000011",
            platform="telegram",
            external_id="tg-11",
            account_created_at=_utc(2026, 5, 5, 9, 50, 0),
            state_updated_at=_utc(2026, 5, 5, 10, 1, 0),
            rules_accepted=True,
            notifications_allowed=True,
            is_registered=True,
        )
        # Входит в delta по account_created_at (> since), state нет.
        _add_person_with_channel(
            session,
            person_id=UUID("00000000-0000-0000-0000-000000000012"),
            phone_e164="+79990000012",
            platform="vk",
            external_id="vk-12",
            account_created_at=_utc(2026, 5, 5, 10, 2, 0),
            state_updated_at=None,
            rules_accepted=False,
            notifications_allowed=False,
            is_registered=False,
        )
        # Входит в delta по account_created_at (> since), тот же effective_updated_at что выше.
        _add_person_with_channel(
            session,
            person_id=UUID("00000000-0000-0000-0000-000000000013"),
            phone_e164="+79990000013",
            platform="max",
            external_id="max-13",
            account_created_at=_utc(2026, 5, 5, 10, 2, 0),
            state_updated_at=None,
            rules_accepted=False,
            notifications_allowed=False,
            is_registered=False,
        )
        # Не входит в delta (и account_created_at, и updated_at <= since).
        _add_person_with_channel(
            session,
            person_id=UUID("00000000-0000-0000-0000-000000000014"),
            phone_e164="+79990000014",
            platform="telegram",
            external_id="tg-14",
            account_created_at=_utc(2026, 5, 5, 9, 40, 0),
            state_updated_at=_utc(2026, 5, 5, 9, 59, 0),
            rules_accepted=True,
            notifications_allowed=True,
            is_registered=True,
        )
        session.commit()

    first_items, first_cursor, first_max_seen = _fetch_delta_page(
        session_factory=postgres_session_factory,
        since=since,
        limit=2,
        cursor=None,
    )
    assert len(first_items) == 2
    assert first_cursor is not None
    assert first_max_seen is not None

    second_items, second_cursor, second_max_seen = _fetch_delta_page(
        session_factory=postgres_session_factory,
        since=since,
        limit=2,
        cursor=_decode_delta_cursor(first_cursor),
    )
    assert len(second_items) == 1
    assert second_cursor is None
    assert second_max_seen is not None

    all_items = first_items + second_items
    assert len(all_items) == 3
    keys = {(item["person_id"], item["platform"]) for item in all_items}
    assert keys == {
        ("00000000-0000-0000-0000-000000000011", "telegram"),
        ("00000000-0000-0000-0000-000000000012", "vk"),
        ("00000000-0000-0000-0000-000000000013", "max"),
    }

    max_seen_combined = max(first_max_seen, second_max_seen)
    assert max_seen_combined == _utc(2026, 5, 5, 10, 2, 0)
