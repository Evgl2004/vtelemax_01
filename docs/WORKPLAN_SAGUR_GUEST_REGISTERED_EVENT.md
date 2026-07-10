# Рабочий план: событие регистрации гостя vtelemax -> SAGUR

Дата ревизии: 2026-07-09.

Статус документа: рабочая дорожная карта после сверки постановки, контракта SAGUR, текущего кода и договоренностей в обсуждении. Модель реализации уточнена: вместо двух отдельных таблиц используется единый исходящий регистр события регистрации SAGUR.

1. факты по контракту SAGUR;
2. факты по текущему коду vtelemax;
3. решения, принятые в обсуждении;
4. зафиксированные ограничения реализации;
5. этапы реализации.

## 1. Источники

1. Контракт SAGUR: `Контракт события регистрации гостя vtelemax -> SAGUR / Program-Loyal`.
2. Постановка задачи: `Привет. Работаем над проектом vtelemax...`.
3. Текущий код vtelemax:
   - `src/vtelemax/core/loyalty_use_cases.py`;
   - `src/vtelemax/core/ports.py`;
   - `src/vtelemax/infrastructure/iiko_client.py`;
   - `src/vtelemax/adapters/telegram/identity_adapter.py`;
   - `src/vtelemax/adapters/vk/identity_adapter.py`;
   - `src/vtelemax/adapters/max/identity_adapter.py`;
   - `src/vtelemax/tools/legacy_telegram_migration.py`;
   - `src/vtelemax/infrastructure/postgres/schema.py`;
   - `src/vtelemax/infrastructure/postgres/repository.py`;
   - `src/vtelemax/infrastructure/postgres/sagur_recipients_repository.py`;
   - `src/vtelemax/apps/sagur_integration_api_app.py`;
   - `src/vtelemax/settings.py`;
   - `docker-compose.yml`;
   - `scripts/run_pytest.ps1`.

## 2. Факты по контракту SAGUR

1. SAGUR принимает событие:

```text
POST https://sagur.24vds.ru/internal/integration/v1/vtelemax/registration-events
```

2. Тип события всегда:

```text
guest_registered
```

3. По контракту vtelemax должен отправлять событие, когда гость завершил регистрацию в одном из ботов:
   - Telegram;
   - VK;
   - MAX.

4. По контракту исторические гости, которые проходят новую регистрацию в текущей логике бота, также должны отправляться как `guest_registered`.
5. Все поля тела события обязательны.
6. `customerId` обязателен и означает идентификатор гостя в iikoCard.
7. `person_id` должен быть UUID профиля vtelemax.
8. `request_id` и `event_id` являются строковыми идентификаторами события/запроса; контракт не требует, чтобы они обязательно были UUID.
9. Заголовок `X-Vtelemax-Request-Id` должен совпадать с полем `request_id` в JSON.
10. Подпись HMAC строится по строке:

```text
METHOD
PATH
TIMESTAMP
SHA256(BODY)
```

11. `SHA256(BODY)` считается от фактических байтов тела HTTP-запроса.
12. Успешный прием SAGUR возвращает HTTP `202`.
13. Повтор того же `event_id` с тем же телом считается безопасным дублем.
14. HTTP `409` с кодом `event_id_payload_conflict` означает конфликт: тот же `event_id` использован с другим телом.
15. После приема события SAGUR сам проверяет, не выдавался ли приветственный купон (welcome) этому гостю ранее.

## 3. Факты по текущему коду vtelemax

1. Исходящего регистра события регистрации vtelemax -> SAGUR сейчас нет.
2. В проекте уже есть входящий API SAGUR, снимок/дельта (snapshot/delta) и купонные события SAGUR -> vtelemax.
3. `GetVirtualCardUseCase` сначала вызывает поиск гостя iikoCard по телефону.
4. Если iikoCard вернул гостя, новый гость не создается; при наличии профиля выполняется обновление через `create_or_update` с известным `customer_id`.
5. Если iikoCard не нашел гостя, `GetVirtualCardUseCase` вызывает создание гостя через `register_customer`.
6. При создании нового гостя текущий iikoCard-клиент вызывает `create_or_update` без поля `id`.
7. При обновлении существующего гостя текущий iikoCard-клиент передает поле `id = customer_id`.
8. Сейчас результат `GetVirtualCardUseCase` возвращает номера карт, но не возвращает наружу:
   - `customerId`;
   - признак, что гость был создан именно сейчас;
   - признак, что гость уже существовал в iikoCard.
9. Финальный шаг iikoCard-синхронизации находится:
   - Telegram: `TelegramIdentityAdapter._finalize_iiko_sync_step`;
   - VK: `VkIdentityAdapter._finalize_iiko_sync_step`;
   - MAX: `MaxIdentityAdapter._finalize_iiko_sync_step`.
10. В Telegram/VK/MAX флаг `is_registered=True` ставится до финального шага iikoCard-синхронизации.
11. Поэтому нельзя создавать событие только по факту `is_registered=True`.
12. Legacy-миграция Telegram из старого бота создает или допривязывает локального человека с:
   - `is_legacy=True`;
   - `is_registered=False`.
13. Новые согласия и завершенная регистрация из legacy-источника не переносятся.
14. В legacy-ветке Telegram/VK/MAX после подтверждения телефона код может выполнить дозаполнение пустых полей профиля из iikoCard через `get_customer_info`.
15. Если у найденного гостя iikoCard нет карт, текущий `GetVirtualCardUseCase` может выпустить карту. Сам выпуск карты не равен факту приветственного события.
16. В коде нет идемпотентного ключа для создания гостя iikoCard.
17. В коде нет автоматической контрольной проверки после тайм-аута создания гостя iikoCard.
18. В коде есть похожий механизм очереди и повторов: `profile_sync_queue`.
19. `profile_sync_queue` использует статусы `pending` / `processing` / `done` / `failed`, поля `attempts`, `next_attempt_at`, `locked_at`, индекс `(status, next_attempt_at)` и выборку `FOR UPDATE SKIP LOCKED`.
20. В текущем `profile_sync_queue` есть уникальность только для одного `pending`-задания на `person_id`; для нового регистра нельзя переносить эту уникальность на `customerId` или платформу.
21. В `sagur_recipients_repository.py` уже есть проверенное сопоставление полей для снимка/дельты (snapshot/delta):
   - `rules_accepted` из `person_platform_states.rules_accepted`;
   - `notifications_allowed` из `person_platform_states.notifications_allowed`;
   - `is_registered` из `person_platform_states.is_registered`;
   - `registered_at` из `person_platform_states.registered_at`;
   - `state_updated_at` из `person_platform_states.updated_at`;
   - `account_created_at` из `platform_accounts.created_at`;
   - `effective_updated_at` как максимум из состояния платформы, даты создания аккаунта и `persons.updated_at`.
22. В `platform_accounts.lifecycle_status` сейчас допустимы `active`, `pending_verification`, `historical`; для одного человека и платформы уникальность задана только на один `active`-аккаунт.
23. В снимке/дельте SAGUR (snapshot/delta) есть отдельная настройка `SAGUR_INCLUDE_VK_PENDING_VERIFICATION`; это факт текущей входящей интеграции, а не правило для нового исходящего события.

## 4. Решения, принятые в обсуждении

1. `customerId` для события SAGUR - это идентификатор гостя в iikoCard.
2. Для нового гостя `customerId` берется из ответа успешного создания гостя iikoCard.
3. Для исторического legacy-гостя `customerId` берется из iikoCard-синхронизации текущей регистрации. В проверенном коде Telegram/VK/MAX legacy-ветка после телефона, имени и согласий доходит до общего финального шага iikoCard; внутри него сначала выполняется поиск iikoCard по телефону, поэтому для уже существующего iikoCard-гостя `customerId` приходит из этого поиска.
4. VK также отправляет событие; на текущем этапе не вводим жесткую проверку статуса `active` / `pending_verification`.
5. Для подписи исходящего запроса использовать отдельный секрет, если он задан:

```env
VTELEMAX_REGISTRATION_CALLBACK_HMAC_SECRET
```

6. Если отдельный секрет пустой, использовать текущий секрет обмена SAGUR в vtelemax:

```env
SAGUR_INTEGRATION_HMAC_SECRET
```

На стороне SAGUR этому общему секрету соответствует `VTELEMAX_SYNC_HMAC_SECRET`.
7. `request_id` и `event_id` можно генерировать как UUID-строки, но хранить и валидировать как строки до 128 символов.
8. `event_id`, `request_id` и тело события должны сохраняться один раз и не меняться при повторной отправке.
9. Отправка в SAGUR должна идти через локальный исходящий регистр, а не прямым HTTP-вызовом из пользовательского сценария.
10. В обычном успешном сценарии не добавлять лишних запросов в iikoCard сверх уже существующего поиска/создания/обновления.
11. Фоновый восстановитель не должен автоматически создавать гостя в iikoCard. Он может только уточнять неизвестный результат.
12. Запись единого исходящего регистра должна создаваться или обновляться до внешнего вызова iikoCard, чтобы не потерять сам факт начатой операции.
13. Если пользователь повторяет текущий шаг после ошибки iikoCard, повтор работает с той же активной записью исходящего регистра, а не создает параллельную запись.
14. Для купонных событий SAGUR -> vtelemax остаются существующие правила и секреты текущего контура. Для исходящего welcome-callback допускается общий секрет текущего обмена: `SAGUR_INTEGRATION_HMAC_SECRET` в vtelemax соответствует `VTELEMAX_SYNC_HMAC_SECRET` на стороне SAGUR.

## 5. Правила создания события

### 5.1. Новый не-legacy гость

1. Гость завершил регистрацию в Telegram/VK/MAX.
2. iikoCard не нашел гостя по телефону.
3. vtelemax успешно создал нового гостя в iikoCard.
4. vtelemax получил `customerId`.
5. Событие `guest_registered` ставится в единый исходящий регистр SAGUR.

### 5.2. Исторический legacy-гость

1. Гость из старого бота проходит новую регистрацию в текущей логике vtelemax.
2. По проверенному коду Telegram/VK/MAX legacy-сценарий после подтверждения телефона не должен сразу ставить событие SAGUR. Он проходит оставшиеся шаги текущей регистрации и доходит до общего финального шага iikoCard.
3. На финальном шаге iikoCard текущий `GetVirtualCardUseCase` сначала ищет гостя по телефону.
4. Если iikoCard нашел гостя, `customerId` берется из найденного гостя и для `registration_origin=legacy_upgrade` событие `guest_registered` ставится в единый исходящий регистр SAGUR.
5. Если iikoCard не нашел гостя и во время этой же регистрации vtelemax создал гостя в iikoCard, `customerId` берется из ответа создания и событие также ставится в регистр.
6. Дозаполнение профиля legacy-гостя из iikoCard до финального шага остается вспомогательным чтением профиля; оно не заменяет финальную iikoCard-синхронизацию и не является самостоятельной точкой создания события SAGUR.

Это правило основано на контракте SAGUR: исторические гости, которые проходят новую регистрацию в текущей логике бота, также должны отправляться как `guest_registered`.

### 5.3. Не-legacy гость, который уже есть в iikoCard

Текущее решение обсуждения: если это не legacy-сценарий и iikoCard уже вернул существующего гостя по телефону, новый гость в iikoCard не создается и приветственное событие не создается.

Это правило нужно держать отдельно от legacy-сценария.

## 6. Зафиксированные ограничения реализации

### 6.1. Локальная идемпотентность

Для локальной защиты от повторного создания одного и того же события используется одна запись единого исходящего регистра.

Правило:

1. один проход регистрации работает с одной активной записью исходящего регистра;
2. повтор текущего шага пользователем обновляет эту же запись;
3. `event_id`, `request_id` и `payload_body` создаются один раз после получения `customerId` и дальше не меняются;
4. активная запись ищется по локальному контексту регистрации: `person_id`, `platform`, `external_id`, `registration_origin`;
5. для активных состояний нужен частичный уникальный индекс по этому локальному контексту, чтобы не плодить параллельные записи при повторе шага;
6. `event_id` имеет частичный уникальный индекс для записей, где `event_id IS NOT NULL`;
7. отдельный `business_dedup_key` не вводится, пока не появится новое явное бизнес-правило.

Нельзя догадкой выбирать уникальность по `customerId`, платформе или их комбинации.

Запись регистра, созданная до получения `customerId`, является технической записью контроля iikoCard-синхронизации. Это еще не готовое событие SAGUR: у нее не должно быть `event_id`, `request_id`, `payload_body` и `sagur_status=pending`.

### 6.2. Неизвестный результат создания iikoCard

Если vtelemax вызвал создание гостя iikoCard, но не получил ответ, запись единого исходящего регистра переводится в состояние `iiko_status=result_unknown`.

Правило:

1. автоматического повторного создания гостя фоном нет;
2. фоновый восстановитель работает только с проблемными записями регистра;
3. один проход делает не больше одного контрольного поиска в iikoCard;
4. если результат нельзя надежно квалифицировать, запись переводится в `manual_review`;
5. событие SAGUR без `customerId` не создается.

### 6.3. Граница с формулировкой контракта SAGUR

Контракт SAGUR формулирует основание широко: событие нужно при завершении регистрации в Telegram/VK/MAX, включая исторических гостей.

В обсуждении принято более узкое правило для обычного не-legacy сценария: если iikoCard уже вернул существующего гостя по телефону и новый гость в iikoCard не создан, событие не ставится.

Это зафиксировано как текущее правило проекта. При реализации нельзя самовольно расширять его до "каждая регистрация всегда создает событие"; если SAGUR будет ожидать другой бизнес-смысл, это отдельное согласование, а не техническая догадка.

## 7. Дорожная карта реализации

### Область изменений

Ожидаемые существующие файлы:

1. `src/vtelemax/settings.py` - настройки отправки, восстановления и лимитов.
2. `src/vtelemax/core/loyalty_use_cases.py` - возврат `customer_id` и признака создания/существования гостя iikoCard.
3. `src/vtelemax/core/ports.py` - порты новых репозиториев/клиента, если по текущей архитектуре они должны жить в core.
4. `src/vtelemax/infrastructure/postgres/schema.py` - ORM-таблица единого исходящего регистра SAGUR.
5. `src/vtelemax/infrastructure/postgres/repository.py` или отдельный PostgreSQL-репозиторий - операции единого исходящего регистра.
6. `src/vtelemax/adapters/telegram/identity_adapter.py` - постановка события после финального шага iikoCard.
7. `src/vtelemax/adapters/vk/identity_adapter.py` - постановка события после финального шага iikoCard.
8. `src/vtelemax/adapters/max/identity_adapter.py` - постановка события после финального шага iikoCard.
9. `docker-compose.yml` - отдельный фоновый процесс (worker), если доставка SAGUR запускается отдельным процессом по аналогии с `profile-sync-worker`.
10. `.env.example` - документирование новых переменных окружения.

Ожидаемые новые файлы:

1. `migrations/sql/00XX_sagur_guest_registration_events.sql` - миграция единого исходящего регистра.
2. `src/vtelemax/adapters/sagur_registration_events.py` - HTTP-клиент, подпись HMAC и обработка ответов SAGUR.
3. `src/vtelemax/adapters/periodic_sagur_registration_worker.py` - периодический обработчик единого исходящего регистра.
4. `src/vtelemax/apps/sagur_registration_events_worker_app.py` - точка входа фонового процесса (worker).
5. Тесты в `tests/unit` и при изменении PostgreSQL-слоя в `tests/integration`.

### Этап 1. Расширить результат iikoCard-сценария

Изменить `LoyaltyMenuResult` / результат `GetVirtualCardUseCase`, чтобы наружу возвращались:

1. `customer_id`;
2. `created_new_customer`;
3. `existing_customer_found`;
4. номера карт, как сейчас.

Критерии:

1. существующий гость iikoCard -> `customer_id` есть, `created_new_customer=false`, `existing_customer_found=true`;
2. новый созданный гость iikoCard -> `customer_id` есть, `created_new_customer=true`, `existing_customer_found=false`;
3. старый показ карт в ботах не ломается;
4. признак `created_new_customer` не вычисляется по наличию карт.

Тесты:

1. существующий гость возвращает `customer_id` и не вызывает создание;
2. новый гость возвращает `customer_id` и признак создания;
3. существующий гость с профилем обновляется с `customer_id`;
4. выпуск карты не влияет на `created_new_customer`.

Ограничение: сам `GetVirtualCardUseCase` остается общим сценарием виртуальной карты и не должен сам создавать SAGUR-событие. Он только возвращает технический результат iikoCard-синхронизации. Постановка в единый исходящий регистр выполняется только из регистрационного сценария Telegram/VK/MAX.

### Этап 2. Добавить единый исходящий регистр SAGUR

Единый регистр заменяет две сущности: отдельную таблицу iikoCard-операции и отдельную очередь отправки.

Он нужен, чтобы одной записью зафиксировать:

1. локальную регистрацию, для которой началась iikoCard-синхронизация;
2. поиск или создание гостя в iikoCard;
3. полученный `customerId` или неизвестный результат;
4. решение, нужно ли событие SAGUR;
5. неизменяемые `event_id`, `request_id` и `payload_body`;
6. состояние отправки в SAGUR.

Предлагаемая таблица:

```text
sagur_guest_registration_events
```

Минимальные поля:

1. `record_id`;
2. `person_id`;
3. `platform`;
4. `external_id`;
5. `phone_e164`;
6. `registration_origin`: `new_registration` или `legacy_upgrade`;
7. `iiko_status`;
8. `sagur_status`;
9. `customer_id`;
10. `created_new_customer`;
11. `existing_customer_found`;
12. `event_id`;
13. `request_id`;
14. `event_type`;
15. `payload_json`;
16. `payload_body`;
17. `payload_sha256`;
18. `lookup_started_at`;
19. `lookup_finished_at`;
20. `create_started_at`;
21. `iiko_response_received_at`;
22. `recovery_reason`;
23. `attempts`;
24. `next_attempt_at`;
25. `locked_at`;
26. `lock_expires_at`;
27. `last_http_status`;
28. `last_error_code`;
29. `last_error_text`;
30. `duplicate`;
31. `created_at`;
32. `updated_at`;
33. `sent_at`.

Статусы `iiko_status`:

1. `lookup_started`;
2. `create_started`;
3. `created`;
4. `existing`;
5. `result_unknown`;
6. `not_required`;
7. `manual_review`;
8. `failed_terminal`.

Статусы `sagur_status`:

1. `not_ready`;
2. `pending`;
3. `processing`;
4. `sent`;
5. `retry_scheduled`;
6. `conflict`;
7. `not_required`;
8. `manual_review`;
9. `failed_terminal`.

Активной считается запись, которая еще не дошла до терминального решения.

Терминальные значения:

1. `sagur_status=sent`;
2. `sagur_status=conflict`;
3. `sagur_status=not_required`;
4. `sagur_status=manual_review`;
5. `sagur_status=failed_terminal`.

Индексы:

1. первичный ключ `record_id`;
2. частичная уникальность `event_id`, где `event_id IS NOT NULL`;
3. частичная уникальность активной записи по `(person_id, platform, external_id, registration_origin)` для нетерминальных состояний;
4. индекс по `(iiko_status, next_attempt_at)` для восстановления неизвестного результата;
5. индекс по `(sagur_status, next_attempt_at)` для отправки в SAGUR.

Правила:

1. До вызова `get_customer_info` создать или обновить активную запись регистра с `iiko_status=lookup_started` и `sagur_status=not_ready`.
2. Запись регистра должна быть зафиксирована в базе до внешнего HTTP-вызова iikoCard; долгую транзакцию базы во время HTTP-вызова не держать.
3. Перед вызовом создания гостя iikoCard обновить эту же запись: заполнить `create_started_at`, поставить `iiko_status=create_started`.
4. При успешном создании записать `customer_id`, `created_new_customer=true`, `iiko_status=created`.
5. При найденном существующем госте записать `customer_id`, `existing_customer_found=true`, `iiko_status=existing`.
6. При сетевой ошибке/тайм-ауте после начала создания поставить `iiko_status=result_unknown`, `sagur_status=not_ready`, заполнить `recovery_reason`, `last_error_code`, `last_error_text`, `next_attempt_at`.
7. `iiko_status=created` создает событие SAGUR для нового не-legacy гостя и legacy-гостя.
8. `iiko_status=existing` создает событие SAGUR только для `registration_origin=legacy_upgrade`.
9. `iiko_status=existing` для `registration_origin=new_registration` переводит запись в `sagur_status=not_required`.
10. Когда событие нужно, в этой же записи один раз создаются `event_id`, `request_id`, `payload_body`, `payload_sha256`, затем ставится `sagur_status=pending`.
11. Пользовательский повтор текущего шага обновляет существующую активную запись регистра, а не создает параллельную.
12. Фоновый восстановитель не выполняет создание гостя; он делает только контрольный поиск по проблемной записи регистра.
13. Событие без `customer_id` и `payload_body` не может перейти в `sagur_status=pending`.

### Этап 3. Собрать тело события

Сборщик события должен формировать JSON по контракту SAGUR.

Источники данных:

1. `person_id` - локальный UUID человека;
2. `platform` - текущая платформа;
3. `external_id` - активный аккаунт платформы;
4. `phone_e164` - локальный телефон;
5. `customerId` - `customer_id` из iikoCard-синхронизации;
6. согласия, даты и профиль - из `persons` / `person_platform_states` / `platform_accounts`.

Сопоставление дат и согласий нужно брать из текущего подхода `sagur_recipients_repository.py`, чтобы не получить расхождение со снимком/дельтой (snapshot/delta):

1. `rules_accepted` = `person_platform_states.rules_accepted`;
2. `notifications_allowed` = `person_platform_states.notifications_allowed`;
3. `is_registered` = `person_platform_states.is_registered`;
4. `registered_at` = `person_platform_states.registered_at`;
5. `state_updated_at` = `person_platform_states.updated_at`;
6. `account_created_at` = `platform_accounts.created_at`;
7. `effective_updated_at` = максимум из `person_platform_states.updated_at`, `platform_accounts.created_at`, `persons.updated_at` с тем же смыслом, что в снимке/дельте (snapshot/delta).

Правила:

1. все обязательные поля должны быть заполнены;
2. `notifications_allowed` должен быть boolean;
3. `is_registered=true`;
4. `payload_body` сохраняется как фактические байты UTF-8 и используется при всех повторах.

### Этап 4. Подключить постановку события в Telegram/VK/MAX

Точки подключения:

1. `TelegramIdentityAdapter._finalize_iiko_sync_step`;
2. `VkIdentityAdapter._finalize_iiko_sync_step`;
3. `MaxIdentityAdapter._finalize_iiko_sync_step`.

Проверенный факт по текущему коду: эти точки используются не только для нового не-legacy сценария, но и для legacy-сценария после прохождения телефона, имени и согласий. Поэтому для legacy не нужно добавлять отдельный HTTP-запрос в iikoCard только ради `customerId`, если финальный шаг уже выполняет поиск/создание через `GetVirtualCardUseCase`.

Перед вызовом финального iikoCard-шага адаптер должен определить и передать `registration_origin`:

1. `legacy_upgrade`, если в текущем черновике регистрации стоит `is_legacy_upgrade=true` или пользователь пришел из явной legacy-ветки;
2. `new_registration` для обычной новой регистрации.

Это нужно сделать до очистки черновика и до потери контекста legacy. Текущая финальная команда регистрации записывает `is_legacy=False`, поэтому после нее нельзя надежно вычислять происхождение события только по `person.is_legacy`.

Регистрационный сценарий должен использовать обертку/сервис финальной iikoCard-синхронизации с контекстом `person_id`, `platform`, `external_id`, `phone_e164`, `registration_origin`. Именно этот сервис создает или обновляет запись единого регистра до внешнего вызова iikoCard, вызывает `GetVirtualCardUseCase`, получает `customer_id` и признаки создания/существования, затем принимает решение о постановке SAGUR-события. Обычное открытие раздела "Виртуальная карта" не должно обращаться к этому сервису и не должно создавать запись SAGUR-регистра.

Условие постановки:

1. `registration_origin=new_registration` и `created_new_customer=true`;
2. `registration_origin=legacy_upgrade` и `customer_id` получен.

Если условие не выполнено, запись регистра не переводится в отправку SAGUR.

### Этап 5. HTTP-клиент SAGUR

Клиент должен:

1. брать сохраненный `payload_body`;
2. считать SHA256 от фактических байтов;
3. собирать каноническую строку;
4. подписывать HMAC-SHA256;
5. отправлять POST;
6. обрабатывать `202`, `202 duplicate=true`, временные ошибки и `409 event_id_payload_conflict`.

### Этап 6. Фоновый обработчик регистра

Обработчик отправки SAGUR:

1. просыпается по интервалу;
2. выбирает записи `sagur_status=pending` или `sagur_status=retry_scheduled`, у которых наступило `next_attempt_at`;
3. берет пачку с лимитом;
4. блокирует записи;
5. отправляет;
6. при успехе ставит `sagur_status=sent`;
7. при временной ошибке ставит `sagur_status=retry_scheduled` и планирует повтор;
8. при конфликте ставит `sagur_status=conflict`;
9. возвращает зависшие `sagur_status=processing` после истечения блокировки.

Рекомендуемые стартовые настройки:

1. интервал прохода: `60` секунд для отправки SAGUR;
2. лимит пачки: `20`;
3. максимальное число попыток: настраиваемое;
4. повтор при временной ошибке планировать с нарастающей задержкой, без постоянного частого опроса.

Обработчик восстановления iikoCard:

1. не создает гостя автоматически;
2. работает только с проблемными записями регистра;
3. рекомендуемый интервал прохода: `300` секунд;
4. лимит пачки: `10`;
5. первый контрольный поиск планировать не сразу, а после короткой задержки, например `120` секунд;
6. один проход по одной записи делает не больше одного контрольного поиска в iikoCard;
7. повторные контрольные поиски выполнять с нарастающей задержкой, например `10` / `30` / `60` минут;
8. после исчерпания попыток переводить запись в `manual_review` или `failed_terminal` по правилу из раздела 6.2.

Для единого регистра нужно отдельно реализовать возврат зависших `sagur_status=processing` записей после истечения блокировки. В текущем `profile_sync_queue` есть `locked_at`, но нет готового механизма восстановления зависших записей после падения процесса; для нового регистра это должно быть явным требованием.

Фиксация текущего запуска на 2026-07-10:

1. Текущий сценарий доводится через отдельный долгоживущий фоновый процесс `sagur-registration-events-worker` в `docker-compose.yml`.
2. Процесс запускает уже реализованную точку входа `python -m vtelemax.apps.sagur_registration_events_worker_app`.
3. Это завершает минимальный боевой запуск текущей реализации без изменения бизнес-логики регистрации.
4. После стабилизации нужно отдельно обсудить рефакторинг способа запуска фоновых очередей: режим одного прохода, запуск по расписанию, диагностика и защита от параллельных запусков.

### Этап 7. Логи, метрики и нагрузка

Логи должны быть на русском языке, технические поля сохраняются как структурированные поля:

1. `event_id`;
2. `request_id`;
3. `record_id`;
4. `person_id`;
5. `platform`;
6. `external_id`;
7. `customerId`;
8. HTTP-статус;
9. код ошибки SAGUR;
10. признак дубля;
11. номер попытки.

В логах нельзя печатать HMAC-секреты и полные тела запросов с персональными данными. Телефон допустим только в маскированном виде или в техническом контексте, где это уже принято в проекте.

Локализация терминов и комментариев:

1. новые комментарии в коде и docstring писать на русском языке, если они нужны для объяснения неочевидной логики;
2. не добавлять комментарии там, где код самодостаточно понятен;
3. пользовательские тексты, сообщения ошибок и логи писать на русском языке;
4. технические идентификаторы, имена полей, переменных окружения, HTTP-заголовков, статусов и кодов ошибок не переводить: `customerId`, `event_id`, `request_id`, `sagur_status`, `iiko_status`, `X-Vtelemax-Request-Id`;
5. если в документации нужен английский термин, рядом указывать русский смысл.

Метрики:

1. количество поставленных событий;
2. количество успешно отправленных событий;
3. количество дублей `duplicate=true`;
4. количество временных ошибок;
5. количество конфликтов `event_id_payload_conflict`;
6. количество записей `manual_review`;
7. задержка от создания записи регистра до успешной отправки;
8. время HTTP-запроса в SAGUR.

Нагрузка:

1. успешный путь нового гостя не должен добавлять дополнительные запросы в iikoCard сверх текущего поиска/создания/обновления;
2. восстановитель iikoCard работает только по проблемным записям, а не сканирует всех гостей;
3. ночной запуск допустим только с тем же ограничением пачки и интервала, потому что он не должен создавать массовую нагрузку;
4. все лимиты должны быть настройками, а не константами внутри кода.

## 8. Минимальный набор тестов

1. Новый не-legacy гость создает iikoCard-гостя и SAGUR-событие.
2. Legacy-гость с существующим iikoCard-гостем создает SAGUR-событие с найденным `customerId`.
3. Legacy-гость, созданный в iikoCard во время текущей регистрации, создает SAGUR-событие.
4. Не-legacy гость с уже существующим iikoCard-гостем не создает SAGUR-событие.
5. Telegram ставит событие при выполненном условии.
6. VK ставит событие при выполненном условии.
7. MAX ставит событие при выполненном условии.
8. Полный JSON соответствует контракту.
9. `X-Vtelemax-Request-Id` совпадает с JSON `request_id`.
10. HMAC считается от фактических байтов `payload_body`.
11. Повтор отправляет тот же `payload_body`.
12. `202` считается успехом.
13. `202 duplicate=true` считается успехом.
14. `409 event_id_payload_conflict` не уходит в автоматический повтор.
15. Сетевая ошибка уходит в повтор.
16. HTTP `5xx` уходит в повтор.
17. Зависшая запись `sagur_status=processing` возвращается в обработку после истечения блокировки.
18. Пользовательский повтор iikoCard-синхронизации обновляет существующую запись регистра.
19. Восстановитель iikoCard не вызывает создание гостя автоматически.
20. Запись регистра создается или обновляется до внешнего вызова iikoCard.
21. Ошибка после начала создания переводит запись в `iiko_status=result_unknown`, а не создает новое событие без `customerId`.
22. VK-сценарий ставит событие без жесткой проверки `active`, если выполнены остальные согласованные условия.
23. В логах нет HMAC-секретов и полного тела запроса с персональными данными.
24. Частичный уникальный индекс активной записи не дает создать параллельную запись для одного текущего прохода регистрации.
25. Запись с `sagur_status=retry_scheduled` снова выбирается обработчиком после наступления `next_attempt_at`.
26. Legacy-проход передает `registration_origin=legacy_upgrade` в финальный iikoCard-шаг до очистки черновика регистрации.
27. Открытие раздела "Виртуальная карта" после регистрации не создает SAGUR-событие и не создает запись единого регистра.

Регрессионные тесты обязательны отдельно от новых сценариев. Они должны подтвердить, что доработка не ломает действующее поведение проекта:

1. существующая регистрация Telegram/VK/MAX по-прежнему завершается и показывает гостю карточки;
2. повтор iikoCard-синхронизации из текущего экрана по-прежнему работает;
3. раздел "Виртуальная карта" по-прежнему ищет/создает/обновляет гостя iikoCard и показывает карту без постановки SAGUR-события;
4. текущая очередь синхронизации профиля `profile_sync_queue` сохраняет прежнее поведение;
5. текущий входящий SAGUR API, снимок/дельта (snapshot/delta) и купонные события SAGUR -> vtelemax сохраняют прежнее поведение;
6. настройка `SAGUR_INTEGRATION_HMAC_SECRET` продолжает обслуживать текущий обмен с SAGUR и может использоваться как общий секрет welcome-callback, если отдельный `VTELEMAX_REGISTRATION_CALLBACK_HMAC_SECRET` пустой;
7. новый флаг отключения исходящих событий SAGUR полностью отключает новую отправку и не влияет на регистрацию, iikoCard и текущие SAGUR-обработчики.

## 9. Настройки

Новые настройки:

1. `SAGUR_REGISTRATION_EVENTS_ENABLED`;
2. `SAGUR_REGISTRATION_EVENTS_ENDPOINT`;
3. `VTELEMAX_REGISTRATION_CALLBACK_HMAC_SECRET`;
4. `SAGUR_REGISTRATION_EVENTS_TIMEOUT_SECONDS`;
5. `SAGUR_REGISTRATION_EVENTS_INTERVAL_SECONDS`;
6. `SAGUR_REGISTRATION_EVENTS_BATCH_LIMIT`;
7. `SAGUR_REGISTRATION_EVENTS_MAX_ATTEMPTS`;
8. `SAGUR_REGISTRATION_EVENTS_RECOVERY_ENABLED`;
9. `SAGUR_REGISTRATION_EVENTS_RECOVERY_INTERVAL_SECONDS`;
10. `SAGUR_REGISTRATION_EVENTS_RECOVERY_BATCH_LIMIT`;
11. `SAGUR_REGISTRATION_EVENTS_RECOVERY_MAX_ATTEMPTS`;
12. `SAGUR_REGISTRATION_EVENTS_RECOVERY_FIRST_DELAY_SECONDS`;
13. `SAGUR_REGISTRATION_EVENTS_LOCK_TIMEOUT_SECONDS`.

Стартовые значения:

Правило секрета:

1. если `VTELEMAX_REGISTRATION_CALLBACK_HMAC_SECRET` заполнен, используется он;
2. если он пустой, используется `SAGUR_INTEGRATION_HMAC_SECRET`;
3. на стороне SAGUR общему секрету соответствует `VTELEMAX_SYNC_HMAC_SECRET`.

1. `SAGUR_REGISTRATION_EVENTS_INTERVAL_SECONDS=60`;
2. `SAGUR_REGISTRATION_EVENTS_BATCH_LIMIT=20`;
3. `SAGUR_REGISTRATION_EVENTS_RECOVERY_INTERVAL_SECONDS=300`;
4. `SAGUR_REGISTRATION_EVENTS_RECOVERY_BATCH_LIMIT=10`;
5. `SAGUR_REGISTRATION_EVENTS_RECOVERY_FIRST_DELAY_SECONDS=120`;
6. `SAGUR_REGISTRATION_EVENTS_RECOVERY_MAX_ATTEMPTS=3`.

## 10. Проверка

Перед реализацией сверить реализацию с зафиксированными ограничениями из раздела 6.

После каждого этапа запускать точечные тесты.

Перед итоговой сдачей использовать проверочный скрипт проекта, найденный в `scripts`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_pytest.ps1 tests/unit
```

При изменении PostgreSQL-слоя дополнительно:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_pytest.ps1 tests/integration
```

Коммит делать только после отдельного подтверждения.
