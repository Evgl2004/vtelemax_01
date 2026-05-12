-- Добавление источника последней гостевой активности в тикетах поддержки.
-- Версия миграции: 0013

BEGIN;

ALTER TABLE support_tickets
    ADD COLUMN IF NOT EXISTS last_guest_external_id VARCHAR(128);

CREATE INDEX IF NOT EXISTS ix_support_tickets_last_guest_external_id
    ON support_tickets(last_guest_external_id);

COMMIT;
