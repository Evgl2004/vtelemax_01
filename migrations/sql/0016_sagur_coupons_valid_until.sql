-- SAGUR coupons: store machine-readable coupon validity deadline.
-- Migration version: 0016

BEGIN;

ALTER TABLE person_coupons
    ADD COLUMN IF NOT EXISTS valid_until TIMESTAMPTZ NULL;

COMMIT;
