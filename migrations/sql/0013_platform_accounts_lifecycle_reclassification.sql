-- Корректировка инициализации lifecycle-статусов платформенных аккаунтов.
-- Версия миграции: 0013

BEGIN;

-- Подстраховка на случай частичного применения предыдущих миграций.
ALTER TABLE platform_accounts
    ADD COLUMN IF NOT EXISTS lifecycle_status VARCHAR(32);

-- VK: до запуска strong-проверки все аккаунты в ожидании верификации.
UPDATE platform_accounts
SET lifecycle_status = 'pending_verification'
WHERE platform = 'vk';

-- MAX: рабочий канал, все связи считаем активными.
UPDATE platform_accounts
SET lifecycle_status = 'active'
WHERE platform = 'max';

-- TG: сначала считаем все связи историческими.
UPDATE platform_accounts
SET lifecycle_status = 'historical'
WHERE platform = 'telegram';

-- TG: для персон с фактом регистрации выбираем один актуальный аккаунт (последний по времени).
WITH tg_ranked_candidates AS (
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
FROM tg_ranked_candidates AS c
WHERE pa.account_id = c.account_id
  AND c.rn = 1;

-- Финальная нормализация: пустых статусов быть не должно.
UPDATE platform_accounts
SET lifecycle_status = 'active'
WHERE lifecycle_status IS NULL;

COMMIT;
