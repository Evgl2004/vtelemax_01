"""Инфраструктурный слой vtelemax.

В этом пакете размещаются реализации портов ядра:

1. Работа с PostgreSQL (репозитории, unit-of-work, модели БД).
2. Работа с Redis и другими внешними сервисами.
3. Технические детали, которые не должны попадать в `core`.
"""

from .migrations import apply_migrations, list_migration_files, read_sql_statements

__all__ = [
    "apply_migrations",
    "list_migration_files",
    "read_sql_statements",
]
