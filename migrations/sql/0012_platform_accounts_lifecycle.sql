-- Добавление lifecycle-статусов платформенных аккаунтов.
-- Версия миграции: 0012

BEGIN;

ALTER TABLE platform_accounts
    ADD COLUMN IF NOT EXISTS lifecycle_status VARCHAR(32);

WITH ranked_accounts AS (
    SELECT
        account_id,
        platform,
        ROW_NUMBER() OVER (
            PARTITION BY person_id, platform
            ORDER BY created_at DESC, account_id DESC
        ) AS rn
    FROM platform_accounts
)
UPDATE platform_accounts AS pa
SET lifecycle_status = CASE
    WHEN ranked_accounts.platform = 'vk' THEN 'pending_verification'
    WHEN ranked_accounts.rn = 1 THEN 'active'
    ELSE 'historical'
END
FROM ranked_accounts
WHERE pa.account_id = ranked_accounts.account_id
  AND pa.lifecycle_status IS NULL;

ALTER TABLE platform_accounts
    ALTER COLUMN lifecycle_status SET DEFAULT 'active';

UPDATE platform_accounts
SET lifecycle_status = 'active'
WHERE lifecycle_status IS NULL;

ALTER TABLE platform_accounts
    ALTER COLUMN lifecycle_status SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_platform_accounts_person_id_platform_lifecycle
    ON platform_accounts(person_id, platform, lifecycle_status);

CREATE UNIQUE INDEX IF NOT EXISTS ux_platform_accounts_one_active_per_person_platform
    ON platform_accounts(person_id, platform)
    WHERE lifecycle_status = 'active';

COMMIT;
