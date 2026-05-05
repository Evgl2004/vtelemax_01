# SAGUR Integration API: Release Checklist

## 1. Что реализовано

- `snapshot` endpoint с детерминированной пагинацией по ключу:
  - `account_created_at ASC`
  - `person_id ASC`
  - `platform ASC`
- `delta` endpoint с детерминированной пагинацией по ключу:
  - `effective_updated_at ASC`
  - `person_id ASC`
  - `platform ASC`
- Отбор `delta`:
  - `person_platform_states.updated_at > since`
  - или `platform_accounts.created_at > since`
- HMAC-аутентификация запроса (`X-Sagur-Timestamp`, `X-Sagur-Signature`).
- Cursor hardening:
  - signed cursor (`payload.signature`);
  - проверка подписи до SQL;
  - `limit` в cursor, контроль совпадения с query.
- Расширение ответа `delta`:
  - поле `effective_updated_at` в `items[]`.
- Метрики `/metrics` в формате Prometheus.
- Индексы производительности:
  - `person_platform_states(updated_at, person_id, platform)`
  - `platform_accounts(created_at, person_id, platform)`
  - `platform_accounts(person_id, platform)`

## 2. Предпрод-проверка (локально/стенд)

1. Запустить/пересобрать сервисы:
   - `sudo docker compose up -d --build`
2. Проверить контейнеры:
   - `sudo docker compose ps`
3. Проверить backend health:
   - `sudo docker compose exec nginx sh -lc "wget -qO- http://sagur-integration-api:8086/health"`
4. Проверить публичный HMAC доступ:
   - выполнить `tmp_test_sagur_hmac.sh` или эквивалентный curl (подписанный).
5. Проверить метрики:
   - `sudo docker compose exec nginx sh -lc "wget -qO- http://sagur-integration-api:8086/metrics | head -n 20"`
6. Проверить audit-логи:
   - `sudo docker compose logs --tail=200 sagur-integration-api`

## 3. Тесты (репозиторий)

1. Unit:
   - `powershell -ExecutionPolicy Bypass -File scripts/run_pytest.ps1 tests/unit/test_sagur_integration_api_app.py`
2. Integration (live Postgres):
   - `VTELEMAX_RUN_POSTGRES_LIVE_TESTS=1` и запуск:
   - `powershell -ExecutionPolicy Bypass -File scripts/run_pytest.ps1 tests/integration/test_postgres_live_sagur_integration_api.py`

## 4. Критерии готовности к передаче в SAGUR

- `snapshot` и `delta` отдают HTTP `200` на корректно подписанный запрос.
- Невалидные подписи и поврежденные cursor отвергаются.
- Контракт `delta` стабилен:
  - нет дублей/пропусков на пагинации;
  - `next_cursor` корректно продвигает страницу;
  - `max_seen_updated_at` корректен.
- На `delta` доступно поле `effective_updated_at`.
- Метрики `/metrics` доступны и читаются.
- В логах есть `request_id`, endpoint, rows, status, latency.

## 5. Что нужно подтвердить на стороне SAGUR

- Upsert-идемпотентность потребителя по ключу (`person_id`, `platform`).
- Watermark двигается только после полного успешного прохода всех страниц.
- Поддержка signed cursor (`payload.signature`) в цикле чтения.
