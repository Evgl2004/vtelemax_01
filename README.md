# vtelemax

Единый монорепозиторий для трех ботов (Telegram, VK, MAX) с общим ядром бизнес-логики и строгой моделью идентификации пользователей по телефону.

## 1. Цель проекта

Проект создается как единая платформа:

1. `core` — доменное ядро и бизнес-правила, не зависящие от мессенджера.
2. `adapters` — транспортные адаптеры для Telegram/VK/MAX.
3. `infrastructure` — общая работа с PostgreSQL, Redis, внешними API.
4. Общая пользовательская база: один телефон = один человек (strict identity).

## 2. Текущий статус

На текущем этапе создан базовый каркас монорепозитория:

1. Пакет `vtelemax` в `src/`.
2. Базовое доменное ядро строгой идентификации.
3. Тесты на `pytest` для нормализации телефона и strict identity.
4. Скрипты Windows для настройки `.venv` и запуска тестов.

## 3. Быстрый старт (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_venv.ps1
powershell -ExecutionPolicy Bypass -File scripts/run_pytest.ps1
```

При необходимости запуска конкретных тестов:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_pytest.ps1 tests/unit/test_identity.py
```

## 4. Структура

```text
vtelemax/
  docs/
  scripts/
  src/
    vtelemax/
      adapters/
      core/
  tests/
    unit/
```

## 5. Ветки

Стратегия работы:

1. `main` — базовая инициализация и стабильные контрольные точки.
2. `codex/develop-cai` — активная разработка.

## 6. Важное правило идентификации

В этом проекте принята строгая модель:

1. Телефон приводится к каноническому формату.
2. Один канонический телефон может быть связан только с одним `Person`.
3. Конфликтные привязки между аккаунтами ботов и телефонами запрещаются и поднимают ошибку домена.

## 7. Документы проекта

1. Архитектура: `docs/ARCHITECTURE.md`.
2. Процесс и правила разработки: `docs/DEVELOPMENT_WORKFLOW.md`.
3. Зафиксированный пошаговый план: `docs/DEVELOPMENT_PLAN.md`.
4. Тестирование: `docs/TESTING.md`.
