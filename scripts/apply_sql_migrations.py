"""CLI-скрипт применения SQL-миграций vtelemax.

Сценарий запуска:

1. Читает настройки PostgreSQL из `.env`/окружения.
2. Подключается к БД через SQLAlchemy.
3. Применяет все SQL-файлы из `migrations/sql` в лексикографическом порядке.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from vtelemax.infrastructure import apply_migrations
from vtelemax.infrastructure.postgres import build_engine
from vtelemax.settings import AppSettings


def main() -> int:
    """Точка входа скрипта миграций.

    Возвращает:
        0: если миграции применены успешно.
        1: если возникла ошибка.
    """

    project_root = Path(__file__).resolve().parents[1]
    migrations_dir = project_root / "migrations" / "sql"

    settings = AppSettings()
    engine = build_engine(settings.postgres_sqlalchemy_dsn, echo=settings.postgres_echo)

    try:
        applied_count = apply_migrations(engine=engine, migrations_dir=migrations_dir)
    except (FileNotFoundError, ValueError, SQLAlchemyError) as exc:
        print(f"[migrations] Ошибка применения миграций: {exc}", file=sys.stderr)
        return 1

    print(
        "[migrations] SQL-миграции успешно применены. "
        f"Каталог: {migrations_dir}. Количество файлов: {applied_count}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
