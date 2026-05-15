# Batch-контракт купонов SAGUR -> vtelemax

Дата фиксации: 2026-05-15.

Документ описывает реализацию приема batch-событий купонов на стороне vtelemax.

## Endpoint

Endpoint остается прежним:

```text
POST /internal/integration/v1/sagur/coupons/events
```

Новый формат запроса:

```json
{
  "request_id": "6c0d7c33-9f3f-4ed0-b8a7-0877ab9f5c2a",
  "direction": "assignments",
  "sent_at": "2026-05-15T10:00:00Z",
  "items": []
}
```

`request_id` идентифицирует HTTP-пачку. Идемпотентность бизнес-событий
сохраняется по `event_id` внутри каждого item.

## Ответ

vtelemax возвращает обязательный item-level `results[]`.

Полный успех:

```json
{
  "request_id": "6c0d7c33-9f3f-4ed0-b8a7-0877ab9f5c2a",
  "status": "acked",
  "results": [
    {
      "event_id": "6f8c2b8d-13d0-4b0f-8f72-2e2fda7fd001",
      "status": "acked"
    }
  ]
}
```

Частичный успех:

```json
{
  "request_id": "6c0d7c33-9f3f-4ed0-b8a7-0877ab9f5c2a",
  "status": "partial",
  "results": [
    {
      "event_id": "6f8c2b8d-13d0-4b0f-8f72-2e2fda7fd001",
      "status": "acked"
    },
    {
      "event_id": "d853d2a2-73c4-4a9a-a6b3-d68f72b0d002",
      "status": "rejected",
      "code": "recipient_not_found",
      "message": "Получатель не найден"
    }
  ]
}
```

HTTP 200 используется и для полного, и для частичного успеха. HTTP 4xx/5xx
возвращается только для batch-level проблем: невалидный JSON, неверная подпись,
невалидная структура верхнего уровня или системная ошибка до обработки items.

## Item-level обработка

Каждый item обрабатывается независимо и коммитится отдельно. Ошибка одного item
не откатывает уже подтвержденные items.

Поддержанные item-level коды:

- `recipient_not_found` - получатель не найден по `person_id` или `phone_e164`;
- `coupon_already_assigned` - купон уже привязан или применен и не был
  освобожден через `canceled`;
- `invalid_payload` - невалидные поля item;
- `internal_error` - внутренняя ошибка обработки конкретного item.

Успешный повтор того же `event_id` возвращается как:

```json
{
  "event_id": "6f8c2b8d-13d0-4b0f-8f72-2e2fda7fd001",
  "status": "acked",
  "deduplicated": true
}
```

## HMAC

Для batch-запросов поддержана подпись по canonical payload с hash тела:

```text
METHOD
PATH
TIMESTAMP
SHA256(BODY)
```

Legacy-подпись без hash тела сохранена для обратной совместимости существующих
SAGUR endpoint.

## Статусы купонов

`assignments`:

- создает или обновляет видимую привязку купона к гостю;
- активными для UI остаются `reserved` и `sent`.

`status_update: used`:

- убирает купон из активного UI;
- не освобождает купон для повторного назначения.

`status_update: used_after_campaign`:

- принимает поздний факт использования после завершения кампании;
- убирает купон из активного UI;
- хранится отдельным статусом, не склеивается с обычным `used`;
- не освобождает купон для повторного назначения.

`status_update: expired`:

- убирает купон из активного UI;
- не освобождает купон для повторного назначения.

`status_update: canceled`:

- трактуется как release;
- удаляет связку `купон <-> гость`;
- позволяет будущий `assignments` того же `coupon_series + coupon_code` другому
  гостю;
- повторный `canceled` по уже снятому купону возвращает успешный item-level ACK.

## Проверенные сценарии

Автотестами покрыты:

- batch `assignments` из двух успешных items;
- batch `assignments` с partial success и `recipient_not_found`;
- защита от повторного `assignments` для купона в статусе `used`;
- batch `status_update` со статусом `used_after_campaign`;
- retry batch item с тем же `event_id`;
- `canceled -> release -> reassign`;
- HMAC batch-подпись с `SHA256(BODY)`.

Базовый запуск:

```powershell
C:\Users\admin_eas\PycharmProjects\vtelemax\scripts\run_pytest.ps1 tests/unit/test_sagur_integration_api_app.py tests/unit/test_sagur_coupons_repository.py tests/unit/test_coupon_content.py
```
