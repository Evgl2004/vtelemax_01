-- SAGUR coupon events: storage + idempotency.
-- Migration version: 0014

BEGIN;

CREATE TABLE IF NOT EXISTS sagur_coupon_events (
    event_id UUID PRIMARY KEY,
    direction VARCHAR(32) NOT NULL,
    sent_at TIMESTAMPTZ NULL,
    payload_json JSONB NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_sagur_coupon_events_direction_allowed
        CHECK (direction IN ('assignments', 'status_update'))
);

CREATE TABLE IF NOT EXISTS person_coupons (
    coupon_id UUID PRIMARY KEY,
    person_id UUID NOT NULL REFERENCES persons(person_id) ON DELETE CASCADE,
    coupon_series VARCHAR(64) NOT NULL,
    coupon_code VARCHAR(128) NOT NULL,
    campaign_id VARCHAR(128) NULL,
    venue_code VARCHAR(64) NOT NULL DEFAULT '__global__',
    venue_name VARCHAR(255) NULL,
    promo_text TEXT NULL,
    status VARCHAR(32) NOT NULL,
    is_visible BOOLEAN NOT NULL DEFAULT TRUE,
    last_event_id UUID NULL REFERENCES sagur_coupon_events(event_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_person_coupons_status_allowed
        CHECK (status IN ('reserved', 'sent', 'used', 'expired', 'canceled', 'error')),
    CONSTRAINT uq_person_coupons_person_series_code
        UNIQUE (person_id, coupon_series, coupon_code)
);

CREATE INDEX IF NOT EXISTS ix_person_coupons_person_visible
    ON person_coupons(person_id, is_visible);

CREATE INDEX IF NOT EXISTS ix_person_coupons_person_venue_visible
    ON person_coupons(person_id, venue_code, is_visible);

CREATE INDEX IF NOT EXISTS ix_person_coupons_last_event_id
    ON person_coupons(last_event_id);

COMMIT;
