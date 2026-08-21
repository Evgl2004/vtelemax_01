-- Интерактивные сообщения SAGUR: факт нажатия и текущее состояние обработки.

CREATE TABLE IF NOT EXISTS sagur_message_interaction_events (
    event_id UUID PRIMARY KEY,
    platform VARCHAR(16) NOT NULL,
    bot_scope VARCHAR(128) NOT NULL,
    platform_callback_id VARCHAR(512) NOT NULL,
    interaction_id BIGINT NOT NULL,
    action VARCHAR(1) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    provider_message_id VARCHAR(255),
    delivery_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL,
    locked_at TIMESTAMPTZ,
    delivery_lease_id UUID,
    delivery_result VARCHAR(64),
    delivered_at TIMESTAMPTZ,
    delivery_error_code VARCHAR(128),
    delivery_error_text TEXT,
    user_action_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    user_action_attempted_at TIMESTAMPTZ,
    user_action_finished_at TIMESTAMPTZ,
    user_action_error_code VARCHAR(128),
    user_action_error_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sagur_message_interaction_events_platform_allowed
        CHECK (platform IN ('telegram', 'vk', 'max')),
    CONSTRAINT ck_sagur_message_interaction_events_interaction_id_positive
        CHECK (interaction_id > 0),
    CONSTRAINT ck_sagur_message_interaction_events_action_allowed
        CHECK (action IN ('l', 'd', 'm', 'c')),
    CONSTRAINT ck_sagur_message_interaction_events_delivery_status_allowed
        CHECK (delivery_status IN ('pending', 'processing', 'retry_scheduled', 'delivered', 'blocked')),
    CONSTRAINT ck_sagur_message_interaction_events_user_action_status_allowed
        CHECK (user_action_status IN ('pending', 'succeeded', 'failed')),
    CONSTRAINT ck_sagur_message_interaction_events_attempts_non_negative
        CHECK (delivery_attempts >= 0),
    CONSTRAINT uq_sagur_message_interaction_events_platform_callback
        UNIQUE (platform, bot_scope, platform_callback_id)
);

CREATE INDEX IF NOT EXISTS ix_sagur_message_interaction_events_due
    ON sagur_message_interaction_events(next_attempt_at, occurred_at)
    WHERE delivery_status IN ('pending', 'retry_scheduled');

CREATE INDEX IF NOT EXISTS ix_sagur_message_interaction_events_processing
    ON sagur_message_interaction_events(locked_at)
    WHERE delivery_status = 'processing';
