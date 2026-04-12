"""CLI-утилита рассылки сообщений migrated legacy-пользователям Telegram.

Сценарий:

1. Читает `user_id` и `phone` из SQLite-таблицы `user_phones` старого проекта.
2. Выбирает уникальные Telegram chat_id (с опциональным фильтром по телефону).
3. Отправляет приветственное сообщение с очисткой старых reply-кнопок.
4. Поддерживает dry-run, точечный запуск и пакетную отправку через limit/offset.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import sys
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from vtelemax.core import normalize_phone
from vtelemax.settings import AppSettings
from vtelemax.tools.legacy_telegram_broadcast import (
    LegacyBroadcastSendResult,
    build_default_legacy_broadcast_message,
    select_legacy_broadcast_targets,
    send_legacy_broadcast,
)
from vtelemax.tools.legacy_telegram_migration import (
    DEFAULT_SOURCE_SQLITE_PATH,
    read_legacy_source_records,
)


def _build_parser() -> argparse.ArgumentParser:
    """Создает parser аргументов командной строки."""

    default_source = os.getenv("LEGACY_SOURCE_SQLITE_PATH", str(DEFAULT_SOURCE_SQLITE_PATH))
    parser = argparse.ArgumentParser(
        description=(
            "Отправляет уведомление migrated legacy-пользователям Telegram "
            "с очисткой старых reply-кнопок."
        )
    )
    parser.add_argument(
        "--source-db",
        default=default_source,
        help=f"Путь к SQLite-файлу старого бота. По умолчанию: {default_source}",
    )
    parser.add_argument(
        "--phone",
        default=None,
        help="Точечная отправка одному номеру (например, +79129923438).",
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
        "--delay",
        type=float,
        default=0.5,
        help="Задержка между отправками в секундах (по умолчанию 0.5).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только предпросмотр получателей и текста без отправки.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Подтвердить фактическую отправку.",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Не отправлять отдельный cleanup-шаг перед приветственным сообщением.",
    )
    return parser


def _validate_mode(*, dry_run: bool, yes: bool) -> tuple[bool, str | None]:
    """Проверяет согласованность флагов режима запуска."""

    if dry_run and yes:
        return False, "Нельзя одновременно указывать --dry-run и --yes."
    if not dry_run and not yes:
        return False, "Укажите --dry-run для проверки или --yes для фактической отправки."
    return True, None


def _print_header(
    *,
    source_db_path: Path,
    dry_run: bool,
    phone_filter_e164: str | None,
    limit: int | None,
    offset: int,
    delay: float,
    cleanup_before_message: bool,
) -> None:
    """Печатает стартовую информацию перед рассылкой."""

    print("[legacy-broadcast] Запуск рассылки legacy Telegram-пользователям.")
    print(f"[legacy-broadcast] Source DB: {source_db_path}")
    print(f"[legacy-broadcast] Режим: {'dry-run' if dry_run else 'apply'}")
    print(
        "[legacy-broadcast] Фильтр по номеру: "
        f"{phone_filter_e164 if phone_filter_e164 is not None else 'не задан'}"
    )
    print(f"[legacy-broadcast] LIMIT={limit}, OFFSET={offset}")
    print(f"[legacy-broadcast] Задержка между отправками: {delay} сек")
    print(
        "[legacy-broadcast] Очистка старых кнопок: "
        f"{'включена' if cleanup_before_message else 'выключена (--no-cleanup)'}"
    )


def _print_selection_result(*, total_source_rows: int, selection_result: object) -> None:
    """Печатает результат отбора получателей."""

    print(f"[legacy-broadcast] Прочитано строк из source: {total_source_rows}")
    print(f"[legacy-broadcast] Уникальных получателей: {len(selection_result.targets)}")
    print(f"[legacy-broadcast] Невалидных telegram_id: {selection_result.invalid_telegram_id_rows}")
    print(f"[legacy-broadcast] Невалидных телефонов: {selection_result.invalid_phone_rows}")
    print(f"[legacy-broadcast] Пропущено по фильтру номера: {selection_result.skipped_by_phone_filter}")
    print(f"[legacy-broadcast] Дубликатов telegram_id: {selection_result.duplicate_telegram_id_rows}")


def _print_send_result(result: LegacyBroadcastSendResult) -> None:
    """Печатает итог отправки рассылки."""

    print("[legacy-broadcast] Рассылка завершена. Итог:")
    print(f"[legacy-broadcast]   total_targets={result.total_targets}")
    print(f"[legacy-broadcast]   sent_cleanup={result.sent_cleanup}")
    print(f"[legacy-broadcast]   sent_messages={result.sent_messages}")
    print(f"[legacy-broadcast]   failed_cleanup={result.failed_cleanup}")
    print(f"[legacy-broadcast]   failed_messages={result.failed_messages}")
    print(f"[legacy-broadcast]   retry_after_errors={result.retry_after_errors}")
    print(f"[legacy-broadcast]   forbidden_errors={result.forbidden_errors}")
    print(f"[legacy-broadcast]   chat_not_found_errors={result.chat_not_found_errors}")
    print(f"[legacy-broadcast]   other_errors={result.other_errors}")


async def _run(args: argparse.Namespace) -> int:
    """Выполняет основной сценарий рассылки."""

    source_db_path = Path(args.source_db).expanduser()
    if not source_db_path.exists():
        print(
            f"[legacy-broadcast] Source SQLite-файл не найден: {source_db_path}",
            file=sys.stderr,
        )
        return 2

    phone_filter_e164: str | None = None
    if args.phone:
        try:
            phone_filter_e164 = normalize_phone(args.phone)
        except ValueError as error:
            print(f"[legacy-broadcast] Некорректный номер в --phone: {error}", file=sys.stderr)
            return 2

    cleanup_before_message = not bool(args.no_cleanup)
    _print_header(
        source_db_path=source_db_path,
        dry_run=bool(args.dry_run),
        phone_filter_e164=phone_filter_e164,
        limit=args.limit,
        offset=args.offset,
        delay=float(args.delay),
        cleanup_before_message=cleanup_before_message,
    )

    try:
        source_records = read_legacy_source_records(
            source_db_path,
            limit=args.limit,
            offset=args.offset,
        )
    except sqlite3.Error as error:
        print(f"[legacy-broadcast] Ошибка чтения source SQLite: {error}", file=sys.stderr)
        return 1

    selection_result = select_legacy_broadcast_targets(
        source_records,
        phone_filter_e164=phone_filter_e164,
    )
    _print_selection_result(
        total_source_rows=len(source_records),
        selection_result=selection_result,
    )

    if not selection_result.targets:
        print("[legacy-broadcast] Нет получателей для рассылки. Завершено.")
        return 0

    if args.dry_run:
        print("[legacy-broadcast] DRY-RUN: отправка не выполнялась.")
        print("[legacy-broadcast] Текст сообщения:")
        print("-" * 60)
        print(build_default_legacy_broadcast_message())
        print("-" * 60)
        return 0

    settings = AppSettings()
    settings.validate_telegram_ready()
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        result = await send_legacy_broadcast(
            bot=bot,
            targets=selection_result.targets,
            delay_seconds=float(args.delay),
            cleanup_before_message=cleanup_before_message,
        )
    finally:
        await bot.session.close()

    _print_send_result(result)

    if result.sent_messages == 0 and result.total_targets > 0:
        print(
            "[legacy-broadcast] Внимание: не удалось отправить ни одного сообщения.",
            file=sys.stderr,
        )
        return 1

    return 0


def main() -> int:
    """Точка входа CLI-утилиты."""

    parser = _build_parser()
    args = parser.parse_args()

    mode_ok, mode_error = _validate_mode(dry_run=bool(args.dry_run), yes=bool(args.yes))
    if not mode_ok:
        print(f"[legacy-broadcast] Ошибка режима запуска: {mode_error}", file=sys.stderr)
        return 2

    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

