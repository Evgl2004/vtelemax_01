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
3. Базовая SQLAlchemy-схема strict identity для PostgreSQL.
4. SQL-миграция `migrations/sql/0001_strict_identity.sql`.
5. SQLAlchemy-репозиторий и Unit Of Work для strict identity.
6. Тесты на `pytest` для ядра, ограничений схемы и integration-сценариев репозитория.
7. Единый контракт гостевого меню/текстов в `core` (эталон: Telegram-прототип).
8. Стартовый VK-адаптер меню на общем контракте.
9. Скрипты Windows для настройки `.venv` и запуска тестов.

## 3. Быстрый старт (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_venv.ps1
powershell -ExecutionPolicy Bypass -File scripts/run_pytest.ps1
```

При необходимости запуска конкретных тестов:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_pytest.ps1 tests/unit/test_identity.py
```

Живые тесты на PostgreSQL запускаются отдельно (после включения флага в `.env`):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_pytest.ps1 tests/integration/test_postgres_live_identity_repository.py
```

Запуск первого адаптера Telegram (локально, без Docker):

```powershell
.\.venv\Scripts\python.exe -m vtelemax.apps.telegram_app
```

Запуск VK-адаптера (локально, без Docker):

```powershell
.\.venv\Scripts\python.exe -m vtelemax.apps.vk_app
```

Текущие команды/кнопки Telegram-бота:

1. `/start` — приветствие и запрос контакта для регистрации.
2. `/menu` или `Главное меню` — показать разделы.
3. `💰 Мой баланс`, `🪪 Виртуальная карта`, `🆘 Отдел заботы`, `💼 Вакансии` — разделы эталонного меню.
4. `Мой профиль` — показать телефон и число привязанных аккаунтов.
5. `Помощь` — подсказки по регистрации и работе с ботом.
6. `О проекте` — краткая информация о платформе.
7. Те же пункты синхронизированы в стартовом VK-адаптере через `vkbottle` payload-кнопки.

## 4. Структура

```text
vtelemax/
  docs/
  migrations/
  scripts/
  src/
    vtelemax/
      adapters/
      core/
      infrastructure/
      apps/
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
4. Дубли телефонов запрещены и на уровне БД (`UNIQUE(phone_e164)`).

## 7. Окружения

1. Локальная разработка выполняется без Docker (виртуальное окружение + локальные сервисы).
2. Итоговое развёртывание проекта выполняется через Docker Compose.

## 8. Документы проекта

1. Архитектура: `docs/ARCHITECTURE.md`.
2. Процесс и правила разработки: `docs/DEVELOPMENT_WORKFLOW.md`.
3. Зафиксированный пошаговый план: `docs/DEVELOPMENT_PLAN.md`.
4. Схема БД strict identity: `docs/DB_SCHEMA.md`.
5. Тестирование: `docs/TESTING.md`.
