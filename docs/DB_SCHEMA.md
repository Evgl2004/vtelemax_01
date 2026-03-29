# Схема БД strict identity + support (v2)

Документ описывает текущую схему PostgreSQL для единой идентификации пользователя и тикетов поддержки.

## 1. Таблица `persons`

Назначение: единая сущность человека, независимая от платформы.

Поля:

1. `person_id` (`UUID`, PK).
2. `created_at` (`TIMESTAMPTZ`, NOT NULL, `NOW()`).
3. `updated_at` (`TIMESTAMPTZ`, NOT NULL, `NOW()`).
4. `rules_accepted` (`BOOLEAN`, NOT NULL, default `false`).
5. `rules_accepted_at` (`TIMESTAMPTZ`, NULL).
6. `notifications_allowed` (`BOOLEAN`, NOT NULL, default `false`).
7. `notifications_allowed_at` (`TIMESTAMPTZ`, NULL).
8. `is_legacy` (`BOOLEAN`, NOT NULL, default `false`).
9. `is_registered` (`BOOLEAN`, NOT NULL, default `false`).
10. `first_name_input` (`VARCHAR(255)`, NULL).
11. `last_name_input` (`VARCHAR(255)`, NULL).
12. `gender` (`VARCHAR(10)`, NULL).
13. `birth_date` (`DATE`, NULL).
14. `email` (`VARCHAR(255)`, NULL).
15. `phone_verified_at` (`TIMESTAMPTZ`, NULL).
16. `phone_verification_method` (`VARCHAR(20)`, NULL).

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

## 4. Таблица `support_tickets`

Назначение: тикет поддержки, связанный с пользователем (`person_id`) и источником обращения.

Поля:

1. `ticket_id` (`UUID`, PK).
2. `person_id` (`UUID`, FK -> `persons.person_id`, `ON DELETE CASCADE`).
3. `status` (`VARCHAR(16)`, NOT NULL, default `open`).
4. `source_platform` (`VARCHAR(16)`, NOT NULL).
5. `last_guest_platform` (`VARCHAR(16)`, NULL).
6. `created_at` (`TIMESTAMPTZ`, NOT NULL, `NOW()`).
7. `updated_at` (`TIMESTAMPTZ`, NOT NULL, `NOW()`).
8. `closed_at` (`TIMESTAMPTZ`, NULL).

Ограничения:

1. `CHECK(status IN ('open', 'closed'))`.
2. `CHECK(source_platform IN ('telegram', 'vk', 'max'))`.
3. `CHECK(last_guest_platform IS NULL OR last_guest_platform IN ('telegram', 'vk', 'max'))`.
4. Индексы `ix_support_tickets_person_id`, `ix_support_tickets_status`.

## 5. Таблица `support_messages`

Назначение: сообщения внутри тикета и сведения о маршрутизации доставки ответа модератора.

Поля:

1. `message_id` (`UUID`, PK).
2. `ticket_id` (`UUID`, FK -> `support_tickets.ticket_id`, `ON DELETE CASCADE`).
3. `author` (`VARCHAR(16)`, NOT NULL, `guest`/`moderator`).
4. `body` (`TEXT`, NOT NULL).
5. `source_platform` (`VARCHAR(16)`, NOT NULL).
6. `target_platform` (`VARCHAR(16)`, NULL) — заполняется для модераторского ответа.
7. `target_external_id` (`VARCHAR(128)`, NULL) — целевой аккаунт пользователя.
8. `delivery_status` (`VARCHAR(16)`, NULL) — `created`/`sent`/`failed`.
9. `delivery_error` (`TEXT`, NULL).
10. `created_at` (`TIMESTAMPTZ`, NOT NULL, `NOW()`).

Ограничения:

1. `CHECK(author IN ('guest', 'moderator'))`.
2. `CHECK(source_platform IN ('telegram', 'vk', 'max'))`.
3. `CHECK(target_platform IS NULL OR target_platform IN ('telegram', 'vk', 'max'))`.
4. `CHECK(delivery_status IS NULL OR delivery_status IN ('created', 'sent', 'failed'))`.
5. Индексы `ix_support_messages_ticket_id`, `ix_support_messages_target_platform_status`.

## 6. Источники истины

1. SQLAlchemy схема: `src/vtelemax/infrastructure/postgres/schema.py`.
2. SQL-миграция strict identity: `migrations/sql/0001_strict_identity.sql`.
3. SQL-миграция support-слоя: `migrations/sql/0002_support_tickets.sql`.
4. SQL-миграция расширения профиля: `migrations/sql/0003_person_profile_fields.sql`.
