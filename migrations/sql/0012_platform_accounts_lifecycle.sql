-- Добавление lifecycle-статусов платформенных аккаунтов (однократная инициализация).
-- Версия миграции: 0012

BEGIN;

ALTER TABLE platform_accounts
    ADD COLUMN IF NOT EXISTS lifecycle_status VARCHAR(32);

-- Базовая безопасная инициализация: все аккаунты исторические.
UPDATE platform_accounts
SET lifecycle_status = 'historical';

-- VK: до запуска strong-подтверждения номера все связи в ожидании верификации.
UPDATE platform_accounts
SET lifecycle_status = 'pending_verification'
WHERE platform = 'vk';

-- MAX: на персону оставляем ровно один активный аккаунт (самый новый).
WITH ranked_max_accounts AS (
    SELECT
        account_id,
        ROW_NUMBER() OVER (
            PARTITION BY person_id
            ORDER BY created_at DESC, account_id DESC
        ) AS rn
    FROM platform_accounts
    WHERE platform = 'max'
)
UPDATE platform_accounts AS pa
SET lifecycle_status = 'active'
FROM ranked_max_accounts AS ranked
WHERE pa.account_id = ranked.account_id
  AND ranked.rn = 1;

-- Telegram: активным считаем только один аккаунт у персон,
-- у которых в person_platform_states зафиксирован факт регистрации.
WITH ranked_telegram_registered AS (
    SELECT
        pa.account_id,
        ROW_NUMBER() OVER (
            PARTITION BY pa.person_id
            ORDER BY pa.created_at DESC, pa.account_id DESC
        ) AS rn
    FROM platform_accounts AS pa
    JOIN person_platform_states AS pps
      ON pps.person_id = pa.person_id
     AND pps.platform = 'telegram'
    WHERE pa.platform = 'telegram'
      AND pps.registered_at IS NOT NULL
)
UPDATE platform_accounts AS pa
SET lifecycle_status = 'active'
FROM ranked_telegram_registered AS ranked
WHERE pa.account_id = ranked.account_id
  AND ranked.rn = 1;

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
