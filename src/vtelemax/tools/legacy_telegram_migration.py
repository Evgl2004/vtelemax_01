"""Инструменты миграции legacy-пользователей Telegram из старого SQLite-бота.

Модуль реализует перенос данных из таблицы `user_phones` проекта `sobalbot`
в строгую identity-модель `vtelemax`.

Основные задачи миграции:

1. Прочитать старые связки `telegram_user_id -> phone`.
2. Нормализовать телефон в формат E.164 (`+7XXXXXXXXXX`).
3. Создать/допривязать аккаунты в новой модели strict identity.
4. Отметить перенесенный профиль как legacy (`is_legacy=True`) и незавершенный (`is_registered=False`).
5. Показать прозрачный прогресс и итоговую сводку.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from vtelemax.core import (
    IdentityConflictError,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountUseCase,
    normalize_phone,
)
from vtelemax.core.ports import IdentityUnitOfWork

# Путь по умолчанию соответствует локальной структуре, согласованной в проекте.
DEFAULT_SOURCE_SQLITE_PATH = Path(r"C:\Users\admin_eas\PycharmProjects\sobalbot\data\bot_requests.db")
LEGACY_PHONE_VERIFICATION_METHOD = "legacy_import_sobalbot"


@dataclass(frozen=True, slots=True)
class LegacyTelegramSourceRecord:
    """Сырая запись из старого SQLite-источника."""

    telegram_user_id: str
    raw_phone: str
    created_at_raw: str | None


@dataclass(frozen=True, slots=True)
class PreparedLegacyTelegramRecord:
    """Подготовленная запись для миграции в strict identity."""

    telegram_user_id: str
    raw_phone: str
    phone_e164: str
    source_created_at: datetime | None


@dataclass(frozen=True, slots=True)
class LegacyMigrationIssue:
    """Проблемная запись миграции с объяснением причины."""

    telegram_user_id: str
    raw_phone: str
    reason: str


@dataclass(frozen=True, slots=True)
class LegacyPreparationResult:
    """Результат подготовки source-данных к миграции."""

    prepared_records: tuple[PreparedLegacyTelegramRecord, ...]
    invalid_issues: tuple[LegacyMigrationIssue, ...]
    skipped_by_phone_filter: int


@dataclass(frozen=True, slots=True)
class LegacyMigrationReport:
    """Итоговая статистика миграции."""

    dry_run: bool
    total_source_rows: int
    selected_rows: int
    invalid_rows: int
    skipped_by_phone_filter: int
    processed_rows: int
    created_count: int
    attached_count: int
    updated_count: int
    conflict_count: int
    failed_count: int
    issues: tuple[LegacyMigrationIssue, ...]


def read_legacy_source_records(
    sqlite_path: Path,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[LegacyTelegramSourceRecord, ...]:
    """Читает записи из legacy SQLite-таблицы `user_phones`.

    Args:
        sqlite_path: Путь до SQLite-файла старого бота.
        limit: Ограничение количества читаемых строк (для пакетного запуска).
        offset: Смещение выборки (для пакетной обработки).
    """

    normalized_limit = None if limit is None else max(0, int(limit))
    normalized_offset = max(0, int(offset))

    query = "SELECT user_id, phone, created_at FROM user_phones ORDER BY user_id"
    params: list[int] = []
    if normalized_limit is not None:
        query += " LIMIT ? OFFSET ?"
        params.extend([normalized_limit, normalized_offset])

    with sqlite3.connect(str(sqlite_path)) as connection:
        cursor = connection.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

    return tuple(
        LegacyTelegramSourceRecord(
            telegram_user_id=str(row[0]),
            raw_phone=str(row[1]),
            created_at_raw=str(row[2]) if row[2] is not None else None,
        )
        for row in rows
    )


def prepare_legacy_source_records(
    source_records: Sequence[LegacyTelegramSourceRecord],
    *,
    phone_filter_e164: str | None = None,
) -> LegacyPreparationResult:
    """Нормализует source-данные и отбраковывает невалидные записи."""

    prepared: list[PreparedLegacyTelegramRecord] = []
    invalid_issues: list[LegacyMigrationIssue] = []
    skipped_by_phone_filter = 0

    for record in source_records:
        try:
            phone_e164 = normalize_phone(record.raw_phone)
        except ValueError as error:
            invalid_issues.append(
                LegacyMigrationIssue(
                    telegram_user_id=record.telegram_user_id,
                    raw_phone=record.raw_phone,
                    reason=f"Некорректный телефон: {error}",
                )
            )
            continue

        if phone_filter_e164 is not None and phone_e164 != phone_filter_e164:
            skipped_by_phone_filter += 1
            continue

        prepared.append(
            PreparedLegacyTelegramRecord(
                telegram_user_id=record.telegram_user_id,
                raw_phone=record.raw_phone,
                phone_e164=phone_e164,
                source_created_at=_parse_source_datetime(record.created_at_raw),
            )
        )

    return LegacyPreparationResult(
        prepared_records=tuple(prepared),
        invalid_issues=tuple(invalid_issues),
        skipped_by_phone_filter=skipped_by_phone_filter,
    )


def migrate_prepared_legacy_records(
    prepared_records: Sequence[PreparedLegacyTelegramRecord],
    *,
    uow_factory: Callable[[], IdentityUnitOfWork],
    dry_run: bool,
    progress_every: int = 500,
    verbose: bool = False,
    max_issue_samples: int = 50,
    log: Callable[[str], None] = print,
) -> LegacyMigrationReport:
    """Переносит подготовленные записи в strict identity.

    В `dry_run`-режиме в БД ничего не сохраняется, но выполняется полный анализ
    конфликтов и ожидаемых действий.
    """

    total = len(prepared_records)
    normalized_progress_every = max(1, int(progress_every))
    issue_samples: list[LegacyMigrationIssue] = []

    created_count = 0
    attached_count = 0
    updated_count = 0
    conflict_count = 0
    failed_count = 0
    processed_rows = 0

    if total == 0:
        return LegacyMigrationReport(
            dry_run=dry_run,
            total_source_rows=0,
            selected_rows=0,
            invalid_rows=0,
            skipped_by_phone_filter=0,
            processed_rows=0,
            created_count=0,
            attached_count=0,
            updated_count=0,
            conflict_count=0,
            failed_count=0,
            issues=(),
        )

    log(f"[legacy-migrate] Старт обработки: записей={total}, dry_run={dry_run}.")

    for index, record in enumerate(prepared_records, start=1):
        processed_rows += 1

        with uow_factory() as unit_of_work:
            repository = unit_of_work.identity_repository
            use_case = RegisterOrAttachAccountUseCase(repository)

            existing_by_phone = repository.get_person_by_phone(record.phone_e164)
            existing_by_account = repository.get_person_by_account("telegram", record.telegram_user_id)
            predicted_action = _predict_action(existing_by_phone, existing_by_account, record.phone_e164)

            if predicted_action == "conflict":
                conflict_count += 1
                _append_issue_sample(
                    issue_samples,
                    max_issue_samples=max_issue_samples,
                    issue=LegacyMigrationIssue(
                        telegram_user_id=record.telegram_user_id,
                        raw_phone=record.raw_phone,
                        reason=(
                            "Конфликт strict identity: телефон и telegram-аккаунт уже "
                            "привязаны к разным персонам."
                        ),
                    ),
                )
            else:
                if dry_run:
                    if predicted_action == "create":
                        created_count += 1
                    elif predicted_action == "attach":
                        attached_count += 1
                    else:
                        updated_count += 1
                else:
                    fixed_at = record.source_created_at or datetime.now(timezone.utc)
                    command = RegisterOrAttachAccountCommand(
                        platform="telegram",
                        external_id=record.telegram_user_id,
                        raw_phone=record.phone_e164,
                        rules_accepted=True,
                        rules_accepted_at=fixed_at,
                        is_legacy=True,
                        is_registered=False,
                        phone_verified_at=fixed_at,
                        phone_verification_method=LEGACY_PHONE_VERIFICATION_METHOD,
                    )
                    try:
                        use_case.execute(command)
                        unit_of_work.commit()
                        if predicted_action == "create":
                            created_count += 1
                        elif predicted_action == "attach":
                            attached_count += 1
                        else:
                            updated_count += 1
                    except IdentityConflictError as error:
                        unit_of_work.rollback()
                        conflict_count += 1
                        _append_issue_sample(
                            issue_samples,
                            max_issue_samples=max_issue_samples,
                            issue=LegacyMigrationIssue(
                                telegram_user_id=record.telegram_user_id,
                                raw_phone=record.raw_phone,
                                reason=f"Конфликт strict identity: {error}",
                            ),
                        )
                    except ValueError as error:
                        unit_of_work.rollback()
                        failed_count += 1
                        _append_issue_sample(
                            issue_samples,
                            max_issue_samples=max_issue_samples,
                            issue=LegacyMigrationIssue(
                                telegram_user_id=record.telegram_user_id,
                                raw_phone=record.raw_phone,
                                reason=f"Ошибка валидации при записи: {error}",
                            ),
                        )
                    except Exception as error:  # noqa: BLE001
                        unit_of_work.rollback()
                        failed_count += 1
                        _append_issue_sample(
                            issue_samples,
                            max_issue_samples=max_issue_samples,
                            issue=LegacyMigrationIssue(
                                telegram_user_id=record.telegram_user_id,
                                raw_phone=record.raw_phone,
                                reason=f"Непредвиденная ошибка записи: {error}",
                            ),
                        )

        should_log_progress = index == 1 or index == total or index % normalized_progress_every == 0
        if should_log_progress:
            percent = (index / total) * 100
            log(
                "[legacy-migrate] Прогресс: "
                f"{index}/{total} ({percent:.1f}%). "
                f"create={created_count}, attach={attached_count}, update={updated_count}, "
                f"conflict={conflict_count}, failed={failed_count}."
            )

        if verbose:
            log(
                "[legacy-migrate] row="
                f"{index}; telegram_id={record.telegram_user_id}; phone={record.phone_e164}; action={predicted_action}."
            )

    return LegacyMigrationReport(
        dry_run=dry_run,
        total_source_rows=total,
        selected_rows=total,
        invalid_rows=0,
        skipped_by_phone_filter=0,
        processed_rows=processed_rows,
        created_count=created_count,
        attached_count=attached_count,
        updated_count=updated_count,
        conflict_count=conflict_count,
        failed_count=failed_count,
        issues=tuple(issue_samples),
    )


def build_report_lines(report: LegacyMigrationReport) -> tuple[str, ...]:
    """Формирует человекочитаемую сводку по результатам миграции."""

    mode_label = "DRY-RUN" if report.dry_run else "APPLY"
    lines = [
        f"[legacy-migrate] Итог ({mode_label}):",
        f"[legacy-migrate]   source_rows={report.total_source_rows}",
        f"[legacy-migrate]   selected_rows={report.selected_rows}",
        f"[legacy-migrate]   invalid_rows={report.invalid_rows}",
        f"[legacy-migrate]   skipped_by_phone_filter={report.skipped_by_phone_filter}",
        f"[legacy-migrate]   processed_rows={report.processed_rows}",
        f"[legacy-migrate]   create={report.created_count}",
        f"[legacy-migrate]   attach={report.attached_count}",
        f"[legacy-migrate]   update={report.updated_count}",
        f"[legacy-migrate]   conflict={report.conflict_count}",
        f"[legacy-migrate]   failed={report.failed_count}",
    ]
    return tuple(lines)


def _parse_source_datetime(raw_value: str | None) -> datetime | None:
    """Преобразует datetime-строку SQLite в timezone-aware UTC datetime."""

    if raw_value is None:
        return None
    normalized = str(raw_value).strip()
    if not normalized:
        return None

    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                parsed = datetime.strptime(normalized, pattern)
                break
            except ValueError:
                continue

    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _predict_action(existing_by_phone: object | None, existing_by_account: object | None, phone_e164: str) -> str:
    """Определяет ожидаемое действие миграции для строки.

    Возможные значения:
    1. `create` — будет создан новый Person.
    2. `attach` — telegram-аккаунт будет добавлен к существующему Person по телефону.
    3. `update` — аккаунт уже привязан корректно, нужно только актуализировать профиль.
    4. `conflict` — найден конфликт strict identity.
    """

    if existing_by_phone is None and existing_by_account is None:
        return "create"

    if existing_by_phone is not None and existing_by_account is None:
        return "attach"

    if existing_by_account is not None and existing_by_phone is None:
        account_phone = str(getattr(existing_by_account, "phone_e164", "")).strip()
        return "update" if account_phone == phone_e164 else "conflict"

    phone_person_id = getattr(existing_by_phone, "person_id", None)
    account_person_id = getattr(existing_by_account, "person_id", None)
    if phone_person_id == account_person_id:
        return "update"
    return "conflict"


def _append_issue_sample(
    issues: list[LegacyMigrationIssue],
    *,
    max_issue_samples: int,
    issue: LegacyMigrationIssue,
) -> None:
    """Добавляет issue в выборку примеров, не превышая лимит."""

    if len(issues) < max_issue_samples:
        issues.append(issue)
