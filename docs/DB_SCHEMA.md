# Схема БД strict identity (v1)

Документ описывает стартовую схему PostgreSQL для единой идентификации пользователя.

## 1. Таблица `persons`

Назначение: единая сущность человека, независимая от платформы.

Поля:

1. `person_id` (`UUID`, PK).
2. `created_at` (`TIMESTAMPTZ`, NOT NULL, `NOW()`).
3. `updated_at` (`TIMESTAMPTZ`, NOT NULL, `NOW()`).

## 2. Таблица `phones`

Назначение: канонический телефон человека в формате E.164.

Поля:

1. `phone_id` (`UUID`, PK).
2. `person_id` (`UUID`, FK -> `persons.person_id`, `ON DELETE CASCADE`).
3. `phone_e164` (`VARCHAR(16)`, NOT NULL).
4. `created_at` (`TIMESTAMPTZ`, NOT NULL, `NOW()`).

Ограничения:

1. `UNIQUE(phone_e164)` — один телефон принадлежит только одному человеку.
2. `UNIQUE(person_id)` — на текущем этапе один человек имеет один основной телефон.

## 3. Таблица `platform_accounts`

Назначение: привязка аккаунтов Telegram/VK/MAX к человеку.

Поля:

1. `account_id` (`UUID`, PK).
2. `person_id` (`UUID`, FK -> `persons.person_id`, `ON DELETE CASCADE`).
3. `platform` (`VARCHAR(16)`, NOT NULL).
4. `external_id` (`VARCHAR(128)`, NOT NULL).
5. `created_at` (`TIMESTAMPTZ`, NOT NULL, `NOW()`).

Ограничения:

1. `UNIQUE(platform, external_id)` — один аккаунт платформы может принадлежать только одному человеку.
2. `CHECK(platform IN ('telegram', 'vk', 'max'))` — допустимые платформы ограничены.
3. Индекс `ix_platform_accounts_person_id` для ускорения выборки аккаунтов по человеку.

## 4. Источники истины

1. SQLAlchemy схема: `src/vtelemax/infrastructure/postgres/schema.py`.
2. SQL-миграция: `migrations/sql/0001_strict_identity.sql`.
