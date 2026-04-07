"""CLI-утилита точечной очистки тестового пользователя.

Сценарий:

1. Находит пользователя по телефону в формате E.164.
2. Удаляет `persons`-запись (с каскадом зависимостей) или показывает dry-run.
3. Опционально очищает Redis-ключи, связанные с пользователем.

Важно:
1. Текущее FSM-состояние адаптеров хранится в памяти процессов ботов.
2. После очистки БД для чистого сценария регистрации лучше перезапустить контейнеры ботов.
"""

from __future__ import annotations

import argparse
import os
import sys

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from vtelemax.core import normalize_phone
from vtelemax.infrastructure.postgres import build_engine
from vtelemax.settings import AppSettings
from vtelemax.tools.user_reset import (
    build_default_redis_patterns,
    collect_matching_redis_keys,
    delete_person_by_id,
    delete_redis_keys,
    get_person_snapshot_by_phone,
)


class _RedisSettings(BaseSettings):
    """Локальная модель Redis-настроек для CLI-утилиты."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    redis_password: str = Field(default="", alias="REDIS_PASSWORD")


def _build_parser() -> argparse.ArgumentParser:
    """Создает parser аргументов командной строки."""

    parser = argparse.ArgumentParser(
        description=(
            "Удаляет тестового пользователя из PostgreSQL по номеру телефона "
            "и при необходимости очищает связанные Redis-ключи."
        )
    )
    parser.add_argument(
        "--phone",
        required=True,
        help="Телефон пользователя (например, +79991234567).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показывает план удаления без фактических изменений.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Подтверждает фактическое удаление из PostgreSQL/Redis.",
    )
    parser.add_argument(
        "--clean-redis",
        action="store_true",
        help="Дополнительно очищает Redis-ключи пользователя.",
    )
    parser.add_argument(
        "--redis-pattern",
        action="append",
        default=[],
        help=(
            "Явный Redis-шаблон для удаления (можно повторять). "
            "Если не задано, используются автоматически сгенерированные шаблоны."
        ),
    )
    parser.add_argument(
        "--redis-scan-count",
        type=int,
        default=1000,
        help="Размер batch для SCAN в Redis (по умолчанию 1000).",
    )
    return parser


def _build_redis_client_from_env() -> Redis:
    """Создает Redis-клиент на основе переменных окружения."""

    redis_settings = _RedisSettings()
    # Явные env-переменные процесса имеют приоритет над .env и defaults.
    host = os.getenv("REDIS_HOST", redis_settings.redis_host)
    port = int(os.getenv("REDIS_PORT", str(redis_settings.redis_port)))
    db = int(os.getenv("REDIS_DB", str(redis_settings.redis_db)))
    password = os.getenv("REDIS_PASSWORD", redis_settings.redis_password).strip() or None
    return Redis(host=host, port=port, db=db, password=password)


def main() -> int:
    """Точка входа CLI-утилиты."""

    parser = _build_parser()
    args = parser.parse_args()

    try:
        phone_e164 = normalize_phone(args.phone)
    except ValueError as error:
        print(f"[reset-user] Некорректный номер телефона: {error}", file=sys.stderr)
        return 2

    if not args.dry_run and not args.yes:
        print(
            "[reset-user] Для фактического удаления добавьте --yes "
            "или используйте --dry-run для предварительной проверки.",
            file=sys.stderr,
        )
        return 2

    settings = AppSettings()
    engine = build_engine(settings.postgres_sqlalchemy_dsn, echo=settings.postgres_echo)

    snapshot = None
    deleted_person_rows = 0

    with Session(engine) as session:
        snapshot = get_person_snapshot_by_phone(session, phone_e164)
        if snapshot is None:
            print(f"[reset-user] Пользователь с телефоном {phone_e164} не найден в PostgreSQL.")
        else:
            print(f"[reset-user] Найден пользователь: person_id={snapshot.person_id}")
            print(f"[reset-user] Привязанных аккаунтов: {len(snapshot.accounts)}")
            print(
                "[reset-user] Profile: "
                f"is_legacy={snapshot.is_legacy}, "
                f"is_moderator={snapshot.is_moderator}, "
                f"is_registered={snapshot.is_registered}, "
                f"first_name_input={snapshot.first_name_input!r}, "
                f"phone_verification_method={snapshot.phone_verification_method!r}"
            )
            for account in snapshot.accounts:
                print(
                    f"[reset-user]   - platform={account.platform}, external_id={account.external_id}"
                )
            print(
                f"[reset-user] Платформенных состояний регистрации: {len(snapshot.platform_states)}"
            )
            for state in snapshot.platform_states:
                print(
                    "[reset-user]   - "
                    f"platform={state.platform}, "
                    f"rules_accepted={state.rules_accepted}, "
                    f"rules_accepted_at={state.rules_accepted_at}, "
                    f"notifications_allowed={state.notifications_allowed}, "
                    f"notifications_allowed_at={state.notifications_allowed_at}, "
                    f"is_registered={state.is_registered}, "
                    f"registered_at={state.registered_at}"
                )
            print(
                "[reset-user] Support-данные: "
                f"tickets={snapshot.tickets_count}, messages={snapshot.messages_count}"
            )

            if args.dry_run:
                print("[reset-user] dry-run: удаление из PostgreSQL не выполнено.")
            else:
                deleted_person_rows = delete_person_by_id(session, snapshot.person_id)
                session.commit()
                print(
                    f"[reset-user] Удаление из PostgreSQL завершено. deleted_person_rows={deleted_person_rows}."
                )

    if not args.clean_redis:
        print(
            "[reset-user] Очистка Redis пропущена (флаг --clean-redis не передан)."
        )
        print(
            "[reset-user] Напоминание: FSM-состояния сейчас in-memory, "
            "для полного сброса сценария перезапустите контейнеры ботов."
        )
        return 0

    redis_patterns = list(args.redis_pattern)
    if not redis_patterns:
        redis_patterns = build_default_redis_patterns(
            phone_e164=phone_e164,
            accounts=tuple() if snapshot is None else snapshot.accounts,
            person_id=None if snapshot is None else snapshot.person_id,
        )

    print(f"[reset-user] Redis-шаблоны для поиска: {len(redis_patterns)}")
    for pattern in redis_patterns:
        print(f"[reset-user]   - {pattern}")

    try:
        redis_client = _build_redis_client_from_env()
        redis_client.ping()
    except (RedisError, OSError, ValueError) as error:
        print(f"[reset-user] Не удалось подключиться к Redis: {error}", file=sys.stderr)
        return 1

    try:
        matched_keys = collect_matching_redis_keys(
            redis_client,
            redis_patterns,
            scan_count=max(1, int(args.redis_scan_count)),
        )
    except RedisError as error:
        print(f"[reset-user] Ошибка поиска Redis-ключей: {error}", file=sys.stderr)
        return 1

    print(f"[reset-user] Найдено Redis-ключей: {len(matched_keys)}")
    for key in matched_keys[:50]:
        print(f"[reset-user]   - {key}")
    if len(matched_keys) > 50:
        print(f"[reset-user]   ... и еще {len(matched_keys) - 50} ключей")

    if args.dry_run:
        print("[reset-user] dry-run: удаление Redis-ключей не выполнено.")
    else:
        try:
            deleted_redis = delete_redis_keys(redis_client, matched_keys)
        except RedisError as error:
            print(f"[reset-user] Ошибка удаления Redis-ключей: {error}", file=sys.stderr)
            return 1
        print(f"[reset-user] Redis-очистка завершена. deleted_keys={deleted_redis}.")

    print(
        "[reset-user] Готово. Для полного сброса FSM in-memory перезапустите контейнеры ботов."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
