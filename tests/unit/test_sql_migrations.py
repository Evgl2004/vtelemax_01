"""Тесты инфраструктурного модуля SQL-миграций."""

from __future__ import annotations

from pathlib import Path

import pytest

from vtelemax.infrastructure.migrations import (
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
