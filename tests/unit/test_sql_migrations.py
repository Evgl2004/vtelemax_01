"""Тесты инфраструктурного модуля SQL-миграций."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from sqlalchemy import create_engine

from vtelemax.infrastructure.migrations import (
    apply_migrations,
    list_migration_files,
    read_sql_statements,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_list_migration_files_returns_sorted_sql_files() -> None:
    """Проверяет сортировку SQL-файлов миграций по имени на реальном каталоге."""

    migrations_dir = _PROJECT_ROOT / "migrations" / "sql"
    files = list_migration_files(migrations_dir)
    names = [path.name for path in files]

    assert names == sorted(names)
    assert names[:2] == ["0001_strict_identity.sql", "0002_support_tickets.sql"]


def test_list_migration_files_raises_when_directory_has_no_sql() -> None:
    """Грязный сценарий: несуществующий каталог не должен считаться валидным."""

    with pytest.raises(FileNotFoundError):
        list_migration_files(_PROJECT_ROOT / "migrations" / "missing_sql_dir")


def test_read_sql_statements_strips_comments_and_transaction_markers() -> None:
    """Проверяет очистку комментариев и BEGIN/COMMIT на реальной миграции."""

    migration_file = _PROJECT_ROOT / "migrations" / "sql" / "0001_strict_identity.sql"
    statements = read_sql_statements(migration_file)

    joined = "\n".join(statements).upper()
    assert "BEGIN" not in joined
    assert "COMMIT" not in joined
    assert any("CREATE TABLE IF NOT EXISTS PERSONS" in statement.upper() for statement in statements)


def test_read_sql_statements_raises_on_empty_migration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Грязный сценарий: миграция только с комментариями должна давать ошибку."""

    def _fake_read_text(self: Path, encoding: str = "utf-8") -> str:  # noqa: ARG001
        return "-- only comments\nBEGIN;\nCOMMIT;\n"

    monkeypatch.setattr(Path, "read_text", _fake_read_text)

    with pytest.raises(ValueError):
        read_sql_statements(_PROJECT_ROOT / "migrations" / "sql" / "fake_empty.sql")


def test_migration_0005_uses_non_destructive_upsert_for_platform_states() -> None:
    """Проверяет, что 0005 не перетирает уже заполненные платформенные состояния."""

    migration_file = _PROJECT_ROOT / "migrations" / "sql" / "0005_person_platform_states.sql"
    content = migration_file.read_text(encoding="utf-8")
    upper = content.upper()

    assert "ON CONFLICT (PERSON_ID, PLATFORM) DO UPDATE" in upper
    assert "RULES_ACCEPTED = CASE" in upper
    assert "NOTIFICATIONS_ALLOWED = CASE" in upper
    assert "IS_REGISTERED = CASE" in upper
    assert "COALESCE(" in upper
    assert "PERSON_PLATFORM_STATES.RULES_ACCEPTED_AT" in upper
    assert "PERSON_PLATFORM_STATES.NOTIFICATIONS_ALLOWED_AT" in upper
    assert "PERSON_PLATFORM_STATES.REGISTERED_AT" in upper

    # Защита от регрессии: нельзя возвращать жесткое затирание через EXCLUDED.*
    assert "RULES_ACCEPTED = EXCLUDED.RULES_ACCEPTED" not in upper
    assert "NOTIFICATIONS_ALLOWED = EXCLUDED.NOTIFICATIONS_ALLOWED" not in upper
    assert "IS_REGISTERED = EXCLUDED.IS_REGISTERED" not in upper


def test_migration_0008_syncs_legacy_platform_consents_from_platform_states() -> None:
    """Checks migration 0008 backfills legacy per-platform fields from canonical state table."""

    migration_file = _PROJECT_ROOT / "migrations" / "sql" / "0008_sync_legacy_platform_consents.sql"
    content = migration_file.read_text(encoding="utf-8")
    upper = content.upper()

    assert "UPDATE PERSONS AS P" in upper
    assert "FROM PERSON_PLATFORM_STATES AS S" in upper
    assert "RULES_ACCEPTED_TG" in upper
    assert "RULES_ACCEPTED_VK" in upper
    assert "RULES_ACCEPTED_MAX" in upper
    assert "NOTIFICATIONS_ALLOWED_TG" in upper
    assert "NOTIFICATIONS_ALLOWED_VK" in upper
    assert "NOTIFICATIONS_ALLOWED_MAX" in upper


def test_migration_0012_adds_platform_account_lifecycle_and_active_unique_index() -> None:
    """Проверяет, что 0012 добавляет lifecycle-статусы и partial unique для active."""

    migration_file = _PROJECT_ROOT / "migrations" / "sql" / "0012_platform_accounts_lifecycle.sql"
    content = migration_file.read_text(encoding="utf-8")
    upper = content.upper()

    assert "ADD COLUMN IF NOT EXISTS LIFECYCLE_STATUS" in upper
    assert "SET LIFECYCLE_STATUS = 'HISTORICAL'" in upper
    assert "WHERE PLATFORM = 'VK'" in upper
    assert "PENDING_VERIFICATION" in upper
    assert "WHERE PLATFORM = 'MAX'" in upper
    assert "PA.PLATFORM = 'TELEGRAM'" in upper
    assert "PPS.REGISTERED_AT IS NOT NULL" in upper
    assert "ROW_NUMBER() OVER" in upper
    assert "ALTER COLUMN LIFECYCLE_STATUS SET DEFAULT 'ACTIVE'" in upper
    assert "ALTER COLUMN LIFECYCLE_STATUS SET NOT NULL" in upper
    assert "CREATE INDEX IF NOT EXISTS IX_PLATFORM_ACCOUNTS_PERSON_ID_PLATFORM_LIFECYCLE" in upper
    assert "CREATE UNIQUE INDEX IF NOT EXISTS UX_PLATFORM_ACCOUNTS_ONE_ACTIVE_PER_PERSON_PLATFORM" in upper


def test_migration_0015_allows_used_after_campaign_coupon_status() -> None:
    migration_file = _PROJECT_ROOT / "migrations" / "sql" / "0015_sagur_coupons_used_after_campaign.sql"
    content = migration_file.read_text(encoding="utf-8")
    upper = content.upper()

    assert "DROP CONSTRAINT IF EXISTS CK_PERSON_COUPONS_STATUS_ALLOWED" in upper
    assert "ADD CONSTRAINT CK_PERSON_COUPONS_STATUS_ALLOWED" in upper
    assert "USED_AFTER_CAMPAIGN" in upper


def test_migration_0016_adds_coupon_valid_until_column() -> None:
    migration_file = _PROJECT_ROOT / "migrations" / "sql" / "0016_sagur_coupons_valid_until.sql"
    content = migration_file.read_text(encoding="utf-8")
    upper = content.upper()

    assert "ADD COLUMN IF NOT EXISTS VALID_UNTIL" in upper
    assert "TIMESTAMPTZ" in upper


def test_migration_0017_adds_coupon_title_column() -> None:
    migration_file = _PROJECT_ROOT / "migrations" / "sql" / "0017_sagur_coupons_title.sql"
    content = migration_file.read_text(encoding="utf-8")
    upper = content.upper()

    assert "ADD COLUMN IF NOT EXISTS COUPON_TITLE" in upper
    assert "VARCHAR(255)" in upper


def test_migration_0018_creates_sagur_guest_registration_events_registry() -> None:
    migration_file = _PROJECT_ROOT / "migrations" / "sql" / "0018_sagur_guest_registration_events.sql"
    content = migration_file.read_text(encoding="utf-8")
    upper = content.upper()

    assert "CREATE TABLE IF NOT EXISTS SAGUR_GUEST_REGISTRATION_EVENTS" in upper
    assert "CUSTOMER_ID VARCHAR(128)" in upper
    assert "PAYLOAD_BODY BYTEA" in upper
    assert "RESULT_UNKNOWN" in upper
    assert "CREATE UNIQUE INDEX IF NOT EXISTS UQ_SAGUR_GUEST_REGISTRATION_EVENTS_EVENT_ID" in upper
    assert "CREATE UNIQUE INDEX IF NOT EXISTS UQ_SAGUR_GUEST_REGISTRATION_EVENTS_ACTIVE_CONTEXT" in upper


def test_migration_0019_creates_sagur_message_interaction_events_registry() -> None:
    """Проверяет однотабличное хранение и частичные индексы активной очереди."""

    migration_file = (
        _PROJECT_ROOT / "migrations" / "sql" / "0019_sagur_message_interaction_events.sql"
    )
    content = migration_file.read_text(encoding="utf-8")
    upper = content.upper()

    assert "CREATE TABLE IF NOT EXISTS SAGUR_MESSAGE_INTERACTION_EVENTS" in upper
    assert "INTERACTION_ID BIGINT NOT NULL" in upper
    assert "UNIQUE (PLATFORM, BOT_SCOPE, PLATFORM_CALLBACK_ID)" in upper
    assert "USER_ACTION_STATUS VARCHAR(32)" in upper
    assert "DELIVERY_STATUS VARCHAR(32)" in upper
    assert "DELIVERY_LEASE_ID UUID" in upper
    assert "CK_SAGUR_MESSAGE_INTERACTION_EVENTS_ATTEMPTS_CONSISTENT" in upper
    assert "CK_SAGUR_MESSAGE_INTERACTION_EVENTS_PROCESSING_LEASE_CONSISTENT" in upper
    assert "CK_SAGUR_MESSAGE_INTERACTION_EVENTS_DELIVERY_COMPLETION_CONSISTENT" in upper
    assert "CK_SAGUR_MESSAGE_INTERACTION_EVENTS_DELIVERY_ERROR_CONSISTENT" in upper
    assert "CK_SAGUR_MESSAGE_INTERACTION_EVENTS_USER_ACTION_CONSISTENT" in upper
    assert "WHERE DELIVERY_STATUS IN ('PENDING', 'RETRY_SCHEDULED')" in upper
    assert "WHERE DELIVERY_STATUS = 'PROCESSING'" in upper
    assert (
        "CREATE INDEX IF NOT EXISTS IX_SAGUR_MESSAGE_INTERACTION_EVENTS_INTERACTION_ID" not in upper
    )


def test_apply_migrations_tracks_applied_files_and_skips_reapply(tmp_path: Path) -> None:
    """Проверяет, что миграция применяется один раз и не выполняется повторно."""

    migrations_dir = tmp_path / "sql"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    migration_file = migrations_dir / "0001_test.sql"
    migration_file.write_text(
        dedent(
            """
            BEGIN;
            CREATE TABLE IF NOT EXISTS test_items (
                id INTEGER PRIMARY KEY,
                value TEXT
            );
            INSERT INTO test_items (id, value) VALUES (1, 'ok');
            COMMIT;
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    first_applied = apply_migrations(engine=engine, migrations_dir=migrations_dir)
    second_applied = apply_migrations(engine=engine, migrations_dir=migrations_dir)

    assert first_applied == 1
    assert second_applied == 0

    with engine.begin() as connection:
        rows = connection.exec_driver_sql("SELECT COUNT(*) FROM test_items").scalar_one()
        history_rows = connection.exec_driver_sql(
            "SELECT COUNT(*) FROM sql_migration_history WHERE migration_name = '0001_test.sql'"
        ).scalar_one()

    assert rows == 1
    assert history_rows == 1


def test_apply_migrations_fails_if_applied_migration_was_changed(tmp_path: Path) -> None:
    """Проверяет защиту от изменения уже применённого SQL-файла."""

    migrations_dir = tmp_path / "sql"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    migration_file = migrations_dir / "0001_test.sql"
    migration_file.write_text("CREATE TABLE IF NOT EXISTS x(id INTEGER PRIMARY KEY);\n", encoding="utf-8")

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    applied = apply_migrations(engine=engine, migrations_dir=migrations_dir)
    assert applied == 1

    # Меняем файл после "применения" и проверяем, что система это отлавливает.
    migration_file.write_text(
        "CREATE TABLE IF NOT EXISTS x(id INTEGER PRIMARY KEY, value TEXT);\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        apply_migrations(engine=engine, migrations_dir=migrations_dir)
