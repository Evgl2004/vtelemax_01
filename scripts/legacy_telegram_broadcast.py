"""CLI-утилита рассылки приветственных сообщений migrated legacy-пользователям Telegram.

Сценарий рассылки:

1. Читает `user_id` и `phone` из SQLite-таблицы `user_phones` старого проекта.
2. Фильтрует и выбирает уникальные Telegram chat_id.
3. Для каждого пользователя:
   - Отправляет ReplyKeyboardRemove() для очистки кэша старых reply-кнопок.
   - Отправляет приветственное сообщение о переходе на новый бот.
4. Поддерживает dry-run, точечную рассылку по номеру, задержку между отправками.

Важно:
1. Рассылку следует запускать после миграции данных (скрипт migrate_legacy_telegram_users.py).
2. Токен бота берётся из TELEGRAM_BOT_TOKEN (тестовый или рабочий).
3. Соблюдаются лимиты Telegram (задержка по умолчанию 0.5 сек).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
import sqlite3

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from vtelemax.core import normalize_phone
from vtelemax.settings import AppSettings
from vtelemax.tools.legacy_telegram_broadcast import (
    LegacyBroadcastTarget,
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
            "Отправляет приветственные сообщения migrated legacy-пользователям Telegram "
            "с очисткой кэша reply-кнопок."
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
            "Точечная рассылка одному номеру (например, +79129923438). "
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
        "--delay",
        type=float,
        default=0.5,
        help="Задержка между отправками в секундах (по умолчанию 0.5).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только предпросмотр получателей без отправки.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Подтвердить фактическую отправку сообщений.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Печатать подробный лог по каждой отправке.",
    )
    parser.add_argument(
        "--max-issues",
        type=int,
        default=20,
        help="Максимум примеров проблемных строк в итоговом отчете.",
    )
    return parser


def _validate_mode(*, dry_run: bool, yes: bool) -> tuple[bool, str | None]:
    """Проверяет согласованность флагов режима запуска."""

    if dry_run and yes:
        return False, "Нельзя одновременно указывать --dry-run и --yes."
    if not dry_run and not yes:
        return (
            False,
            "Укажите --dry-run для проверки или --yes для фактической отправки.",
        )
    return True, None


def _print_header(
    *,
    source_db_path: Path,
    dry_run: bool,
    phone_filter_e164: str | None,
    limit: int | None,
    offset: int,
    delay: float,
) -> None:
    """Печатает стартовую информацию перед рассылкой."""

    print("[legacy-broadcast] Запуск рассылки legacy Telegram-пользователям.")
    print(f"[legacy-broadcast] Source DB: {source_db_path}")
    print(f"[legacy-broadcast] Режим: {'dry-run' if dry_run else 'apply'}")
    if phone_filter_e164 is not None:
        print(f"[legacy-broadcast] Фильтр по номеру: {phone_filter_e164}")
    else:
        print("[legacy-broadcast] Фильтр по номеру: не задан")
    print(f"[legacy-broadcast] LIMIT={limit}, OFFSET={offset}")
    print(f"[legacy-broadcast] Задержка между отправками: {delay} сек")


def _print_selection_result(result, total_source_rows: int) -> None:
    """Печатает результат отбора получателей."""

    print(f"[legacy-broadcast] Всего source-строк: {total_source_rows}")
    print(f"[legacy-broadcast] Уникальных получателей: {len(result.targets)}")
    if result.invalid_telegram_id_rows:
        print(f"[legacy-broadcast] Невалидных telegram_id: {result.invalid_telegram_id_rows}")
    if result.invalid_phone_rows:
        print(f"[legacy-broadcast] Невалидных телефонов: {result.invalid_phone_rows}")
    if result.skipped_by_phone_filter:
        print(f"[legacy-broadcast] Пропущено по фильтру номера: {result.skipped_by_phone_filter}")
    if result.duplicate_telegram_id_rows:
        print(f"[legacy-broadcast] Дубликатов telegram_id: {result.duplicate_telegram_id_rows}")


def _print_send_result(result: LegacyBroadcastSendResult) -> None:
    """Печатает итог отправки рассылки."""

    print("[legacy-broadcast] Рассылка завершена. Итог:")
    print(f"  Всего получателей: {result.total_targets}")
    print(f"  Успешных очисток кэша: {result.sent_cleanup}")
    print(f"  Успешных сообщений: {result.sent_messages}")
    if result.failed_cleanup:
        print(f"  Неудачных очисток: {result.failed_cleanup}")
    if result.failed_messages:
        print(f"  Неудачных сообщений: {result.failed_messages}")
    if result.retry_after_errors:
        print(f"  Ошибок лимита (TelegramRetryAfter): {result.retry_after_errors}")
    if result.forbidden_errors:
        print(f"  Заблокированных ботов: {result.forbidden_errors}")
    if result.chat_not_found_errors:
        print(f"  Чатов не найдено: {result.chat_not_found_errors}")
    if result.other_errors:
        print(f"  Прочих ошибок: {result.other_errors}")


async def _run_broadcast(
    *,
    source_db_path: Path,
    phone_filter_e164: str | None,
    limit: int | None,
    offset: int,
    delay: float,
    dry_run: bool,
    verbose: bool,
    max_issue_samples: int,
) -> int:
    """Асинхронно выполняет чтение source, отбор получателей и рассылку."""

    # 1. Чтение source-записей
    try:
        source_records = read_legacy_source_records(
            source_db_path,
            limit=limit,
            offset=offset,
        )
    except sqlite3.Error as error:
        print(f"[legacy-broadcast] Ошибка чтения source SQLite: {error}", file=sys.stderr)
        return 1

    print(f"[legacy-broadcast] Прочитано строк из source: {len(source_records)}")

    # 2. Отбор получателей
    selection_result = select_legacy_broadcast_targets(
        source_records,
        phone_filter_e164=phone_filter_e164,
    )
    _print_selection_result(selection_result, total_source_rows=len(source_records))

    if not selection_result.targets:
        print("[legacy-broadcast] Нет получателей для рассылки. Завершено.")
        return 0

    # 3. Если dry-run — только предпросмотр
    if dry_run:
        print("[legacy-broadcast] DRY-RUN: отправка не производится.")
        print("[legacy-broadcast] Пример текста сообщения:")
        print("-" * 60)
        print(build_default_legacy_broadcast_message())
        print("-" * 60)
        return 0

    # 4. Инициализация бота
    settings = AppSettings()
    settings.validate_telegram_ready()
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # 5. Запуск рассылки
    print(f"[legacy-broadcast] Начинаем рассылку для {len(selection_result.targets)} пользователей...")
    try:
        send_result = await send_legacy_broadcast(
            bot=bot,
            targets=selection_result.targets,
            delay_seconds=delay,
            cleanup_before_message=True,
        )
    finally:
        await bot.session.close()

    _print_send_result(send_result)

    if send_result.sent_messages == 0 and send_result.total_targets > 0:
        print("[legacy-broadcast] Внимание: ни одно сообщение не было отправлено.", file=sys.stderr)
        return 1

    return 0


def main() -> int:
    """Точка входа CLI-утилиты."""

    parser = _build_parser()
    args = parser.parse_args()

    is_mode_ok, mode_error = _validate_mode(dry_run=args.dry_run, yes=args.yes)
    if not is_mode_ok:
        print(f"[legacy-broadcast] Ошибка режима запуска: {mode_error}", file=sys.stderr)
        return 2

    dry_run = bool(args.dry_run)
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
            print(
                f"[legacy-broadcast] Некорректный номер в --phone: {error}",
                file=sys.stderr,
            )
            return 2

    _print_header(
        source_db_path=source_db_path,
        dry_run=dry_run,
        phone_filter_e164=phone_filter_e164,
        limit=args.limit,
        offset=args.offset,
        delay=args.delay,
    )

    return asyncio.run(
        _run_broadcast(
            source_db_path=source_db_path,
            phone_filter_e164=phone_filter_e164,
            limit=args.limit,
            offset=args.offset,
            delay=args.delay,
            dry_run=dry_run,
            verbose=args.verbose,
            max_issue_samples=max(1, int(args.max_issues)),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())