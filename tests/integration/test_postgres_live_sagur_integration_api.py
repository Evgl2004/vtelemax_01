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
    lifecycle_status: str = "active",
) -> None:
    """Добавляет гостя с каналом платформы и (опционально) platform state."""

    # Важно: фиксируем profile_updated_at в контрольной временной шкале теста,
    # чтобы effective_updated_at не "прыгал" на текущее время сервера.
    session.add(
        PersonRow(
            person_id=person_id,
            created_at=account_created_at,
            updated_at=state_updated_at or account_created_at,
        )
    )
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
            lifecycle_status=lifecycle_status,
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
    # Для сценариев, где сразу после вставки выполняется session.get(...)
    # (без commit), нужен flush после добавления platform-state.
    session.flush()


def _add_channel_for_existing_person(
    session: Session,
    *,
    person_id: UUID,
    platform: str,
    external_id: str,
    account_created_at: datetime,
    lifecycle_status: str = "active",
) -> None:
    """Добавляет новый канал существующему гостю."""

    session.add(
        PlatformAccountRow(
            account_id=uuid4(),
            person_id=person_id,
            platform=platform,
            external_id=external_id,
            lifecycle_status=lifecycle_status,
            created_at=account_created_at,
        )
    )


def _set_platform_state(
    session: Session,
    *,
    person_id: UUID,
    platform: str,
    updated_at: datetime,
    rules_accepted: bool,
    notifications_allowed: bool,
    is_registered: bool,
) -> None:
    """Обновляет платформенное состояние существующего канала гостя."""

    state_row = session.get(PersonPlatformStateRow, (person_id, platform))
    if state_row is None:
        raise AssertionError("Platform state row not found for update in live test.")

    state_row.rules_accepted = rules_accepted
    state_row.rules_accepted_at = updated_at if rules_accepted else None
    state_row.notifications_allowed = notifications_allowed
    state_row.notifications_allowed_at = updated_at if notifications_allowed else None
    state_row.is_registered = is_registered
    state_row.registered_at = updated_at if is_registered else None
    state_row.updated_at = updated_at


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
    assert all("effective_updated_at" in item for item in all_items)
    assert all("registered_at" in item for item in all_items)
    assert all("profile" in item for item in all_items)


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
            person_id=UUID("10000000-0000-0000-0000-000000000001"),
            phone_e164="+79000001001",
            platform="telegram",
            external_id="test_tg_user_1",
            account_created_at=_utc(2026, 5, 5, 9, 50, 0),
            state_updated_at=_utc(2026, 5, 5, 10, 1, 0),
            rules_accepted=True,
            notifications_allowed=True,
            is_registered=True,
        )
        # Входит в delta по account_created_at (> since), state нет.
        _add_person_with_channel(
            session,
            person_id=UUID("20000000-0000-0000-0000-000000000002"),
            phone_e164="+79000002002",
            platform="vk",
            external_id="test_vk_user_2",
            account_created_at=_utc(2026, 5, 5, 10, 2, 0),
            state_updated_at=None,
            rules_accepted=False,
            notifications_allowed=False,
            is_registered=False,
        )
        # Входит в delta по account_created_at (> since), тот же effective_updated_at что выше.
        _add_person_with_channel(
            session,
            person_id=UUID("30000000-0000-0000-0000-000000000003"),
            phone_e164="+79000003003",
            platform="max",
            external_id="test_max_user_3",
            account_created_at=_utc(2026, 5, 5, 10, 2, 0),
            state_updated_at=None,
            rules_accepted=False,
            notifications_allowed=False,
            is_registered=False,
        )
        # Не входит в delta (и account_created_at, и updated_at <= since).
        _add_person_with_channel(
            session,
            person_id=UUID("40000000-0000-0000-0000-000000000004"),
            phone_e164="+79000004004",
            platform="telegram",
            external_id="test_tg_user_4",
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
    assert all(item["effective_updated_at"] is not None for item in all_items)
    assert all("registered_at" in item for item in all_items)
    assert all("profile" in item for item in all_items)
    keys = {(item["person_id"], item["platform"]) for item in all_items}
    assert keys == {
        ("10000000-0000-0000-0000-000000000001", "telegram"),
        ("20000000-0000-0000-0000-000000000002", "vk"),
        ("30000000-0000-0000-0000-000000000003", "max"),
    }

    max_seen_combined = max(first_max_seen, second_max_seen)
    assert max_seen_combined == _utc(2026, 5, 5, 10, 2, 0)


@pytest.mark.postgres_live
def test_live_delta_includes_new_guest_channel(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    """Проверяет, что новый гость попадает в delta по created_at канала."""

    since = _utc(2026, 5, 5, 10, 0, 0)
    with postgres_session_factory() as session:
        _add_person_with_channel(
            session,
            person_id=UUID("00000000-0000-0000-0000-000000000021"),
            phone_e164="+79990000021",
            platform="telegram",
            external_id="tg-21",
            account_created_at=_utc(2026, 5, 5, 10, 5, 0),
            state_updated_at=None,
            rules_accepted=False,
            notifications_allowed=False,
            is_registered=False,
        )
        session.commit()

    items, next_cursor, max_seen_updated_at = _fetch_delta_page(
        session_factory=postgres_session_factory,
        since=since,
        limit=10,
        cursor=None,
    )
    assert next_cursor is None
    assert max_seen_updated_at == _utc(2026, 5, 5, 10, 5, 0)
    assert all(item["effective_updated_at"] is not None for item in items)
    assert all("registered_at" in item for item in items)
    assert all("profile" in item for item in items)
    assert ("00000000-0000-0000-0000-000000000021", "telegram") in {
        (item["person_id"], item["platform"]) for item in items
    }


@pytest.mark.postgres_live
def test_live_delta_includes_new_channel_for_existing_guest(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    """Проверяет попадание нового канала существующего гостя в delta."""

    since = _utc(2026, 5, 5, 10, 0, 0)
    person_id = UUID("00000000-0000-0000-0000-000000000022")

    with postgres_session_factory() as session:
        _add_person_with_channel(
            session,
            person_id=person_id,
            phone_e164="+79990000022",
            platform="telegram",
            external_id="tg-22",
            account_created_at=_utc(2026, 5, 5, 9, 50, 0),
            state_updated_at=_utc(2026, 5, 5, 9, 55, 0),
            rules_accepted=True,
            notifications_allowed=True,
            is_registered=True,
        )
        _add_channel_for_existing_person(
            session,
            person_id=person_id,
            platform="vk",
            external_id="vk-22",
            account_created_at=_utc(2026, 5, 5, 10, 6, 0),
        )
        session.commit()

    items, _, _ = _fetch_delta_page(
        session_factory=postgres_session_factory,
        since=since,
        limit=10,
        cursor=None,
    )
    keys = {(item["person_id"], item["platform"]) for item in items}
    assert ("00000000-0000-0000-0000-000000000022", "vk") in keys
    assert ("00000000-0000-0000-0000-000000000022", "telegram") not in keys


@pytest.mark.postgres_live
def test_live_delta_includes_notifications_deactivation(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    """Проверяет, что отключение уведомлений попадает в delta."""

    since = _utc(2026, 5, 5, 10, 0, 0)
    person_id = UUID("00000000-0000-0000-0000-000000000023")

    with postgres_session_factory() as session:
        _add_person_with_channel(
            session,
            person_id=person_id,
            phone_e164="+79990000023",
            platform="max",
            external_id="max-23",
            account_created_at=_utc(2026, 5, 5, 9, 40, 0),
            state_updated_at=_utc(2026, 5, 5, 9, 50, 0),
            rules_accepted=True,
            notifications_allowed=True,
            is_registered=True,
        )
        _set_platform_state(
            session,
            person_id=person_id,
            platform="max",
            updated_at=_utc(2026, 5, 5, 10, 7, 0),
            rules_accepted=True,
            notifications_allowed=False,
            is_registered=True,
        )
        session.commit()

    items, _, _ = _fetch_delta_page(
        session_factory=postgres_session_factory,
        since=since,
        limit=10,
        cursor=None,
    )
    target_items = [
        item
        for item in items
        if item["person_id"] == "00000000-0000-0000-0000-000000000023"
        and item["platform"] == "max"
    ]
    assert len(target_items) == 1
    assert target_items[0]["notifications_allowed"] is False


@pytest.mark.postgres_live
def test_live_delta_includes_profile_changes(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    """Проверяет, что изменение профильных полей в persons попадает в delta."""

    since = _utc(2026, 5, 5, 10, 0, 0)
    person_id = UUID("00000000-0000-0000-0000-000000000024")
    profile_updated_at = _utc(2026, 5, 5, 10, 8, 0)

    with postgres_session_factory() as session:
        _add_person_with_channel(
            session,
            person_id=person_id,
            phone_e164="+79990000024",
            platform="telegram",
            external_id="tg-24",
            account_created_at=_utc(2026, 5, 5, 9, 40, 0),
            state_updated_at=_utc(2026, 5, 5, 9, 45, 0),
            rules_accepted=True,
            notifications_allowed=True,
            is_registered=True,
        )
        session.commit()

    with postgres_session_factory() as session:
        person_row = session.get(PersonRow, person_id)
        assert person_row is not None
        person_row.first_name_input = "Иван"
        person_row.last_name_input = "Иванов"
        person_row.updated_at = profile_updated_at
        session.commit()

    items, _, max_seen_updated_at = _fetch_delta_page(
        session_factory=postgres_session_factory,
        since=since,
        limit=10,
        cursor=None,
    )

    target_items = [
        item
        for item in items
        if item["person_id"] == "00000000-0000-0000-0000-000000000024"
        and item["platform"] == "telegram"
    ]
    assert len(target_items) == 1
    assert target_items[0]["profile"]["first_name"] == "Иван"
    assert target_items[0]["profile"]["last_name"] == "Иванов"
    assert target_items[0]["effective_updated_at"] == "2026-05-05T10:08:00Z"
    assert max_seen_updated_at == profile_updated_at


@pytest.mark.postgres_live
def test_live_snapshot_prefers_active_account_over_historical(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    """Проверяет, что snapshot выбирает active аккаунт, а historical игнорирует."""

    person_id = UUID("00000000-0000-0000-0000-000000000031")
    with postgres_session_factory() as session:
        _add_person_with_channel(
            session,
            person_id=person_id,
            phone_e164="+79990000031",
            platform="telegram",
            external_id="tg-active-31",
            account_created_at=_utc(2026, 5, 5, 10, 1, 0),
            state_updated_at=_utc(2026, 5, 5, 10, 6, 0),
            rules_accepted=True,
            notifications_allowed=True,
            is_registered=True,
            lifecycle_status="active",
        )
        _add_channel_for_existing_person(
            session,
            person_id=person_id,
            platform="telegram",
            external_id="tg-historical-31",
            account_created_at=_utc(2026, 5, 5, 10, 9, 0),
            lifecycle_status="historical",
        )
        session.commit()

    items, _ = _fetch_snapshot_page(
        session_factory=postgres_session_factory,
        limit=10,
        cursor=None,
    )
    target = next(
        item
        for item in items
        if item["person_id"] == "00000000-0000-0000-0000-000000000031"
        and item["platform"] == "telegram"
    )
    assert target["external_id"] == "tg-active-31"
    assert target["registered_at"] == "2026-05-05T10:06:00Z"


@pytest.mark.postgres_live
def test_live_delta_vk_pending_verification_is_controlled_by_flag(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    """Проверяет, что VK pending_verification в delta попадает только при включённом флаге."""

    since = _utc(2026, 5, 5, 10, 0, 0)
    with postgres_session_factory() as session:
        _add_person_with_channel(
            session,
            person_id=UUID("00000000-0000-0000-0000-000000000032"),
            phone_e164="+79990000032",
            platform="vk",
            external_id="vk-pending-32",
            account_created_at=_utc(2026, 5, 5, 10, 7, 0),
            state_updated_at=_utc(2026, 5, 5, 10, 8, 0),
            rules_accepted=True,
            notifications_allowed=False,
            is_registered=True,
            lifecycle_status="pending_verification",
        )
        session.commit()

    disabled_items, _, _ = _fetch_delta_page(
        session_factory=postgres_session_factory,
        since=since,
        limit=10,
        cursor=None,
        include_vk_pending_verification=False,
    )
    assert all(
        not (
            item["person_id"] == "00000000-0000-0000-0000-000000000032"
            and item["platform"] == "vk"
        )
        for item in disabled_items
    )

    enabled_items, _, _ = _fetch_delta_page(
        session_factory=postgres_session_factory,
        since=since,
        limit=10,
        cursor=None,
        include_vk_pending_verification=True,
    )
    target = next(
        item
        for item in enabled_items
        if item["person_id"] == "00000000-0000-0000-0000-000000000032"
        and item["platform"] == "vk"
    )
    assert target["external_id"] == "vk-pending-32"
    assert target["registered_at"] == "2026-05-05T10:08:00Z"
