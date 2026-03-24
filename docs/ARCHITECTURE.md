# Архитектура vtelemax (черновик v0)

## 1. Общая идея

Архитектура строится вокруг разделения:

1. Доменное ядро (`core`) — единые бизнес-правила.
2. Транспортные адаптеры (`adapters`) — вход/выход для каждого мессенджера.
3. Инфраструктура (`infrastructure`) — БД, кэш, внешние сервисы.

Ключевой принцип: переносим максимум логики в `core`, чтобы не дублировать код в трех ботах.

## 2. Слои

### 2.1 Core

В `core` размещаются:

1. Доменная модель пользователей/регистрации/тикетов.
2. Use-case сценарии (`start`, регистрация, legacy, поддержка, модерация).
3. Единые валидаторы, форматтеры, бизнес-ограничения.

Уже реализовано в ядре на текущем этапе:

1. Доменные модели (`models.py`).
2. Доменные ошибки (`errors.py`).
3. Порты репозиториев (`ports.py`).
4. Use-case регистрации/привязки аккаунта (`use_cases.py`).
5. Единый контракт меню и текстов (`menu_contract.py`, `guest_content.py`).

### 2.2 Adapters

В `adapters` остаются только платформенные детали:

1. Маппинг событий платформы на команды ядра.
2. Маппинг ответов ядра в сообщения/кнопки конкретной платформы.
3. Технические особенности SDK (callback, attachment, state-контекст).

Уже реализовано на текущем этапе:

1. Первый Telegram-адаптер регистрации (`adapters/telegram/identity_adapter.py`).
2. Aiogram router для `/start` и обработки контакта (`adapters/telegram/router.py`).
3. Telegram-меню синхронизировано по эталонным текстам Telegram-прототипа.
4. Стартовый VK-адаптер меню на общем контракте (`adapters/vk/menu_adapter.py`).
5. VK identity-адаптер и `vkbottle` router (`adapters/vk/identity_adapter.py`, `adapters/vk/router.py`).
6. MAX menu/identity/router-адаптеры на том же контракте (`adapters/max/*`).
7. Контрактные тесты согласованности Telegram/VK/MAX (`tests/adapter_contract/*`).

### 2.3 Infrastructure

В `infrastructure` будут:

1. Реализация репозиториев (PostgreSQL).
2. Реализация хранилища состояний (Redis).
3. Реализация внешних клиентов (iiko и др.).

Уже реализовано на текущем этапе:

1. Базовая SQLAlchemy-схема strict identity (`infrastructure/postgres/schema.py`).
2. Стартовая SQL-миграция схемы (`migrations/sql/0001_strict_identity.sql`).
3. SQLAlchemy-репозиторий strict identity (`infrastructure/postgres/repository.py`).
4. Транзакционный Unit Of Work (`infrastructure/postgres/uow.py`).

### 2.4 Settings и приложения

1. Централизованные настройки через `AppSettings` (`settings.py`).
2. Первая точка входа приложения: `apps/telegram_app.py`.
3. Telegram-приложение использует два use-case: регистрация и чтение профиля по аккаунту.
4. Добавлена точка входа VK-приложения: `apps/vk_app.py`.
5. Добавлена точка входа MAX-приложения: `apps/max_app.py`.

## 3. Строгая идентификация (Strict Identity)

Правило проекта:

1. `phone -> person` является уникальным соответствием.
2. Один телефон не может соответствовать двум разным людям.
3. Конфликтные перепривязки аккаунтов должны поднимать доменную ошибку.

## 4. Целевая схема данных (эскиз)

Текущий контур strict identity включает:

1. `persons` — единый профиль человека.
2. `phones` — канонический телефон человека (`UNIQUE phone_e164`, `UNIQUE person_id`).
3. `platform_accounts` — привязка `platform + external_id -> person_id` с `UNIQUE(platform, external_id)`.

Будущее расширение:

1. `tickets`, `ticket_messages` — связь через `person_id`.

Это позволит:

1. Хранить одну анкету на человека.
2. Связывать одного человека с Telegram, VK и MAX одновременно.
