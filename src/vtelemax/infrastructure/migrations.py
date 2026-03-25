"""Инфраструктурные функции применения SQL-миграций.

Модуль нужен для повторяемого запуска миграций:

1. локально через Python-скрипт;
2. в Docker-контейнерах перед запуском ботов;
3. в тестах (проверка парсинга SQL-файлов).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import Engine


_TRANSACTION_MARKERS = {"BEGIN", "COMMIT"}


def list_migration_files(migrations_dir: Path) -> list[Path]:
    """Возвращает упорядоченный список SQL-миграций из каталога."""

    migration_files = sorted(path for path in migrations_dir.glob("*.sql") if path.is_file())
    if not migration_files:
        raise FileNotFoundError(f"Не найдены SQL-миграции в каталоге: {migrations_dir}")
    return migration_files


def read_sql_statements(migration_file: Path) -> list[str]:
    """Читает SQL-файл и возвращает список исполняемых SQL-команд.

    Технические детали:

    1. Строковые комментарии `-- ...` отбрасываются.
    2. Технические маркеры транзакций (`BEGIN`/`COMMIT`) удаляются.
    3. Оставшиеся команды режутся по `;`.
    """

    source = migration_file.read_text(encoding="utf-8")
    filtered_lines = []
    for line in source.splitlines():
        if line.strip().startswith("--"):
            continue
        filtered_lines.append(line)

    normalized_sql = "\n".join(filtered_lines)
    statements = []
    for chunk in normalized_sql.split(";"):
        statement = chunk.strip()
        if not statement:
            continue
        if statement.upper() in _TRANSACTION_MARKERS:
            continue
        statements.append(statement)

    if not statements:
        raise ValueError(f"В миграции нет исполняемых SQL-команд: {migration_file}")
    return statements


def apply_migrations(engine: Engine, migrations_dir: Path) -> int:
    """Применяет все SQL-миграции к переданному SQLAlchemy-engine.

    Возвращает количество успешно обработанных файлов.
    """

    migration_files = list_migration_files(migrations_dir)
    with engine.begin() as connection:
        for migration_file in migration_files:
            statements = read_sql_statements(migration_file)
            for statement in statements:
                connection.exec_driver_sql(statement)
    return len(migration_files)
