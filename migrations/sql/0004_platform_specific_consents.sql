-- Добавление платформо-специфичных полей согласия и уведомлений.
-- Версия миграции: 0004

BEGIN;

ALTER TABLE persons
    ADD COLUMN IF NOT EXISTS rules_accepted_tg BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS rules_accepted_tg_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS rules_accepted_vk BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS rules_accepted_vk_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS rules_accepted_max BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS rules_accepted_max_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS notifications_allowed_tg BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS notifications_allowed_tg_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS notifications_allowed_vk BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS notifications_allowed_vk_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS notifications_allowed_max BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS notifications_allowed_max_at TIMESTAMPTZ NULL;

COMMIT;