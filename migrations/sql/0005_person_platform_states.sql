-- Выделение платформенного состояния регистрации в отдельную таблицу.
-- Версия миграции: 0005

BEGIN;

CREATE TABLE IF NOT EXISTS person_platform_states (
    person_id UUID NOT NULL REFERENCES persons(person_id) ON DELETE CASCADE,
    platform VARCHAR(16) NOT NULL,
    rules_accepted BOOLEAN NOT NULL DEFAULT FALSE,
    rules_accepted_at TIMESTAMPTZ NULL,
    notifications_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    notifications_allowed_at TIMESTAMPTZ NULL,
    is_registered BOOLEAN NOT NULL DEFAULT FALSE,
    registered_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_person_platform_states PRIMARY KEY (person_id, platform),
    CONSTRAINT ck_person_platform_states_platform_allowed
        CHECK (platform IN ('telegram', 'vk', 'max'))
);

CREATE INDEX IF NOT EXISTS ix_person_platform_states_person_id
    ON person_platform_states(person_id);

CREATE INDEX IF NOT EXISTS ix_person_platform_states_platform
    ON person_platform_states(platform);

INSERT INTO person_platform_states (
    person_id,
    platform,
    rules_accepted,
    rules_accepted_at,
    notifications_allowed,
    notifications_allowed_at,
    is_registered,
    registered_at
)
SELECT
    person_id,
    'telegram',
    COALESCE(rules_accepted_tg, FALSE),
    rules_accepted_tg_at,
    COALESCE(notifications_allowed_tg, FALSE),
    notifications_allowed_tg_at,
    CASE
        WHEN is_registered = TRUE
             AND COALESCE(rules_accepted_tg, FALSE) = TRUE
             AND notifications_allowed_tg_at IS NOT NULL
        THEN TRUE
        ELSE FALSE
    END,
    CASE
        WHEN is_registered = TRUE
             AND COALESCE(rules_accepted_tg, FALSE) = TRUE
             AND notifications_allowed_tg_at IS NOT NULL
        THEN notifications_allowed_tg_at
        ELSE NULL
    END
FROM persons
ON CONFLICT (person_id, platform) DO UPDATE
SET
    rules_accepted = CASE WHEN EXCLUDED.rules_accepted = TRUE THEN TRUE ELSE person_platform_states.rules_accepted END,
    rules_accepted_at = COALESCE(person_platform_states.rules_accepted_at, EXCLUDED.rules_accepted_at),
    notifications_allowed = CASE WHEN EXCLUDED.notifications_allowed = TRUE THEN TRUE ELSE person_platform_states.notifications_allowed END,
    notifications_allowed_at = COALESCE(person_platform_states.notifications_allowed_at, EXCLUDED.notifications_allowed_at),
    is_registered = CASE WHEN EXCLUDED.is_registered = TRUE THEN TRUE ELSE person_platform_states.is_registered END,
    registered_at = COALESCE(person_platform_states.registered_at, EXCLUDED.registered_at);

INSERT INTO person_platform_states (
    person_id,
    platform,
    rules_accepted,
    rules_accepted_at,
    notifications_allowed,
    notifications_allowed_at,
    is_registered,
    registered_at
)
SELECT
    person_id,
    'vk',
    COALESCE(rules_accepted_vk, FALSE),
    rules_accepted_vk_at,
    COALESCE(notifications_allowed_vk, FALSE),
    notifications_allowed_vk_at,
    CASE
        WHEN is_registered = TRUE
             AND COALESCE(rules_accepted_vk, FALSE) = TRUE
             AND notifications_allowed_vk_at IS NOT NULL
        THEN TRUE
        ELSE FALSE
    END,
    CASE
        WHEN is_registered = TRUE
             AND COALESCE(rules_accepted_vk, FALSE) = TRUE
             AND notifications_allowed_vk_at IS NOT NULL
        THEN notifications_allowed_vk_at
        ELSE NULL
    END
FROM persons
ON CONFLICT (person_id, platform) DO UPDATE
SET
    rules_accepted = CASE WHEN EXCLUDED.rules_accepted = TRUE THEN TRUE ELSE person_platform_states.rules_accepted END,
    rules_accepted_at = COALESCE(person_platform_states.rules_accepted_at, EXCLUDED.rules_accepted_at),
    notifications_allowed = CASE WHEN EXCLUDED.notifications_allowed = TRUE THEN TRUE ELSE person_platform_states.notifications_allowed END,
    notifications_allowed_at = COALESCE(person_platform_states.notifications_allowed_at, EXCLUDED.notifications_allowed_at),
    is_registered = CASE WHEN EXCLUDED.is_registered = TRUE THEN TRUE ELSE person_platform_states.is_registered END,
    registered_at = COALESCE(person_platform_states.registered_at, EXCLUDED.registered_at);

INSERT INTO person_platform_states (
    person_id,
    platform,
    rules_accepted,
    rules_accepted_at,
    notifications_allowed,
    notifications_allowed_at,
    is_registered,
    registered_at
)
SELECT
    person_id,
    'max',
    COALESCE(rules_accepted_max, FALSE),
    rules_accepted_max_at,
    COALESCE(notifications_allowed_max, FALSE),
    notifications_allowed_max_at,
    CASE
        WHEN is_registered = TRUE
             AND COALESCE(rules_accepted_max, FALSE) = TRUE
             AND notifications_allowed_max_at IS NOT NULL
        THEN TRUE
        ELSE FALSE
    END,
    CASE
        WHEN is_registered = TRUE
             AND COALESCE(rules_accepted_max, FALSE) = TRUE
             AND notifications_allowed_max_at IS NOT NULL
        THEN notifications_allowed_max_at
        ELSE NULL
    END
FROM persons
ON CONFLICT (person_id, platform) DO UPDATE
SET
    rules_accepted = CASE WHEN EXCLUDED.rules_accepted = TRUE THEN TRUE ELSE person_platform_states.rules_accepted END,
    rules_accepted_at = COALESCE(person_platform_states.rules_accepted_at, EXCLUDED.rules_accepted_at),
    notifications_allowed = CASE WHEN EXCLUDED.notifications_allowed = TRUE THEN TRUE ELSE person_platform_states.notifications_allowed END,
    notifications_allowed_at = COALESCE(person_platform_states.notifications_allowed_at, EXCLUDED.notifications_allowed_at),
    is_registered = CASE WHEN EXCLUDED.is_registered = TRUE THEN TRUE ELSE person_platform_states.is_registered END,
    registered_at = COALESCE(person_platform_states.registered_at, EXCLUDED.registered_at);

COMMIT;
