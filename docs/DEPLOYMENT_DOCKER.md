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
   1. `IIKO_AUTH_VERSION` — `v1` по умолчанию или `v2` после проверки новой
      авторизации;
   2. для `v1`: `IIKO_API_KEY` со старым `apiLogin`;
   3. для `v2`: `IIKO_APP_ID`, `IIKO_CLIENT_SECRET`, `IIKO_CLOUD_API_KEY`;
   4. общий `IIKO_ORG_ID`;
   5. `IIKO_AUTH_URL` и `IIKO_BASE_URL` обычно оставляются со значениями из
      `.env.example`.

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
   1. при полном наборе выбранной версии должен возвращаться реальный ответ системы
      лояльности;
   2. при неполном наборе шлюз iiko не создаётся, приложения продолжают работать и
      возвращают предусмотренное сообщение о недоступности функций лояльности.

## 8. Переход с авторизации v1 на v2

1. Сначала разверните новый код с `IIKO_AUTH_VERSION=v1` и убедитесь, что текущие
   сценарии iiko работают без регрессий.
2. Добавьте в защищённый `.env` новые `IIKO_APP_ID`, `IIKO_CLIENT_SECRET` и
   `IIKO_CLOUD_API_KEY`, не меняя активную версию.
3. Выполните отдельную проверку `v2` по инструкции `docs/IIKO_DIAGNOSTICS.md`.
4. После успешной проверки измените только:

```dotenv
IIKO_AUTH_VERSION=v2
```

5. Пересоздайте процессы, использующие iiko:

```bash
docker compose up -d --force-recreate \
  telegram-bot vk-bot max-bot \
  profile-sync-worker sagur-registration-events-worker
```

6. Проверьте баланс, виртуальную карту, регистрацию в трёх мессенджерах, очередь
   синхронизации профиля и восстановление регистраций SAGUR.

Автоматического возврата к `v1` при ошибке нет. Для ручного отката верните
`IIKO_AUTH_VERSION=v1` и повторно пересоздайте те же процессы. Старый
`IIKO_API_KEY` удаляется только после принятия отдельного решения об отключении
возможности возврата.
