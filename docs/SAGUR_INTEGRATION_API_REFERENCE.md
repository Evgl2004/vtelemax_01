# SAGUR Integration API: Техническая документация

## 1. Назначение

Сервис предоставляет **read-only REST API** для внешней системы SAGUR:

- полная выгрузка получателей (`snapshot`);
- инкрементальная выгрузка изменений (`delta`).

Сервис не изменяет данные в `vtelemax`, только читает PostgreSQL.

---

## 2. Архитектура и доступ

## 2.1 Компоненты

- `sagur-integration-api` — backend API (aiohttp), контейнер внутри docker-сети.
- `nginx` — внешний вход, TLS, IP allowlist, rate-limit, proxy в `sagur-integration-api`.

## 2.2 Публичные URL

- `GET /internal/integration/v1/sagur/recipients/snapshot`
- `GET /internal/integration/v1/sagur/recipients/delta`
- `GET /metrics` (служебный endpoint метрик, Prometheus text format)

Базовый host (prod): `https://sobalbot.24vds.ru`

## 2.3 Ограничения доступа

1. IP allowlist на уровне `nginx` (`SAGUR_INTEGRATION_IP_ALLOWLIST`).
2. HMAC-подпись запроса на уровне приложения (`X-Sagur-Timestamp`, `X-Sagur-Signature`).
3. Rate limit на уровне `nginx` (`SAGUR_INTEGRATION_RATE_LIMIT_RPM`).

---

## 3. Переменные окружения

## 3.1 Переменные сервиса `sagur-integration-api`

| Переменная | Обязательность | Назначение | Пример |
|---|---|---|---|
| `SAGUR_INTEGRATION_API_ENABLED` | да | Включение сервиса (`true/false`) | `true` |
| `SAGUR_INTEGRATION_SERVICE_HOST` | да | Host bind внутри контейнера | `0.0.0.0` |
| `SAGUR_INTEGRATION_SERVICE_PORT` | да | Порт backend API | `8086` |
| `SAGUR_INTEGRATION_DEFAULT_LIMIT` | да | `limit` по умолчанию | `1000` |
| `SAGUR_INTEGRATION_MAX_LIMIT` | да | Максимальный `limit` | `5000` |
| `SAGUR_INTEGRATION_HMAC_SECRET` | да | Секрет HMAC подписи | `...` |
| `SAGUR_INTEGRATION_HMAC_MAX_SKEW_SECONDS` | да | Окно валидности timestamp | `60` |

## 3.2 Переменные `nginx`

| Переменная | Обязательность | Назначение | Пример |
|---|---|---|---|
| `SAGUR_INTEGRATION_IP_ALLOWLIST` | да | Список IP/CIDR через запятую | `31.148.148.177,10.0.0.0/24` |
| `SAGUR_INTEGRATION_RATE_LIMIT_RPM` | да | Лимит запросов в минуту на IP | `60` |
| `SAGUR_INTEGRATION_SERVICE_PORT` | да | Порт backend API для proxy | `8086` |

---

## 4. Авторизация HMAC (обязательно)

## 4.1 Заголовки

- `X-Sagur-Timestamp`: Unix timestamp (секунды)
- `X-Sagur-Signature`: hex(HMAC-SHA256)
- `X-Request-Id`: опционально (для трассировки)

## 4.2 Canonical payload (точный формат)

```text
<HTTP_METHOD_UPPER>
<PATH_WITH_QUERY>
<TIMESTAMP>
```

Пример:

```text
GET
/internal/integration/v1/sagur/recipients/snapshot?limit=2
1714900000
```

Подпись:

```text
signature = hex(hmac_sha256(SAGUR_INTEGRATION_HMAC_SECRET, payload))
```

---

## 5. Endpoint: Snapshot

`GET /internal/integration/v1/sagur/recipients/snapshot`

## 5.1 Query параметры

| Параметр | Тип | Обязателен | Описание |
|---|---|---|---|
| `limit` | int | нет | Кол-во строк на страницу. По умолчанию `SAGUR_INTEGRATION_DEFAULT_LIMIT`, максимум `SAGUR_INTEGRATION_MAX_LIMIT`. |
| `cursor` | string | нет | Signed opaque cursor для следующей страницы (`payload.signature`). |

## 5.2 Пример запроса

```bash
SAGUR_HOST="https://sobalbot.24vds.ru"
SAGUR_SECRET="REPLACE_WITH_REAL_SECRET"
PATH_QS="/internal/integration/v1/sagur/recipients/snapshot?limit=2"
TS=$(date +%s)
PAYLOAD="GET
${PATH_QS}
${TS}"
SIG=$(printf "%s" "$PAYLOAD" | openssl dgst -sha256 -hmac "$SAGUR_SECRET" -hex | sed 's/^.* //')

curl -sS -i "${SAGUR_HOST}${PATH_QS}" \
  -H "X-Sagur-Timestamp: ${TS}" \
  -H "X-Sagur-Signature: ${SIG}"
```

## 5.3 Пример ответа (200)

```json
{
  "items": [
    {
      "person_id": "ba933058-a3ea-402e-8a0e-c0d7c51f278f",
      "phone_e164": "+79224800001",
      "platform": "telegram",
      "external_id": "113703",
      "rules_accepted": false,
      "notifications_allowed": false,
      "is_registered": false,
      "registered_at": null,
      "state_updated_at": "2026-04-13T02:10:52.642922Z",
      "account_created_at": "2026-04-13T02:10:52.642922Z"
    }
  ],
  "next_cursor": "eyJ...snip...",
  "generated_at": "2026-05-05T06:03:24.633551Z"
}
```

---

## 6. Endpoint: Delta

`GET /internal/integration/v1/sagur/recipients/delta`

## 6.1 Query параметры

| Параметр | Тип | Обязателен | Описание |
|---|---|---|---|
| `since` | RFC3339 UTC | да | Нижняя граница инкремента (строго `>`). |
| `limit` | int | нет | Кол-во строк на страницу. |
| `cursor` | string | нет | Signed opaque cursor следующей страницы (`payload.signature`). |

Важно:

- если передан `cursor`, поле `since` в query должно совпадать с `since`, который закодирован в cursor;
- если передан `cursor`, поле `limit` в query должно совпадать с `limit` внутри cursor;
- иначе вернется `400`.

## 6.2 Пример запроса

```bash
SAGUR_HOST="https://sobalbot.24vds.ru"
SAGUR_SECRET="REPLACE_WITH_REAL_SECRET"
SINCE="2026-05-01T00:00:00Z"
PATH_QS="/internal/integration/v1/sagur/recipients/delta?since=${SINCE}&limit=2"
TS=$(date +%s)
PAYLOAD="GET
${PATH_QS}
${TS}"
SIG=$(printf "%s" "$PAYLOAD" | openssl dgst -sha256 -hmac "$SAGUR_SECRET" -hex | sed 's/^.* //')

curl -sS -i "${SAGUR_HOST}${PATH_QS}" \
  -H "X-Sagur-Timestamp: ${TS}" \
  -H "X-Sagur-Signature: ${SIG}"
```

## 6.3 Пример ответа (200)

```json
{
  "items": [
    {
      "person_id": "f3c8d28e-5032-41c1-a37c-175fc41c8033",
      "phone_e164": "+79859709371",
      "platform": "max",
      "external_id": "4239565",
      "rules_accepted": true,
      "notifications_allowed": true,
      "is_registered": true,
      "registered_at": "2026-05-01T06:03:52.325334Z",
      "state_updated_at": "2026-05-01T06:03:52.325334Z",
      "account_created_at": "2026-05-01T06:03:39.899978Z",
      "effective_updated_at": "2026-05-01T06:03:52.325334Z",
      "profile": {
        "first_name": "Иван",
        "last_name": "Иванов",
        "gender": "male",
        "email": "ivan@example.com",
        "birthdate": "1991-05-17"
      }
    }
  ],
  "next_cursor": "eyJ...snip...",
  "max_seen_updated_at": "2026-05-01T09:08:28.821253Z",
  "generated_at": "2026-05-05T06:03:25.044941Z"
}
```

---

## 7. Поля `items[]`

| Поле | Тип | Описание |
|---|---|---|
| `person_id` | UUID string | Идентификатор персоны в vtelemax |
| `phone_e164` | string | Телефон в формате E.164 |
| `platform` | enum | `telegram` \| `vk` \| `max` |
| `external_id` | string \| null | Идентификатор пользователя в платформе |
| `rules_accepted` | bool | Согласие с правилами по платформе |
| `notifications_allowed` | bool | Согласие на рассылку по платформе |
| `is_registered` | bool | Признак завершенной регистрации по платформе |
| `registered_at` | RFC3339 UTC \| null | Первая зафиксированная дата завершения регистрации по платформе (`person_platform_states.registered_at`) |
| `state_updated_at` | RFC3339 UTC \| null | Время обновления платформенного state |
| `account_created_at` | RFC3339 UTC \| null | Время создания платформенного аккаунта |
| `effective_updated_at` | RFC3339 UTC \| null | Используется в `delta`: `greatest(coalesce(state_updated_at, account_created_at), account_created_at, profile_updated_at)` |
| `profile.first_name` | string \| null | Имя гостя |
| `profile.last_name` | string \| null | Фамилия гостя |
| `profile.gender` | string \| null | Пол |
| `profile.email` | string \| null | Email |
| `profile.birthdate` | `YYYY-MM-DD` \| null | Дата рождения |

---

## 8. Логика пагинации и сортировки

## 8.0 Выбор `external_id` по lifecycle-политике

- `telegram` / `max`: выбирается только аккаунт с `lifecycle_status = active`;
- `vk`: по умолчанию только `active`;
- `vk`: при `SAGUR_INCLUDE_VK_PENDING_VERIFICATION=true` допускается fallback в `pending_verification`;
- `historical` никогда не участвует в выгрузке.

## 8.1 Snapshot

- сортировка: `account_created_at`, `person_id`, `platform` (ASC);
- cursor продолжает чтение строго после последней записи страницы.

## 8.2 Delta

- строка попадает в delta, если `effective_updated_at > since`;
- сортировка: `effective_updated_at`, `person_id`, `platform` (ASC);
- `effective_updated_at = greatest(coalesce(state_updated_at, account_created_at), account_created_at, profile_updated_at)`.

## 8.3 Cursor hardening

- курсор подписывается HMAC (`payload.signature`);
- подпись курсора проверяется до SQL-выборки;
- tampered cursor отклоняется с `400`;
- курсор хранит `limit`, и `limit` в query обязан совпадать с `limit` внутри cursor.

---

## 8.4 Индексы для производительности

Для запросов `snapshot/delta` в БД должны быть применены индексы:

- `ix_person_platform_states_updated_at_person_id_platform`
  - таблица: `person_platform_states(updated_at, person_id, platform)`
- `ix_platform_accounts_created_at_person_id_platform`
  - таблица: `platform_accounts(created_at, person_id, platform)`
- `ix_platform_accounts_person_id_platform`
  - таблица: `platform_accounts(person_id, platform)`

Миграция: `migrations/sql/0011_sagur_delta_snapshot_indexes.sql`.

---

## 9. Коды ответов и ошибки

| HTTP | Причина | Пример |
|---|---|---|
| `200` | Успех | Корректный HMAC и параметры |
| `400` | Ошибка параметров | Некорректный `limit`, пустой/невалидный `since`, конфликт `since/limit` с cursor, поврежденный cursor |
| `401` | Ошибка авторизации | Неверная подпись или просроченный timestamp |
| `403` | Блокировка на `nginx` | IP не в allowlist |
| `426` | HTTP bootstrap mode | TLS еще не активирован, для SAGUR endpoint требуется HTTPS |
| `503` | Сервис не готов | Не задан HMAC секрет в env |

Формат ошибок приложения:

```json
{
  "status": "error",
  "message": "Текст ошибки"
}
```

---

## 10. Проверка работоспособности

## 10.1 Проверка контейнеров

```bash
sudo docker compose ps
```

Ожидаемо должны быть `Up`:

- `nginx`
- `sagur-integration-api`
- `postgres`

## 10.2 Health backend (изнутри docker-сети)

```bash
sudo docker compose exec nginx sh -lc "wget -qO- http://sagur-integration-api:8086/health"
```

Ожидаемый ответ:

```json
{"status":"ok","service":"sagur-integration-api"}
```

## 10.3 Проверка endpoint метрик

```bash
sudo docker compose exec nginx sh -lc "wget -qO- http://sagur-integration-api:8086/metrics | head -n 20"
```

Ожидается текст с метриками:

- `sagur_integration_requests_total`
- `sagur_integration_request_latency_seconds_sum`
- `sagur_integration_request_latency_seconds_count`
- `sagur_integration_rows_returned_total`
- `sagur_integration_auth_failures_total`

## 10.4 Аудит-логи сервиса

```bash
sudo docker compose logs --tail=120 sagur-integration-api
```

Искать записи `stage=integration_audit` со статусами и latency.

---

## 11. Диагностика типовых проблем

## 11.1 `403 Forbidden`

Причина: клиентский IP не входит в `SAGUR_INTEGRATION_IP_ALLOWLIST`.

Проверка:

```bash
sudo docker compose logs --tail=120 nginx | grep -E "internal/integration/v1/sagur|forbidden"
```

## 11.2 `401` (подпись)

Проверить:

1. timestamp в секундах UTC;
2. canonical payload строго в формате:
   - `METHOD`
   - `PATH_WITH_QUERY`
   - `TIMESTAMP`
3. тот же секрет, что в `SAGUR_INTEGRATION_HMAC_SECRET`.

## 11.3 `400` по `since`/`cursor`

- `since` обязателен для `delta`;
- если передан cursor, `since` в query должен совпасть с `since` внутри cursor;
- `limit` > max вызывает `400`.

---

## 12. Что передавать команде SAGUR для реализации клиента

1. Host: `https://sobalbot.24vds.ru`
2. Endpoint’ы:
   - `/internal/integration/v1/sagur/recipients/snapshot`
   - `/internal/integration/v1/sagur/recipients/delta`
3. Схема HMAC из раздела 4 (без body-hash, без key-id).
4. Рекомендуемый процесс:
   - один раз пройти `snapshot` до `next_cursor=null`;
   - далее регулярно вызывать `delta` с фиксированным `since`;
   - при пагинации `delta` передавать тот же `since`, что и у первого запроса страницы;
   - после полного цикла сохранять `max_seen_updated_at` как новый watermark.
