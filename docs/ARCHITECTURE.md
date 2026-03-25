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
6. Единый onboarding-flow регистрации/legacy (`onboarding.py`).
7. Доменные модели и порты поддержки/модерации (`support_models.py`, `support_ports.py`).
8. Use-case создания тикета, маршрутизации ответа модератора и чтения карточки тикета (`support_use_cases.py`).
9. Порт лояльности и use-case разделов `Мой баланс` / `Виртуальная карта` (`loyalty_ports.py`, `loyalty_use_cases.py`).

### 2.2 Adapters

В `adapters` остаются только платформенные детали:

1. Маппинг событий платформы на команды ядра.
2. Маппинг ответов ядра в сообщения/кнопки конкретной платформы.
3. Технические особенности SDK (callback, attachment, state-контекст).

Уже реализовано на текущем этапе:

1. Первый Telegram-адаптер регистрации (`adapters/telegram/identity_adapter.py`).
2. Aiogram router для `/start` и обработки контакта (`adapters/telegram/router.py`).
3. Telegram-меню синхронизировано по эталонным текстам Telegram-прототипа.
4. Telegram подключен к общему onboarding-flow (правила -> телефон) и legacy-ветке (`/legacy`).
5. VK подключен к общему onboarding-flow и legacy-ветке (`adapters/vk/identity_adapter.py`).
6. MAX подключен к общему onboarding-flow и legacy-ветке (`adapters/max/identity_adapter.py`).
7. VK/MAX router-слой поддерживает явный запуск legacy-сценария по команде.
8. Контрактные тесты согласованности Telegram/VK/MAX (`tests/adapter_contract/*`).
9. Сценарий создания тикета поддержки подключен в Telegram/VK/MAX через единый core use-case.
10. Команды модератора `/modreply` и `/modticket` реализованы в Telegram/VK/MAX.
11. В Telegram/VK/MAX восстановлен сценарий `/mod` с FSM-меню модератора (список тикетов, ответ, карточка).
12. Реализован MVP-контур доставки pending-сообщений модератора в целевые каналы (одна попытка, статусы `sent/failed`).
13. Разделы меню `Мой баланс` и `Виртуальная карта` подключены к единым core use-case во всех трех адаптерах.

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
5. SQLAlchemy-схема и SQL-миграция support-таблиц (`support_tickets`, `support_messages`, `migrations/sql/0002_support_tickets.sql`).
6. SQLAlchemy-репозиторий поддержки (`infrastructure/postgres/support_repository.py`).
7. Централизованная конфигурация логирования (`infrastructure/logging_config.py`).
8. Инфраструктурный iiko-клиент лояльности (`infrastructure/iiko_client.py`).

### 2.4 Settings и приложения

1. Централизованные настройки через `AppSettings` (`settings.py`).
2. Первая точка входа приложения: `apps/telegram_app.py`.
3. Telegram-приложение использует два use-case: регистрация и чтение профиля по аккаунту.
4. Добавлена точка входа VK-приложения: `apps/vk_app.py`.
5. Добавлена точка входа MAX-приложения: `apps/max_app.py`.
6. Во всех приложениях подключены use-case поддержки/модерации (создание тикета, маршрутизация ответа, карточка тикета, список открытых тикетов, выборка pending и фиксация статуса доставки).
7. Во всех приложениях и роутерах добавлены этапные логи взаимодействий (входящие события, onboarding, модерация, pending-доставка).
8. В `AppSettings` добавлены параметры интеграции с iiko (`IIKO_API_KEY`, `IIKO_ORG_ID`, `IIKO_BASE_URL`) и флаг `is_iiko_configured`.
9. Во всех приложениях подключены loyalty-use-case (`GetLoyaltyBalanceUseCase`, `GetVirtualCardUseCase`) с единым iiko-шлюзом.

## 3. Строгая идентификация (Strict Identity)

Правило проекта:

1. `phone -> person` является уникальным соответствием.
2. Один телефон не может соответствовать двум разным людям.
3. Конфликтные перепривязки аккаунтов должны поднимать доменную ошибку.

## 4. Текущая схема данных

Текущий контур strict identity и поддержки включает:

1. `persons` — единый профиль человека.
2. `phones` — канонический телефон человека (`UNIQUE phone_e164`, `UNIQUE person_id`).
3. `platform_accounts` — привязка `platform + external_id -> person_id` с `UNIQUE(platform, external_id)`.
4. `support_tickets` — тикеты поддержки, привязанные к `person_id`.
5. `support_messages` — сообщения тикета и данные маршрутизации модераторского ответа.

Это позволит:

1. Хранить одну анкету на человека.
2. Связывать одного человека с Telegram, VK и MAX одновременно.
3. Принимать обращение в одном мессенджере и отправлять ответ модератора в другой канал того же пользователя.
