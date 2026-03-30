# Legacy Migration: Telegram (sobalbot -> vtelemax)

Документ фиксирует поверхностный анализ старого проекта и правила переноса пользователей в новую strict-identity модель.

## 1. Источник данных (старый бот)

Источник: проект `C:\Users\admin_eas\PycharmProjects\sobalbot`.

Фактически используемая база:  
`C:\Users\admin_eas\PycharmProjects\sobalbot\data\bot_requests.db` (SQLite).

Ключевые таблицы:

1. `user_phones`:
   1. `user_id` (INTEGER, Telegram ID, PK);
   2. `phone` (TEXT);
   3. `created_at` (DATETIME).
2. `requests`:
   1. история вопросов/ответов поддержки;
   2. для миграции identity напрямую не используется.
3. `rate_limits`:
   1. техническая таблица старого бота;
   2. для миграции identity не используется.

Вывод по анализу:

1. В старом источнике нет полной анкеты профиля (нет нормализованных полей `first_name`, `gender`, `birth_date`, `email`).
2. Надежно переносим только связку `telegram_user_id + phone`.
3. Остальной профиль пользователь заполнит в новом onboarding/legacy-сценарии.

## 2. Маппинг в новую модель vtelemax

Для каждой валидной source-строки выполняется upsert через strict identity:

1. `platform = telegram`;
2. `external_id = user_id` из старой таблицы;
3. `raw_phone = phone` из source c нормализацией в `+7XXXXXXXXXX`;
4. `is_legacy = true`;
5. `is_registered = false`;
6. `rules_accepted = true` и `rules_accepted_at = created_at source (или now)`;
7. `phone_verified_at = created_at source (или now)`;
8. `phone_verification_method = legacy_import_sobalbot`.

## 3. Скрипт миграции

Скрипт: `scripts/migrate_legacy_telegram_users.py`.

Что умеет:

1. `--dry-run` без записи в PostgreSQL.
2. Прогресс обработки в формате `N/total (%)`.
3. Точечный режим по одному номеру: `--phone +79...`.
4. Пакетная обработка: `--limit`, `--offset`.
5. Вывод примеров проблемных строк (невалидный телефон, конфликт strict identity).

Примеры запуска (Windows):

```powershell
# 1) Предпросмотр общего переноса
.\.venv\Scripts\python.exe scripts/migrate_legacy_telegram_users.py --dry-run

# 2) Предпросмотр точечного переноса одного номера
.\.venv\Scripts\python.exe scripts/migrate_legacy_telegram_users.py --phone +79129923438 --dry-run

# 3) Фактический перенос одного номера
.\.venv\Scripts\python.exe scripts/migrate_legacy_telegram_users.py --phone +79129923438 --yes

# 4) Фактический перенос общего массива
.\.venv\Scripts\python.exe scripts/migrate_legacy_telegram_users.py --yes --progress-every 500
```

Пример запуска в контейнере (если SQLite-файл смонтирован внутрь контейнера):

```bash
sudo docker compose exec telegram-bot \
  python scripts/migrate_legacy_telegram_users.py \
  --source-db /app/data/legacy/bot_requests.db \
  --yes
```

## 4. Поведение при грязных данных

Скрипт не падает на первой ошибке:

1. невалидные телефоны помечаются как `invalid` и пропускаются;
2. strict-identity конфликты фиксируются отдельно (`conflict`);
3. миграция продолжается по остальным строкам;
4. в конце печатается сводка и примеры проблемных строк.

## 5. Точки развития (зафиксировано)

1. На первом входе legacy-пользователя рассмотреть обогащение профиля из iiko
   (не только по локально перенесенным данным).
2. Для обновления профиля добавить отложенную выгрузку в iiko:
   1. сохранять изменения локально сразу;
   2. отправлять пакетно по расписанию/очереди;
   3. не дергать iiko на каждый отдельный edit-атрибут.
