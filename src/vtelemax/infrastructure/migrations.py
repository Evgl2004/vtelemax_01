"""Инфраструктурные функции применения SQL-миграций.

Модуль нужен для повторяемого запуска миграций:

1. локально через Python-скрипт;
2. в Docker-контейнерах перед запуском ботов;
3. в тестах (проверка парсинга SQL-файлов).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy.engine import Engine


_TRANSACTION_MARKERS = {"BEGIN", "COMMIT"}
_MIGRATION_HISTORY_TABLE = "sql_migration_history"


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


def _ensure_migration_history_table(connection) -> None:
    """Гарантирует существование таблицы учёта применённых SQL-миграций."""

    connection.exec_driver_sql(
        f"""
        CREATE TABLE IF NOT EXISTS {_MIGRATION_HISTORY_TABLE} (
            migration_name VARCHAR(255) PRIMARY KEY,
            checksum_sha256 VARCHAR(64) NOT NULL,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _get_applied_migrations(connection) -> dict[str, str]:
    """Возвращает словарь уже применённых миграций: имя -> checksum."""

    rows = connection.exec_driver_sql(
        f"SELECT migration_name, checksum_sha256 FROM {_MIGRATION_HISTORY_TABLE}"
    ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _compute_migration_checksum(migration_file: Path) -> str:
    """Считает SHA256 checksum содержимого SQL-файла."""

    content = migration_file.read_bytes()
    return hashlib.sha256(content).hexdigest()


def apply_migrations(engine: Engine, migrations_dir: Path) -> int:
    """Применяет все SQL-миграции к переданному SQLAlchemy-engine.

    Выполняет только новые миграции (по имени файла), хранит checksum и защищает
    от “тихого” изменения уже применённых миграций.

    Возвращает количество миграций, применённых в текущем запуске.
    """

    migration_files = list_migration_files(migrations_dir)
    applied_now = 0
    with engine.begin() as connection:
        _ensure_migration_history_table(connection)
        applied_history = _get_applied_migrations(connection)

        for migration_file in migration_files:
            migration_name = migration_file.name
            checksum = _compute_migration_checksum(migration_file)
            applied_checksum = applied_history.get(migration_name)

            if applied_checksum is not None:
                if applied_checksum != checksum:
                    raise ValueError(
                        "Обнаружено изменение уже применённой миграции: "
                        f"{migration_name}. Ожидаемый checksum={applied_checksum}, "
                        f"текущий checksum={checksum}."
                    )
                continue

            statements = read_sql_statements(migration_file)
            for statement in statements:
                connection.exec_driver_sql(statement)

            connection.exec_driver_sql(
                f"""
                INSERT INTO {_MIGRATION_HISTORY_TABLE} (migration_name, checksum_sha256)
                VALUES (:migration_name, :checksum_sha256)
                """,
                {
                    "migration_name": migration_name,
                    "checksum_sha256": checksum,
                },
            )
            applied_now += 1

    return applied_now
