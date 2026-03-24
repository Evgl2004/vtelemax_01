-- Схема поддержки и кросс-мессенджер модерации для vtelemax.
-- Версия миграции: 0002

BEGIN;

CREATE TABLE IF NOT EXISTS support_tickets (
    ticket_id UUID PRIMARY KEY,
    person_id UUID NOT NULL REFERENCES persons(person_id) ON DELETE CASCADE,
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    source_platform VARCHAR(16) NOT NULL,
    last_guest_platform VARCHAR(16) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_support_tickets_status_allowed
        CHECK (status IN ('open', 'closed')),
    CONSTRAINT ck_support_tickets_source_platform_allowed
        CHECK (source_platform IN ('telegram', 'vk', 'max')),
    CONSTRAINT ck_support_tickets_last_guest_platform_allowed
        CHECK (
            last_guest_platform IS NULL
            OR last_guest_platform IN ('telegram', 'vk', 'max')
        )
);

CREATE INDEX IF NOT EXISTS ix_support_tickets_person_id
    ON support_tickets(person_id);
CREATE INDEX IF NOT EXISTS ix_support_tickets_status
    ON support_tickets(status);

CREATE TABLE IF NOT EXISTS support_messages (
    message_id UUID PRIMARY KEY,
    ticket_id UUID NOT NULL REFERENCES support_tickets(ticket_id) ON DELETE CASCADE,
    author VARCHAR(16) NOT NULL,
    body TEXT NOT NULL,
    source_platform VARCHAR(16) NOT NULL,
    target_platform VARCHAR(16) NULL,
    target_external_id VARCHAR(128) NULL,
    delivery_status VARCHAR(16) NULL,
    delivery_error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_support_messages_author_allowed
        CHECK (author IN ('guest', 'moderator')),
    CONSTRAINT ck_support_messages_source_platform_allowed
        CHECK (source_platform IN ('telegram', 'vk', 'max')),
    CONSTRAINT ck_support_messages_target_platform_allowed
        CHECK (
            target_platform IS NULL
            OR target_platform IN ('telegram', 'vk', 'max')
        ),
    CONSTRAINT ck_support_messages_delivery_status_allowed
        CHECK (
            delivery_status IS NULL
            OR delivery_status IN ('created', 'sent', 'failed')
        )
);

CREATE INDEX IF NOT EXISTS ix_support_messages_ticket_id
    ON support_messages(ticket_id);
CREATE INDEX IF NOT EXISTS ix_support_messages_target_platform_status
    ON support_messages(target_platform, delivery_status);

COMMIT;
