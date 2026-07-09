-- SAGUR guest registration events: unified outgoing registry and delivery outbox.

CREATE TABLE IF NOT EXISTS sagur_guest_registration_events (
    record_id UUID PRIMARY KEY,
    person_id UUID NOT NULL REFERENCES persons(person_id) ON DELETE CASCADE,
    platform VARCHAR(16) NOT NULL,
    external_id VARCHAR(128) NOT NULL,
    phone_e164 VARCHAR(16) NOT NULL,
    registration_origin VARCHAR(32) NOT NULL,
    iiko_status VARCHAR(32) NOT NULL,
    sagur_status VARCHAR(32) NOT NULL,
    customer_id VARCHAR(128),
    created_new_customer BOOLEAN NOT NULL DEFAULT false,
    existing_customer_found BOOLEAN NOT NULL DEFAULT false,
    event_id VARCHAR(128),
    request_id VARCHAR(128),
    event_type VARCHAR(64) NOT NULL DEFAULT 'guest_registered',
    payload_json JSONB,
    payload_body BYTEA,
    payload_sha256 VARCHAR(64),
    attempts INTEGER NOT NULL DEFAULT 0,
    recovery_attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_at TIMESTAMPTZ,
    lookup_started_at TIMESTAMPTZ,
    lookup_finished_at TIMESTAMPTZ,
    create_started_at TIMESTAMPTZ,
    iiko_response_received_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    recovery_reason TEXT,
    last_error_code VARCHAR(128),
    last_error_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_sagur_guest_registration_events_platform_allowed
        CHECK (platform IN ('telegram', 'vk', 'max')),
    CONSTRAINT ck_sagur_guest_registration_events_origin_allowed
        CHECK (registration_origin IN ('new_registration', 'legacy_upgrade')),
    CONSTRAINT ck_sagur_guest_registration_events_iiko_status_allowed
        CHECK (
            iiko_status IN (
                'lookup_started',
                'create_started',
                'created',
                'existing',
                'result_unknown',
                'not_required',
                'manual_review',
                'failed_terminal'
            )
        ),
    CONSTRAINT ck_sagur_guest_registration_events_sagur_status_allowed
        CHECK (
            sagur_status IN (
                'not_ready',
                'pending',
                'processing',
                'sent',
                'retry_scheduled',
                'conflict',
                'not_required',
                'manual_review',
                'failed_terminal'
            )
        ),
    CONSTRAINT ck_sagur_guest_registration_events_attempts_non_negative
        CHECK (attempts >= 0),
    CONSTRAINT ck_sagur_guest_registration_events_recovery_attempts_non_negative
        CHECK (recovery_attempts >= 0),
    CONSTRAINT ck_sagur_guest_registration_events_event_id_len
        CHECK (event_id IS NULL OR length(event_id) <= 128),
    CONSTRAINT ck_sagur_guest_registration_events_request_id_len
        CHECK (request_id IS NULL OR length(request_id) <= 128)
);

CREATE INDEX IF NOT EXISTS ix_sagur_guest_registration_events_sagur_next_attempt
    ON sagur_guest_registration_events(sagur_status, next_attempt_at);

CREATE INDEX IF NOT EXISTS ix_sagur_guest_registration_events_iiko_next_attempt
    ON sagur_guest_registration_events(iiko_status, next_attempt_at);

CREATE INDEX IF NOT EXISTS ix_sagur_guest_registration_events_person_id
    ON sagur_guest_registration_events(person_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sagur_guest_registration_events_event_id
    ON sagur_guest_registration_events(event_id)
    WHERE event_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_sagur_guest_registration_events_active_context
    ON sagur_guest_registration_events(person_id, platform, external_id, registration_origin)
    WHERE sagur_status NOT IN (
        'sent',
        'conflict',
        'not_required',
        'manual_review',
        'failed_terminal'
    );
