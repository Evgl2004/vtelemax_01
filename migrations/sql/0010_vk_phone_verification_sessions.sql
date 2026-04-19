-- Sessions for VK Mini App phone verification flow.
-- Migration version: 0010

BEGIN;

CREATE TABLE IF NOT EXISTS vk_phone_verification_sessions (
    session_id UUID PRIMARY KEY,
    vk_user_id BIGINT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'created',
    phone_e164 VARCHAR(16) NULL,
    failure_reason TEXT NULL,
    launch_uid BIGINT NULL,
    launch_ts BIGINT NULL,
    raw_payload JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    verified_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    CONSTRAINT ck_vk_phone_verification_sessions_status_allowed
        CHECK (status IN ('created', 'verified', 'failed', 'expired'))
);

CREATE INDEX IF NOT EXISTS ix_vk_phone_verification_sessions_vk_user_created_at
    ON vk_phone_verification_sessions(vk_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_vk_phone_verification_sessions_status_expires_at
    ON vk_phone_verification_sessions(status, expires_at);

CREATE UNIQUE INDEX IF NOT EXISTS uq_vk_phone_verification_sessions_user_created
    ON vk_phone_verification_sessions(vk_user_id)
    WHERE status = 'created';

COMMIT;

