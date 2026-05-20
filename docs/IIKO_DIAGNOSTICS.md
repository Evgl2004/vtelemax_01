# Диагностика ошибок iiko

Документ описывает безопасный запуск read-only диагностики по кодам `IIKO-*`.
Скрипт имеет историческое имя `diagnose_iiko_balance_incident.py`, но теперь
подходит и для баланса, и для виртуальной карты.

## Что собирает скрипт

- связь `platform/external_id` с `person_id`;
- телефон, состояние регистрации, согласия и platform state;
- уникальность телефона: по указанному `--phone-e164`, а если телефон не задан,
  только по найденному `person_id`;
- тикеты и сообщения поддержки за окно инцидента;
- другие тикеты с теми же `IIKO-*` кодами за это же окно, с агрегацией
  повторяющихся сообщений внутри одного тикета;
- состояние очереди синхронизации профиля с iiko;
- замаскированный runtime-конфиг iiko из `.env`;
- отфильтрованные логи контейнеров;
- опционально read-only live-probe `customer/info` в iiko.

SQL выполняется внутри `BEGIN READ ONLY`, поэтому расследование не меняет БД.
Live-probe вызывает только `customer/info`; операции create/update/card issue
скрипт не выполняет.

## Известные коды

| Код | Значение |
| --- | --- |
| `IIKO-BAL-000` | Баланс: use-case не подключен, локальная интеграция выключена/недоступна. |
| `IIKO-BAL-001` | Баланс: клиент не найден в iiko или запрос `customer/info` завершился ошибкой. |
| `IIKO-CARD-000` | Виртуальная карта: use-case не подключен, локальная интеграция выключена/недоступна. |
| `IIKO-CARD-001` | Виртуальная карта: не удалось получить `customer/info` перед показом карты. |
| `IIKO-CARD-002` | Виртуальная карта: не удалось создать/зарегистрировать клиента в iiko. |
| `IIKO-CARD-003` | Виртуальная карта: не удалось выпустить карту в iiko. |
| `IIKO-CARD-004` | Виртуальная карта: не удалось обновить профиль клиента в iiko. |

На сервере справочник можно вывести командой:

```bash
cd /var/www/vtelemax
sudo python3 scripts/diagnose_iiko_balance_incident.py --list-known-codes
```

## Подготовка файла на сервере

Если скрипт переносится вручную, команды выполняются раздельно.

Создание/редактирование файла:

```bash
cd /var/www/vtelemax
sudo nano scripts/diagnose_iiko_balance_incident.py
```

Проверка компиляции:

```bash
sudo python3 -m py_compile scripts/diagnose_iiko_balance_incident.py
```

Разрешение на исполнение:

```bash
sudo chmod 750 scripts/diagnose_iiko_balance_incident.py
```

## Пример: баланс `IIKO-BAL-001`

```bash
sudo python3 scripts/diagnose_iiko_balance_incident.py \
  --platform telegram \
  --external-id 5833652675 \
  --phone-e164 +79829303027 \
  --ticket-suffix 8E5D \
  --error-code IIKO-BAL-001 \
  --incident-local "2026-05-19 12:05:41" \
  --window-minutes 10 \
  --live-iiko-readonly \
  --report-path /tmp/iiko_bal_8E5D.txt
```

Чтение отчета:

```bash
sudo cat /tmp/iiko_bal_8E5D.txt
```

## Пример: виртуальная карта

Для ошибок карты код меняется на нужный `IIKO-CARD-*`. Live-probe безопасен,
но проверяет только наличие клиента через `customer/info`.

```bash
sudo python3 scripts/diagnose_iiko_balance_incident.py \
  --platform telegram \
  --external-id 5833652675 \
  --phone-e164 +79829303027 \
  --error-code IIKO-CARD-001 \
  --incident-local "2026-05-19 12:05:41" \
  --window-minutes 10 \
  --live-iiko-readonly \
  --report-path /tmp/iiko_card_5833652675.txt
```

## Поиск нескольких кодов сразу

Можно передать несколько кодов повтором флага:

```bash
sudo python3 scripts/diagnose_iiko_balance_incident.py \
  --platform telegram \
  --external-id 5833652675 \
  --phone-e164 +79829303027 \
  --error-code IIKO-BAL-001 \
  --error-code IIKO-CARD-001 \
  --error-code IIKO-CARD-003 \
  --incident-local "2026-05-19 12:05:41" \
  --window-minutes 30 \
  --report-path /tmp/iiko_multi_5833652675.txt
```

Или через запятую:

```bash
sudo python3 scripts/diagnose_iiko_balance_incident.py \
  --platform telegram \
  --external-id 5833652675 \
  --phone-e164 +79829303027 \
  --error-code IIKO-BAL-001,IIKO-CARD-001,IIKO-CARD-003 \
  --incident-local "2026-05-19 12:05:41" \
  --window-minutes 30 \
  --report-path /tmp/iiko_multi_5833652675.txt
```

## Минимальный запуск без live-probe

Если телефон неизвестен или не нужно обращаться к iiko, можно собрать только
локальные факты по профилю, тикетам и логам:

```bash
sudo python3 scripts/diagnose_iiko_balance_incident.py \
  --platform telegram \
  --external-id 5833652675 \
  --error-code IIKO-BAL-001 \
  --incident-local "2026-05-19 12:05:41" \
  --window-minutes 10 \
  --report-path /tmp/iiko_local_only_5833652675.txt
```
