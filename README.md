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
5. SQL-миграция `migrations/sql/0002_support_tickets.sql` для тикетов поддержки и сообщений модерации.
6. SQLAlchemy-репозиторий и Unit Of Work для strict identity и поддержки.
7. Единый контракт гостевого меню/текстов в `core` (эталон: Telegram-прототип).
8. Единый onboarding-flow в `core` (регистрация + legacy-ветка), подключенный в Telegram/VK/MAX.
9. Единый сценарный слой поддержки/модерации в `core` с кросс-мессенджерной маршрутизацией ответа.
10. Рабочие адаптеры Telegram/VK/MAX на общем контракте меню, onboarding и support-модерации.
11. Во всех трех адаптерах доступно FSM-меню модератора `/mod` (список тикетов, ответ, карточка тикета).
12. Команды модерации `/modreply` и `/modticket` сохранены как прямые технические команды.
13. Реализована MVP-доставка pending-сообщений модератора в целевые каналы (одна попытка, фиксация `sent/failed`).
14. Ретраи/backoff доставки вынесены в следующий этап развития.
15. Скрипты Windows для настройки `.venv` и запуска тестов.
16. Adapter-contract тесты для согласованности поведения между Telegram/VK/MAX.
17. Тесты на `pytest` для ядра, ограничений схемы и integration/live-сценариев репозиториев.
18. Docker-инфраструктура: `Dockerfile` и `docker-compose.yml` для запуска PostgreSQL + Telegram/VK/MAX.
19. Скрипт `scripts/apply_sql_migrations.py` для применения SQL-миграций перед стартом контейнеров.
20. Централизованное логирование (`loguru`) с поддержкой уровней `LOG_LEVEL` и этапных логов взаимодействия.
21. Единые use-case лояльности (`Мой баланс`, `Виртуальная карта`) вынесены в `core` и подключены к Telegram/VK/MAX.
22. Добавлен инфраструктурный iiko-клиент (`IikoLoyaltyGateway`) и настройки `IIKO_API_KEY`, `IIKO_ORG_ID`, `IIKO_BASE_URL`.
23. Добавлены unit-тесты loyalty-сценариев (happy path + грязные ветки) и тесты интеграции loyalty-use-case в адаптеры.

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
powershell -ExecutionPolicy Bypass -File scripts/run_pytest.ps1 tests/integration/test_postgres_live_identity_repository.py tests/integration/test_postgres_live_support_repository.py
```

Запуск первого адаптера Telegram (локально, без Docker):

```powershell
.\.venv\Scripts\python.exe -m vtelemax.apps.telegram_app
```

Запуск VK-адаптера (локально, без Docker):

```powershell
.\.venv\Scripts\python.exe -m vtelemax.apps.vk_app
```

Запуск MAX-адаптера (локально, без Docker):

```powershell
.\.venv\Scripts\python.exe -m vtelemax.apps.max_app
```

Применение SQL-миграций локально (при необходимости):

```powershell
.\.venv\Scripts\python.exe scripts/apply_sql_migrations.py
```

Сброс тестового пользователя по телефону (для повторной проверки регистрации):

```powershell
# Предпросмотр (без изменений)
.\.venv\Scripts\python.exe scripts/reset_test_user.py --phone +79991234567 --dry-run --clean-redis

# Фактическое удаление из PostgreSQL + очистка Redis-ключей
.\.venv\Scripts\python.exe scripts/reset_test_user.py --phone +79991234567 --yes --clean-redis
```

Запуск всего стека в Docker Compose:

```bash
docker compose up -d --build
```

Для детальной диагностики можно включить расширенный режим логов:

```dotenv
LOG_LEVEL=DEBUG
```

Просмотр логов ботов:

```bash
docker compose logs -f telegram-bot
docker compose logs -f vk-bot
docker compose logs -f max-bot
```

Текущие команды/кнопки Telegram-бота:

1. `/start` — запуск onboarding: согласие с правилами, затем запрос контакта.
2. `/menu` или `Главное меню` — показать разделы.
3. `💰 Мой баланс`, `🪪 Виртуальная карта`, `🆘 Отдел заботы`, `💼 Вакансии` — разделы эталонного меню.
4. `Мой профиль` — показать телефон и число привязанных аккаунтов.
5. `Помощь` — подсказки по регистрации и работе с ботом.
6. `О проекте` — краткая информация о платформе.
7. `/legacy` — ручной запуск ветки обновления legacy-профиля (подтверждение телефона).
8. Те же пункты синхронизированы в VK- и MAX-адаптерах через callback/payload-кнопки.
9. Onboarding-flow (правила -> телефон + legacy-подтверждение) теперь единый для Telegram/VK/MAX.
10. `🆘 Отдел заботы` переводит в сценарий вопроса, где создается тикет поддержки и фиксируется исходная платформа гостя.
11. `/mod` — единое FSM-меню модератора: список открытых тикетов, ответ на тикет, карточка тикета.
12. `/modreply <ticket_id> [--to=telegram|vk|max] <текст>` — прямой ответ модератора из любого бота с маршрутизацией в целевой канал гостя.
13. `/modticket <ticket_id>` — прямая команда карточки тикета (источник обращения, последняя платформа гостя, список привязанных платформ).
14. Pending-ответы модератора автоматически доставляются в целевой мессенджер при обработке входящих событий бота (MVP: одна попытка).

Для полноценной работы разделов `💰 Мой баланс` и `🪪 Виртуальная карта` заполните в `.env`:

```dotenv
IIKO_API_KEY=...
IIKO_ORG_ID=...
# опционально
IIKO_BASE_URL=https://api-ru.iiko.services/api/1
```

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
    adapter_contract/
    integration/
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
2. Итоговое развёртывание проекта выполняется через Docker Compose (`docker-compose.yml`).
3. Для контейнерного запуска используется idempotent-скрипт SQL-миграций `scripts/apply_sql_migrations.py`.
4. Логирование всех приложений настраивается через `LOG_LEVEL` (`INFO` по умолчанию, `DEBUG` для диагностики).
5. Для включения функционала лояльности нужно заполнить `IIKO_API_KEY` и `IIKO_ORG_ID` (иначе разделы покажут fallback-сообщение о недоступности).

## 8. Документы проекта

1. Архитектура: `docs/ARCHITECTURE.md`.
2. Процесс и правила разработки: `docs/DEVELOPMENT_WORKFLOW.md`.
3. Зафиксированный пошаговый план: `docs/DEVELOPMENT_PLAN.md`.
4. Схема БД strict identity: `docs/DB_SCHEMA.md`.
5. Тестирование: `docs/TESTING.md`.
6. Контейнерный запуск: `docs/DEPLOYMENT_DOCKER.md`.
7. Матрица UI-паритета с прототипами: `docs/PARITY_SPEC_V1.md`.
8. Сценарий QR для виртуальной карты: `docs/VIRTUAL_CARD_QR.md`.
