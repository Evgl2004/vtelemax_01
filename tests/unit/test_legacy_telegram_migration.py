"""Тесты утилит миграции legacy Telegram-пользователей."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from types import TracebackType
from pathlib import Path
from uuid import uuid4

from vtelemax.core import (
    GetPersonByAccountCommand,
    GetPersonByAccountUseCase,
    IdentityRepository,
    IdentityUnitOfWork,
    InMemoryIdentityRepository,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountUseCase,
    normalize_phone,
)
from vtelemax.tools.legacy_telegram_migration import (
    LEGACY_PHONE_VERIFICATION_METHOD,
    LegacyTelegramSourceRecord,
    PreparedLegacyTelegramRecord,
    build_extended_report_lines,
    LegacyMigrationReport,
    migrate_prepared_legacy_records,
    prepare_legacy_source_records,
    read_legacy_source_records,
)


class InMemoryIdentityUnitOfWork(IdentityUnitOfWork):
    """Тестовый UnitOfWork поверх in-memory репозитория."""

    def __init__(self, repository: IdentityRepository) -> None:
        self.identity_repository = repository

    def __enter__(self) -> "InMemoryIdentityUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return

    def commit(self) -> None:
        return

    def rollback(self) -> None:
        return


def _create_source_sqlite(path: Path) -> None:
    """Создает минимальный SQLite-источник legacy-данных для тестов."""

    with sqlite3.connect(str(path)) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE user_phones (
                user_id INTEGER PRIMARY KEY,
                phone TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.executemany(
            "INSERT INTO user_phones (user_id, phone, created_at) VALUES (?, ?, ?)",
            [
                (1001, "+79120000001", "2025-01-01 10:00:00"),
                (1002, "79120000002", "2025-01-02 10:00:00"),
                (1003, "bad-phone", "2025-01-03 10:00:00"),
                (1004, "+79120000004", "2025-01-04 10:00:00"),
            ],
        )
        connection.commit()


def test_read_legacy_source_records_respects_limit_and_offset() -> None:
    """Проверяет чтение source-строк с LIMIT/OFFSET."""

    local_tmp_dir = Path(".tmp") / "tests"
    local_tmp_dir.mkdir(parents=True, exist_ok=True)
    source_db = local_tmp_dir / f"legacy_{uuid4().hex}.db"

    _create_source_sqlite(source_db)
    rows = read_legacy_source_records(source_db, limit=2, offset=1)

    assert len(rows) == 2
    assert rows[0].telegram_user_id == "1002"
    assert rows[1].telegram_user_id == "1003"


def test_legacy_phone_verification_method_fits_storage_limit() -> None:
    """Проверяет, что маркер legacy-верификации помещается в VARCHAR(20)."""

    assert len(LEGACY_PHONE_VERIFICATION_METHOD) <= 20


def test_build_extended_report_lines_contains_percentage_metrics() -> None:
    """Проверяет формирование расширенной сводки миграции с процентными метриками."""

    report = LegacyMigrationReport(
        dry_run=True,
        total_source_rows=100,
        selected_rows=10,
        invalid_rows=5,
        skipped_by_phone_filter=80,
        processed_rows=10,
        created_count=4,
        attached_count=3,
        updated_count=1,
        conflict_count=1,
        failed_count=1,
        issues=(),
    )

    lines = build_extended_report_lines(report)

    assert any("Расширенный итог" in line for line in lines)
    assert any("success_total=8" in line for line in lines)
    assert any("errors_total=2" in line for line in lines)


def test_prepare_legacy_source_records_filters_phone_and_marks_invalid() -> None:
    """Проверяет нормализацию телефонов, фильтр по номеру и отбраковку мусора."""

    source_rows = (
        LegacyTelegramSourceRecord(telegram_user_id="1001", raw_phone="+7 (912) 000-00-01", created_at_raw=None),
        LegacyTelegramSourceRecord(telegram_user_id="1002", raw_phone="bad-phone", created_at_raw=None),
        LegacyTelegramSourceRecord(telegram_user_id="1003", raw_phone="79120000003", created_at_raw=None),
    )
    phone_filter_e164 = normalize_phone("+79120000003")

    result = prepare_legacy_source_records(source_rows, phone_filter_e164=phone_filter_e164)

    assert len(result.prepared_records) == 1
    assert result.prepared_records[0].telegram_user_id == "1003"
    assert result.prepared_records[0].phone_e164 == "+79120000003"
    assert result.skipped_by_phone_filter == 1
    assert len(result.invalid_issues) == 1
    assert result.invalid_issues[0].telegram_user_id == "1002"


def test_migrate_prepared_legacy_records_dry_run_detects_actions() -> None:
    """Проверяет dry-run: классификацию create/attach/update/conflict без записи в репозиторий."""

    repository = InMemoryIdentityRepository()
    use_case = RegisterOrAttachAccountUseCase(repository)

    # Базовая персона для attach/update.
    use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="500",
            raw_phone="+79120000001",
        )
    )
    # Вторая персона для конфликтного telegram account.
    use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="999",
            raw_phone="+79120000009",
        )
    )

    prepared = (
        PreparedLegacyTelegramRecord(
            telegram_user_id="100",
            raw_phone="+79120000001",
            phone_e164="+79120000001",
            source_created_at=None,
        ),
        PreparedLegacyTelegramRecord(
            telegram_user_id="500",
            raw_phone="+79120000001",
            phone_e164="+79120000001",
            source_created_at=None,
        ),
        PreparedLegacyTelegramRecord(
            telegram_user_id="999",
            raw_phone="+79120000001",
            phone_e164="+79120000001",
            source_created_at=None,
        ),
    )

    report = migrate_prepared_legacy_records(
        prepared,
        uow_factory=lambda: InMemoryIdentityUnitOfWork(repository),
        dry_run=True,
        progress_every=1,
        log=lambda _: None,
    )

    assert report.created_count == 0
    assert report.attached_count == 1
    assert report.updated_count == 1
    assert report.conflict_count == 1
    assert report.failed_count == 0

    # Dry-run ничего не должен записать: аккаунт "100" отсутствует.
    lookup = GetPersonByAccountUseCase(repository)
    person_100 = lookup.execute(GetPersonByAccountCommand(platform="telegram", external_id="100"))
    assert person_100 is None


def test_migrate_prepared_legacy_records_applies_changes_for_create_and_attach() -> None:
    """Проверяет фактическую запись create+attach и установку legacy-флагов."""

    repository = InMemoryIdentityRepository()
    lookup = GetPersonByAccountUseCase(repository)
    prepared = (
        PreparedLegacyTelegramRecord(
            telegram_user_id="101",
            raw_phone="+79129990001",
            phone_e164="+79129990001",
            source_created_at=None,
        ),
        PreparedLegacyTelegramRecord(
            telegram_user_id="202",
            raw_phone="+79129990001",
            phone_e164="+79129990001",
            source_created_at=None,
        ),
    )

    report = migrate_prepared_legacy_records(
        prepared,
        uow_factory=lambda: InMemoryIdentityUnitOfWork(repository),
        dry_run=False,
        progress_every=1,
        log=lambda _: None,
    )

    assert report.created_count == 1
    assert report.attached_count == 1
    assert report.updated_count == 0
    assert report.conflict_count == 0
    assert report.failed_count == 0

    person_101 = lookup.execute(GetPersonByAccountCommand(platform="telegram", external_id="101"))
    person_202 = lookup.execute(GetPersonByAccountCommand(platform="telegram", external_id="202"))
    assert person_101 is not None
    assert person_202 is not None
    assert person_101.person_id == person_202.person_id
    assert person_101.is_legacy is True
    assert person_101.is_registered is False
    assert person_101.rules_accepted is False
    assert person_101.notifications_allowed is False
    assert person_101.phone_verification_method == LEGACY_PHONE_VERIFICATION_METHOD
    assert person_101.get_rules_accepted_for_platform("telegram") is False
    assert person_101.get_notifications_allowed_for_platform("telegram") is False
    assert person_101.is_registered_for_platform("telegram") is False


def test_migrate_attach_does_not_degrade_registered_non_legacy_profile() -> None:
    """Проверяет, что attach из legacy-источника не сбрасывает уже активный профиль."""

    repository = InMemoryIdentityRepository()
    register_use_case = RegisterOrAttachAccountUseCase(repository)
    lookup = GetPersonByAccountUseCase(repository)

    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="vk-500",
            raw_phone="+79128880001",
            rules_accepted=True,
            is_registered=True,
            is_legacy=False,
            phone_verified_at=datetime(2026, 4, 7, 1, 0, tzinfo=timezone.utc),
            phone_verification_method="vk_contact",
        )
    )

    report = migrate_prepared_legacy_records(
        (
            PreparedLegacyTelegramRecord(
                telegram_user_id="tg-500",
                raw_phone="+79128880001",
                phone_e164="+79128880001",
                source_created_at=None,
            ),
        ),
        uow_factory=lambda: InMemoryIdentityUnitOfWork(repository),
        dry_run=False,
        progress_every=1,
        log=lambda _: None,
    )

    assert report.attached_count == 1
    person = lookup.execute(GetPersonByAccountCommand(platform="telegram", external_id="tg-500"))
    assert person is not None
    assert person.rules_accepted is True
    assert person.is_registered is True
    assert person.is_legacy is False
    assert person.phone_verification_method == "vk_contact"
    assert person.get_rules_accepted_for_platform("vk") is True
    assert person.is_registered_for_platform("vk") is True
    # Для Telegram-канала при attach из legacy профиль создается незавершенным.
    assert person.get_rules_accepted_for_platform("telegram") is False
    assert person.get_notifications_allowed_for_platform("telegram") is False
    assert person.is_registered_for_platform("telegram") is False
