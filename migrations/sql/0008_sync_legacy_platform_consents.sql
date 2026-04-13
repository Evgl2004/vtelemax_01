-- Synchronizes legacy per-platform consent fields in `persons`
-- from canonical `person_platform_states` rows.
-- Migration version: 0008

BEGIN;

UPDATE persons AS p
SET
    rules_accepted_tg = COALESCE((
        SELECT s.rules_accepted
        FROM person_platform_states AS s
        WHERE s.person_id = p.person_id
          AND s.platform = 'telegram'
    ), p.rules_accepted_tg),
    rules_accepted_tg_at = COALESCE((
        SELECT s.rules_accepted_at
        FROM person_platform_states AS s
        WHERE s.person_id = p.person_id
          AND s.platform = 'telegram'
    ), p.rules_accepted_tg_at),
    notifications_allowed_tg = COALESCE((
        SELECT s.notifications_allowed
        FROM person_platform_states AS s
        WHERE s.person_id = p.person_id
          AND s.platform = 'telegram'
    ), p.notifications_allowed_tg),
    notifications_allowed_tg_at = COALESCE((
        SELECT s.notifications_allowed_at
        FROM person_platform_states AS s
        WHERE s.person_id = p.person_id
          AND s.platform = 'telegram'
    ), p.notifications_allowed_tg_at),

    rules_accepted_vk = COALESCE((
        SELECT s.rules_accepted
        FROM person_platform_states AS s
        WHERE s.person_id = p.person_id
          AND s.platform = 'vk'
    ), p.rules_accepted_vk),
    rules_accepted_vk_at = COALESCE((
        SELECT s.rules_accepted_at
        FROM person_platform_states AS s
        WHERE s.person_id = p.person_id
          AND s.platform = 'vk'
    ), p.rules_accepted_vk_at),
    notifications_allowed_vk = COALESCE((
        SELECT s.notifications_allowed
        FROM person_platform_states AS s
        WHERE s.person_id = p.person_id
          AND s.platform = 'vk'
    ), p.notifications_allowed_vk),
    notifications_allowed_vk_at = COALESCE((
        SELECT s.notifications_allowed_at
        FROM person_platform_states AS s
        WHERE s.person_id = p.person_id
          AND s.platform = 'vk'
    ), p.notifications_allowed_vk_at),

    rules_accepted_max = COALESCE((
        SELECT s.rules_accepted
        FROM person_platform_states AS s
        WHERE s.person_id = p.person_id
          AND s.platform = 'max'
    ), p.rules_accepted_max),
    rules_accepted_max_at = COALESCE((
        SELECT s.rules_accepted_at
        FROM person_platform_states AS s
        WHERE s.person_id = p.person_id
          AND s.platform = 'max'
    ), p.rules_accepted_max_at),
    notifications_allowed_max = COALESCE((
        SELECT s.notifications_allowed
        FROM person_platform_states AS s
        WHERE s.person_id = p.person_id
          AND s.platform = 'max'
    ), p.notifications_allowed_max),
    notifications_allowed_max_at = COALESCE((
        SELECT s.notifications_allowed_at
        FROM person_platform_states AS s
        WHERE s.person_id = p.person_id
          AND s.platform = 'max'
    ), p.notifications_allowed_max_at),

    is_registered = COALESCE((
        SELECT BOOL_OR(s.is_registered)
        FROM person_platform_states AS s
        WHERE s.person_id = p.person_id
    ), p.is_registered);

COMMIT;
