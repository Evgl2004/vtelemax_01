-- Добавляет признак модератора и расширяет статусы тикетов.
-- Версия миграции: 0006

BEGIN;

ALTER TABLE persons
    ADD COLUMN IF NOT EXISTS is_moderator BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE support_tickets
    DROP CONSTRAINT IF EXISTS ck_support_tickets_status_allowed;

ALTER TABLE support_tickets
    ADD CONSTRAINT ck_support_tickets_status_allowed
        CHECK (status IN ('open', 'in_progress', 'closed'));

COMMIT;
