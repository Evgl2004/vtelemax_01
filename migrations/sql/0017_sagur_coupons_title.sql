-- SAGUR coupon guest-facing title.
-- Migration version: 0017

BEGIN;

ALTER TABLE person_coupons
    ADD COLUMN IF NOT EXISTS coupon_title VARCHAR(255) NULL;

COMMIT;
