"""CLI-утилита миграции legacy-пользователей Telegram из старого SQLite-бота.

Сценарий миграции:

1. Читает `user_id` и `phone` из SQLite-таблицы `user_phones` старого проекта.
2. Нормализует телефоны и переносит записи в strict identity (PostgreSQL).
3. Устанавливает флаги переноса: `is_legacy=True`, `is_registered=False`.
4. Поддерживает dry-run, прогресс в процентах и точечный перенос одного номера.

Важно:
1. Источник (старый проект) хранит минимальные данные: фактически только телефон и Telegram ID.
2. Расширенный профиль (имя/дата рождения/email) заполняется в новом onboarding/legacy-флоу.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
import sqlite3

from vtelemax.core import normalize_phone
from vtelemax.infrastructure.postgres import (
    SQLAlchemyIdentityUnitOfWork,
    build_engine,
    build_session_factory,
)
from vtelemax.settings import AppSettings
from vtelemax.tools.legacy_telegram_migration import (
    DEFAULT_SOURCE_SQLITE_PATH,
    LegacyMigrationReport,
    LegacyMigrationIssue,
    build_report_lines,
    migrate_prepared_legacy_records,
    prepare_legacy_source_records,
    read_legacy_source_records,
)


def _build_parser() -> argparse.ArgumentParser:
    """Создает parser аргументов командной строки."""

    default_source = os.getenv("LEGACY_SOURCE_SQLITE_PATH", str(DEFAULT_SOURCE_SQLITE_PATH))
    parser = argparse.ArgumentParser(
        description=(
            "Переносит legacy-пользователей Telegram из старой SQLite-базы "
            "в strict identity PostgreSQL."
        )
    )
    parser.add_argument(
        "--source-db",
        default=default_source,
        help=(
            "Путь к SQLite-файлу старого бота. "
            f"По умолчанию: {default_source}"
        ),
    )
    parser.add_argument(
        "--phone",
        default=None,
        help=(
            "Точечный перенос одного номера (например, +79129923438). "
            "Удобно для предварительных тестов."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Ограничить количество source-строк (для пакетного запуска).",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Смещение source-строк (для пакетного запуска).",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=500,
        help="Период печати прогресса (по умолчанию 500 строк).",
    )
    parser.add_argument(
        "--max-issues",
        type=int,
        default=50,
        help="Максимум примеров проблемных строк в итоговом отчете.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Печатать подробный лог по каждой обработанной записи.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Проверка без записи в PostgreSQL.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Подтвердить реальную запись в PostgreSQL.",
    )
    return parser


def _validate_mode(*, dry_run: bool, yes: bool) -> tuple[bool, str | None]:
    """Проверяет согласованность флагов режима запуска."""

    if dry_run and yes:
        return False, "Нельзя одновременно указывать --dry-run и --yes."
    if not dry_run and not yes:
        return (
            False,
            "Укажите --dry-run для проверки или --yes для фактического переноса.",
        )
    return True, None


def _print_header(
    *,
    source_db_path: Path,
    dry_run: bool,
    phone_filter_e164: str | None,
    limit: int | None,
    offset: int,
) -> None:
    """Печатает стартовую информацию перед миграцией."""

    print("[legacy-migrate] Запуск миграции legacy Telegram-пользователей.")
    print(f"[legacy-migrate] Source DB: {source_db_path}")
    print(f"[legacy-migrate] Режим: {'dry-run' if dry_run else 'apply'}")
    if phone_filter_e164 is not None:
        print(f"[legacy-migrate] Фильтр по номеру: {phone_filter_e164}")
    else:
        print("[legacy-migrate] Фильтр по номеру: не задан")
    print(f"[legacy-migrate] LIMIT={limit}, OFFSET={offset}")


def _print_issues(issues: tuple[LegacyMigrationIssue, ...]) -> None:
    """Печатает проблемные примеры строк из отчета."""

    if not issues:
        return
    print(f"[legacy-migrate] Примеры проблемных строк ({len(issues)}):")
    for issue in issues:
        print(
            "[legacy-migrate]   "
            f"telegram_id={issue.telegram_user_id}, "
            f"phone={issue.raw_phone}, reason={issue.reason}"
        )


def _print_combined_report(
    *,
    migration_report: LegacyMigrationReport,
    invalid_issues: tuple[LegacyMigrationIssue, ...],
    skipped_by_phone_filter: int,
    source_rows_count: int,
) -> None:
    """Печатает объединенный отчет подготовки + миграции."""

    normalized_report = LegacyMigrationReport(
        dry_run=migration_report.dry_run,
        total_source_rows=source_rows_count,
        selected_rows=migration_report.selected_rows,
        invalid_rows=len(invalid_issues),
        skipped_by_phone_filter=skipped_by_phone_filter,
        processed_rows=migration_report.processed_rows,
        created_count=migration_report.created_count,
        attached_count=migration_report.attached_count,
        updated_count=migration_report.updated_count,
        conflict_count=migration_report.conflict_count,
        failed_count=migration_report.failed_count,
        issues=migration_report.issues,
    )
    for line in build_report_lines(normalized_report):
        print(line)

    if invalid_issues:
        print(
            "[legacy-migrate] Внимание: обнаружены невалидные source-строки. "
            "Они были пропущены."
        )

    _print_issues(invalid_issues)
    _print_issues(migration_report.issues)


def main() -> int:
    """Точка входа CLI-утилиты."""

    parser = _build_parser()
    args = parser.parse_args()

    is_mode_ok, mode_error = _validate_mode(dry_run=args.dry_run, yes=args.yes)
    if not is_mode_ok:
        print(f"[legacy-migrate] Ошибка режима запуска: {mode_error}", file=sys.stderr)
        return 2

    dry_run = bool(args.dry_run)
    source_db_path = Path(args.source_db).expanduser()
    if not source_db_path.exists():
        print(
            f"[legacy-migrate] Source SQLite-файл не найден: {source_db_path}",
            file=sys.stderr,
        )
        return 2

    phone_filter_e164: str | None = None
    if args.phone:
        try:
            phone_filter_e164 = normalize_phone(args.phone)
        except ValueError as error:
            print(
                f"[legacy-migrate] Некорректный номер в --phone: {error}",
                file=sys.stderr,
            )
            return 2

    _print_header(
        source_db_path=source_db_path,
        dry_run=dry_run,
        phone_filter_e164=phone_filter_e164,
        limit=args.limit,
        offset=args.offset,
    )

    try:
        source_records = read_legacy_source_records(
            source_db_path,
            limit=args.limit,
            offset=args.offset,
        )
    except sqlite3.Error as error:
        print(f"[legacy-migrate] Ошибка чтения source SQLite: {error}", file=sys.stderr)
        return 1

    print(f"[legacy-migrate] Прочитано строк из source: {len(source_records)}")
    preparation_result = prepare_legacy_source_records(
        source_records,
        phone_filter_e164=phone_filter_e164,
    )

    print(f"[legacy-migrate] Подготовлено к обработке: {len(preparation_result.prepared_records)}")
    print(f"[legacy-migrate] Невалидных строк: {len(preparation_result.invalid_issues)}")
    print(
        "[legacy-migrate] Пропущено по фильтру номера: "
        f"{preparation_result.skipped_by_phone_filter}"
    )

    if not preparation_result.prepared_records:
        print("[legacy-migrate] Нет данных для переноса. Завершено.")
        _print_issues(preparation_result.invalid_issues[: min(20, len(preparation_result.invalid_issues))])
        return 0

    settings = AppSettings()
    engine = build_engine(settings.postgres_sqlalchemy_dsn, echo=settings.postgres_echo)
    session_factory = build_session_factory(engine)

    def uow_factory() -> SQLAlchemyIdentityUnitOfWork:
        """Создает UoW для одной транзакции миграции."""

        return SQLAlchemyIdentityUnitOfWork(session_factory)

    try:
        migration_report = migrate_prepared_legacy_records(
            preparation_result.prepared_records,
            uow_factory=uow_factory,
            dry_run=dry_run,
            progress_every=args.progress_every,
            verbose=args.verbose,
            max_issue_samples=max(1, int(args.max_issues)),
            log=print,
        )
    finally:
        engine.dispose()

    _print_combined_report(
        migration_report=migration_report,
        invalid_issues=preparation_result.invalid_issues,
        skipped_by_phone_filter=preparation_result.skipped_by_phone_filter,
        source_rows_count=len(source_records),
    )

    if migration_report.failed_count > 0:
        print(
            "[legacy-migrate] Завершено с ошибками записи. "
            "Проверьте лог и повторите запуск после исправлений.",
            file=sys.stderr,
        )
        return 1

    if migration_report.conflict_count > 0:
        print(
            "[legacy-migrate] Завершено с конфликтами strict identity. "
            "Конфликты нужно разобрать отдельно.",
        )
    else:
        print("[legacy-migrate] Завершено успешно.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
