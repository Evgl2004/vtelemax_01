# Docker Compose: запуск vtelemax

Документ описывает базовый контур запуска проекта в контейнерах:

1. PostgreSQL.
2. Одноразовый сервис миграций `db-migrator`.
3. Telegram-бот.
4. VK-бот.
5. MAX-бот.

## 1. Подготовка

1. Убедитесь, что установлен Docker Desktop (или Docker Engine + Compose plugin).
2. Создайте `.env` на основе `.env.example`.
3. Заполните обязательные токены:
   1. `TELEGRAM_BOT_TOKEN`
   2. `VK_BOT_TOKEN`
   3. `MAX_BOT_TOKEN`
4. При необходимости скорректируйте параметры PostgreSQL в `.env`.
5. Для разделов лояльности `Мой баланс` и `Виртуальная карта` заполните:
   1. `IIKO_API_KEY`
   2. `IIKO_ORG_ID`
   3. `IIKO_BASE_URL` (опционально, по умолчанию уже задан)

## 2. Запуск всего стека

```bash
docker compose up -d --build
```

Порядок старта:

1. Поднимается контейнер `postgres`.
2. После `healthy` запускается одноразовый контейнер `db-migrator` и применяет SQL-миграции из `migrations/sql`.
3. Только после успешного завершения `db-migrator` запускаются `telegram-bot`, `vk-bot`, `max-bot`.

Важно: миграции не выполняются параллельно тремя ботами, поэтому исключается гонка и ошибки вида `duplicate key value violates unique constraint ... pg_type_typname_nsp_index`.

## 3. Проверка логов

```bash
docker compose logs -f db-migrator
docker compose logs -f telegram-bot
docker compose logs -f vk-bot
docker compose logs -f max-bot
```

Ожидаемое поведение `db-migrator`: успешное завершение (`Exited (0)`).

## 4. Повторный запуск миграций вручную

Если нужно вручную повторно применить миграции:

```bash
docker compose run --rm db-migrator
```

## 5. Запуск отдельного бота

```bash
docker compose up -d --build postgres telegram-bot
```

По аналогии можно запускать `vk-bot` или `max-bot`.

## 6. Остановка и удаление контейнеров

```bash
docker compose down
```

Чтобы удалить также том с данными PostgreSQL:

```bash
docker compose down -v
```

## 7. Базовый smoke-чеклист

1. Убедитесь, что `postgres` в статусе `healthy`.
2. Убедитесь, что `db-migrator` завершился успешно (`Exited (0)`).
3. Убедитесь, что контейнеры ботов не перезапускаются циклически.
4. Отправьте `/start` в каждый бот и проверьте ответ.
5. Проверьте пункты меню `Мой баланс` и `Виртуальная карта` в Telegram/VK/MAX:
   1. при заполненных `IIKO_*` должен возвращаться реальный ответ системы лояльности;
   2. при отключенных `IIKO_API_KEY`/`IIKO_ORG_ID` должен приходить корректный fallback-текст о временной недоступности.
