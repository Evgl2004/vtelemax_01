# Тестирование в vtelemax

## 1. Базовый запуск

После подготовки виртуального окружения:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_pytest.ps1
```

## 2. Запуск конкретного файла

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_pytest.ps1 tests/unit/test_identity.py
```

## 3. Почему есть fallback-режим

В части Windows-окружений встроенный запуск `.venv\Scripts\python.exe` может быть недоступен.

Скрипт `run_pytest.ps1` работает по схеме:

1. Сначала пытается запустить `.venv\Scripts\python.exe -m pytest`.
2. Если это невозможно — использует fallback интерпретатор pgAdmin Python.
3. В fallback-режиме подключает `site-packages` из `.venv`.

Этот подход повторяет проверенный путь из соседнего проекта.

## 4. Текущее покрытие на старте

На этапе инициализации есть unit-тесты для:

1. Нормализации телефона.
2. Строгой модели идентификации аккаунтов по телефону.
3. Ограничений SQLAlchemy-схемы strict identity (`persons`, `phones`, `platform_accounts`).

## 5. Интеграционные тесты репозитория

Добавлены integration-тесты для:

1. `SQLAlchemyIdentityRepository`.
2. `SQLAlchemyIdentityUnitOfWork`.
3. Транзакционного use-case регистрации/привязки.

Текущий формат integration-тестов:

1. Выполняются на SQLite in-memory через SQLAlchemy metadata.
2. Проверяют контракты репозитория и транзакционное поведение (`commit`/`rollback`).
