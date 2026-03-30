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
4. `SQLAlchemySupportRepository` и транзакционных support use-case (тикет/модерация).

Текущий формат integration-тестов:

1. Выполняются на SQLite in-memory через SQLAlchemy metadata.
2. Проверяют контракты репозитория и транзакционное поведение (`commit`/`rollback`).

## 6. Обязательная практика "грязных" тестов

Для каждого нового сценария мы проверяем не только happy path, но и негативные ветки:

1. Невалидные или "грязные" входные данные (`None`, пустые значения, неверный формат).
2. Конфликтные состояния strict identity (дубли, перепривязка, нарушения `UNIQUE`).
3. Поведение транзакций при ошибках (rollback и отсутствие частично сохраненных данных).
4. Трансляцию инфраструктурных ошибок в доменные ошибки.

Это правило считается обязательным для всех следующих этапов разработки.

Дополнительно на текущем этапе покрыты:

1. Модель настроек `AppSettings`.
2. Telegram-адаптер регистрации и его негативные сценарии.
3. Telegram-меню (профиль/помощь/неизвестные команды/незарегистрированный пользователь).
4. Use-case чтения пользователя по аккаунту платформы.
5. Единый core-контракт меню и эталонный контент гостевых экранов.
6. Стартовый VK-адаптер меню и payload-конвертер.
7. VK identity-адаптер (регистрация по телефону, меню, сценарий обращения в поддержку).
8. Рендер VK-клавиатур и валидация VK-настроек в `AppSettings`.
9. MAX-адаптер меню/payload/identity и рендер MAX-клавиатур.
10. Валидация MAX-настроек в `AppSettings`.
11. Adapter-contract тесты согласованности поведения Telegram/VK/MAX.
12. Единый onboarding-flow `core` (регистрация + legacy) и его dirty-сценарии.
13. Telegram onboarding/legacy-ветка (`/start` + `/legacy`) на общем flow.
14. VK onboarding/legacy-ветка на общем flow (включая dirty-сценарии согласия).
15. MAX onboarding/legacy-ветка на общем flow (включая dirty-сценарии согласия).
16. Core use-case поддержки/модерации (создание тикета, выбор канала доставки ответа, карточка тикета).
17. Команды модератора `/modreply` и `/modticket` в Telegram/VK/MAX.
18. FSM-сценарий `/mod` (меню модератора, выбор тикета, ответ, карточка) в Telegram/VK/MAX, включая грязные входные данные (некорректный UUID).
19. MVP-доставку pending-сообщений модератора (одна попытка) с фиксацией статусов `sent/failed`.
20. Integration/live-сценарии кросс-мессенджерной маршрутизации ответа модератора.
21. Модуль SQL-миграций для Docker-запуска (сортировка файлов, парсинг SQL, грязные сценарии пустых миграций).
22. Конфигурацию централизованного логирования (`LOG_LEVEL`, валидация и инициализация sink).
23. Сценарий «Мои обращения» (Telegram/VK/MAX): список тикетов, empty-state и грязные проверки входных данных для use-case списка тикетов пользователя.
24. Сценарии лояльности `Мой баланс` и `Виртуальная карта`:
   1. unit-тесты core use-case (happy path + грязные ветки ошибок шлюза, пустых данных, ошибок регистрации/выпуска карты);
   2. unit-тесты Telegram/VK/MAX адаптеров на использование общего loyalty use-case вместо заглушек.

## 7. Живые тесты на локальном PostgreSQL

По умолчанию живые тесты отключены. Для запуска:

1. В `.env` выставить `VTELEMAX_RUN_POSTGRES_LIVE_TESTS=1`.
2. Проверить параметры подключения:
   `POSTGRES_HOST=localhost`, `POSTGRES_PORT=5433`,
   `POSTGRES_DB=postgres`, `POSTGRES_USER=postgres`, `POSTGRES_PASSWORD=1234`.
3. Запустить общий `pytest` или только live-тесты:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_pytest.ps1 tests/integration/test_postgres_live_identity_repository.py tests/integration/test_postgres_live_support_repository.py
```

Live-тесты создают временную схему в PostgreSQL и удаляют ее после завершения.

## 8. Ручной сброс пользователя для повторной регистрации

Для повторного прогона onboarding в Telegram/VK/MAX можно удалить тестового пользователя по телефону:

```powershell
# Предпросмотр изменений:
.\.venv\Scripts\python.exe scripts/reset_test_user.py --phone +79991234567 --dry-run --clean-redis

# Фактическое удаление:
.\.venv\Scripts\python.exe scripts/reset_test_user.py --phone +79991234567 --yes --clean-redis
```

Примечание: текущее FSM-состояние адаптеров хранится в памяти процессов, поэтому после очистки БД/Redis
рекомендуется перезапустить контейнеры ботов.
