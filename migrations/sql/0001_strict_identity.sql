-- Базовая схема strict identity для vtelemax.
-- Версия миграции: 0001

BEGIN;

CREATE TABLE IF NOT EXISTS persons (
    person_id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS phones (
    phone_id UUID PRIMARY KEY,
    person_id UUID NOT NULL REFERENCES persons(person_id) ON DELETE CASCADE,
    phone_e164 VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_phones_phone_e164 UNIQUE (phone_e164),
    CONSTRAINT uq_phones_person_id UNIQUE (person_id)
);

CREATE TABLE IF NOT EXISTS platform_accounts (
    account_id UUID PRIMARY KEY,
    person_id UUID NOT NULL REFERENCES persons(person_id) ON DELETE CASCADE,
    platform VARCHAR(16) NOT NULL,
    external_id VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_platform_accounts_platform_external_id UNIQUE (platform, external_id),
    CONSTRAINT ck_platform_accounts_platform_allowed
        CHECK (platform IN ('telegram', 'vk', 'max'))
);

CREATE INDEX IF NOT EXISTS ix_platform_accounts_person_id
    ON platform_accounts(person_id);

COMMIT;
