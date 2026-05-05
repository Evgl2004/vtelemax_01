-- Performance indexes for SAGUR snapshot/delta extraction.
-- These indexes support filtering/sorting used by integration API.

CREATE INDEX IF NOT EXISTS ix_person_platform_states_updated_at_person_id_platform
    ON person_platform_states(updated_at, person_id, platform);

CREATE INDEX IF NOT EXISTS ix_platform_accounts_created_at_person_id_platform
    ON platform_accounts(created_at, person_id, platform);

CREATE INDEX IF NOT EXISTS ix_platform_accounts_person_id_platform
    ON platform_accounts(person_id, platform);
