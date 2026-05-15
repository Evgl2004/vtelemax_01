-- SAGUR coupons: allow late redemption status after campaign close.
-- Migration version: 0015

BEGIN;

ALTER TABLE person_coupons
    DROP CONSTRAINT IF EXISTS ck_person_coupons_status_allowed;

ALTER TABLE person_coupons
    ADD CONSTRAINT ck_person_coupons_status_allowed
        CHECK (
            status IN (
                'reserved',
                'sent',
                'used',
                'used_after_campaign',
                'expired',
                'canceled',
                'error'
            )
        );

COMMIT;
