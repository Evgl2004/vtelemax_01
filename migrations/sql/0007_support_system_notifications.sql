-- Расширяет автора support_messages для системных уведомлений модераторам.
-- Версия миграции: 0007

BEGIN;

ALTER TABLE support_messages
    DROP CONSTRAINT IF EXISTS ck_support_messages_author_allowed;

ALTER TABLE support_messages
    ADD CONSTRAINT ck_support_messages_author_allowed
        CHECK (author IN ('guest', 'moderator', 'system'));

COMMIT;
