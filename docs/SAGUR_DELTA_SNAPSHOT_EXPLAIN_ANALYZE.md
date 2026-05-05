# Артефакт EXPLAIN ANALYZE: SAGUR `snapshot` / `delta`

Документ фиксирует фактические планы выполнения PostgreSQL для API-интеграции SAGUR.

## 1. Контекст проверки

- Дата проверки: `__FILL_DATE__`
- Среда: `__FILL_ENV__` (`staging`/`prod`)
- Размер данных:
  - `platform_accounts`: `__FILL_COUNT__`
  - `person_platform_states`: `__FILL_COUNT__`
  - `phones`: `__FILL_COUNT__`
- Версия PostgreSQL: `__FILL_VERSION__`

## 2. Обязательные индексы

Проверить наличие:

```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname IN (
    'ix_person_platform_states_updated_at_person_id_platform',
    'ix_platform_accounts_created_at_person_id_platform',
    'ix_platform_accounts_person_id_platform'
  )
ORDER BY indexname;
```

Ожидаемо: 3 строки.

## 3. EXPLAIN ANALYZE: snapshot limit=1000

```sql
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
WITH ranked_accounts AS (
    SELECT
        pa.person_id,
        pa.platform,
        pa.external_id,
        pa.created_at AS account_created_at,
        row_number() OVER (
            PARTITION BY pa.person_id, pa.platform
            ORDER BY pa.created_at DESC, pa.account_id DESC
        ) AS row_rank
    FROM platform_accounts pa
),
resolved_accounts AS (
    SELECT
        person_id,
        platform,
        external_id,
        account_created_at
    FROM ranked_accounts
    WHERE row_rank = 1
),
enriched AS (
    SELECT
        ra.person_id::text AS person_id,
        ph.phone_e164,
        ra.platform,
        ra.external_id,
        COALESCE(ps.rules_accepted, false) AS rules_accepted,
        COALESCE(ps.notifications_allowed, false) AS notifications_allowed,
        COALESCE(ps.is_registered, false) AS is_registered,
        ps.updated_at AS state_updated_at,
        ra.account_created_at,
        GREATEST(COALESCE(ps.updated_at, ra.account_created_at), ra.account_created_at) AS effective_updated_at
    FROM resolved_accounts ra
    JOIN phones ph ON ph.person_id = ra.person_id
    LEFT JOIN person_platform_states ps
      ON ps.person_id = ra.person_id
     AND ps.platform = ra.platform
)
SELECT
    person_id,
    phone_e164,
    platform,
    external_id,
    rules_accepted,
    notifications_allowed,
    is_registered,
    state_updated_at,
    account_created_at,
    effective_updated_at
FROM enriched
ORDER BY account_created_at ASC, person_id ASC, platform ASC
LIMIT 1001;
```

Результат (вставить полный вывод):

```text
__PASTE_EXPLAIN_ANALYZE_SNAPSHOT_OUTPUT__
```

Ключевые метрики:

- Planning Time: `__FILL_MS__`
- Execution Time: `__FILL_MS__`
- Buffers shared hit/read: `__FILL__`
- Признаки full scan: `__FILL_YES_NO__`

## 4. EXPLAIN ANALYZE: delta since=<recent> limit=1000

`<recent>` выбрать как реальный watermark из последних рабочих интеграционных запусков.

```sql
EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
WITH ranked_accounts AS (
    SELECT
        pa.person_id,
        pa.platform,
        pa.external_id,
        pa.created_at AS account_created_at,
        row_number() OVER (
            PARTITION BY pa.person_id, pa.platform
            ORDER BY pa.created_at DESC, pa.account_id DESC
        ) AS row_rank
    FROM platform_accounts pa
),
resolved_accounts AS (
    SELECT
        person_id,
        platform,
        external_id,
        account_created_at
    FROM ranked_accounts
    WHERE row_rank = 1
),
enriched AS (
    SELECT
        ra.person_id::text AS person_id,
        ph.phone_e164,
        ra.platform,
        ra.external_id,
        COALESCE(ps.rules_accepted, false) AS rules_accepted,
        COALESCE(ps.notifications_allowed, false) AS notifications_allowed,
        COALESCE(ps.is_registered, false) AS is_registered,
        ps.updated_at AS state_updated_at,
        ra.account_created_at,
        GREATEST(COALESCE(ps.updated_at, ra.account_created_at), ra.account_created_at) AS effective_updated_at
    FROM resolved_accounts ra
    JOIN phones ph ON ph.person_id = ra.person_id
    LEFT JOIN person_platform_states ps
      ON ps.person_id = ra.person_id
     AND ps.platform = ra.platform
)
SELECT
    person_id,
    phone_e164,
    platform,
    external_id,
    rules_accepted,
    notifications_allowed,
    is_registered,
    state_updated_at,
    account_created_at,
    effective_updated_at
FROM enriched
WHERE (
    (state_updated_at IS NOT NULL AND state_updated_at > TIMESTAMPTZ '__FILL_SINCE__')
    OR account_created_at > TIMESTAMPTZ '__FILL_SINCE__'
)
ORDER BY effective_updated_at ASC, person_id ASC, platform ASC
LIMIT 1001;
```

Результат (вставить полный вывод):

```text
__PASTE_EXPLAIN_ANALYZE_DELTA_OUTPUT__
```

Ключевые метрики:

- Planning Time: `__FILL_MS__`
- Execution Time: `__FILL_MS__`
- Buffers shared hit/read: `__FILL__`
- Признаки full scan: `__FILL_YES_NO__`

## 5. Вывод по производительности

- `snapshot`: `__FILL_CONCLUSION__`
- `delta`: `__FILL_CONCLUSION__`
- Оценка SLA/p95: `__FILL_CONCLUSION__`
- Нужны доп. индексы/тюнинг: `__FILL_CONCLUSION__`

## 6. Команда запуска в контейнере postgres

```bash
sudo docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

