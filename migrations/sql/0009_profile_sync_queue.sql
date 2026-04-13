-- Queue for asynchronous profile synchronization with iiko.
-- Migration version: 0009

BEGIN;

CREATE TABLE IF NOT EXISTS profile_sync_queue (
    sync_id UUID PRIMARY KEY,
    person_id UUID NOT NULL REFERENCES persons(person_id) ON DELETE CASCADE,
    source_platform VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_at TIMESTAMPTZ NULL,
    error_text TEXT NULL,
    payload_json JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_profile_sync_queue_platform_allowed
        CHECK (source_platform IN ('telegram', 'vk', 'max')),
    CONSTRAINT ck_profile_sync_queue_status_allowed
        CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    CONSTRAINT ck_profile_sync_queue_attempts_non_negative
        CHECK (attempts >= 0)
);

CREATE INDEX IF NOT EXISTS ix_profile_sync_queue_status_next_attempt_at
    ON profile_sync_queue(status, next_attempt_at);

CREATE INDEX IF NOT EXISTS ix_profile_sync_queue_person_id
    ON profile_sync_queue(person_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_profile_sync_queue_person_pending
    ON profile_sync_queue(person_id)
    WHERE status = 'pending';

COMMIT;

