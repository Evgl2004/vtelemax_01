# Docker Compose: запуск vtelemax

Документ описывает минимальный контур запуска проекта в контейнерах:

1. PostgreSQL.
2. Telegram-бот.
3. VK-бот.
4. MAX-бот.

## 1. Подготовка

1. Убедитесь, что установлен Docker Desktop (или Docker Engine + Compose plugin).
2. Создайте `.env` на основе `.env.example`.
3. Заполните обязательные токены:
   1. `TELEGRAM_BOT_TOKEN`
   2. `VK_BOT_TOKEN`
   3. `MAX_BOT_TOKEN`
4. При необходимости скорректируйте параметры PostgreSQL в `.env`.

## 2. Запуск всего стека

```bash
docker compose up -d --build
```

Что происходит при старте:

1. Поднимается контейнер `postgres`.
2. Каждый бот перед запуском применяет SQL-миграции из `migrations/sql`.
3. После миграций запускается приложение соответствующего адаптера.

Миграции сделаны идемпотентными (`IF NOT EXISTS`), поэтому повторный запуск безопасен.

## 3. Просмотр логов

```bash
docker compose logs -f postgres
docker compose logs -f telegram-bot
docker compose logs -f vk-bot
docker compose logs -f max-bot
```

## 4. Запуск отдельного бота

```bash
docker compose up -d --build postgres telegram-bot
```

По аналогии можно запускать `vk-bot` или `max-bot`.

## 5. Остановка и удаление контейнеров

```bash
docker compose down
```

Чтобы также удалить том с данными PostgreSQL:

```bash
docker compose down -v
```

## 6. Проверка запуска

Базовая smoke-проверка:

1. Убедитесь, что `postgres` в статусе `healthy`.
2. Убедитесь, что контейнеры ботов не перезапускаются циклически.
3. Отправьте `/start` в каждый бот и проверьте ответ.
