# VK Mini App: подтверждение телефона (MVP)

Документ описывает запуск отдельного сервиса `vk-phone-verification-service`
для сценария:

`VK бот -> VK Mini App -> подтверждение телефона -> polling статуса из VK-бота`.

## 1. Что уже реализовано

- Отдельный контейнер `vk-phone-verification-service`.
- Таблица сессий `vk_phone_verification_sessions`.
- Backend endpoints:
  - `GET /vk/miniapp` — страница Mini App;
  - `POST /api/v1/vk/miniapp/session/start`;
  - `POST /api/v1/vk/miniapp/session/phone`;
  - `GET /api/v1/vk/miniapp/session/status?vk_user_id=...`.
- Подписанные ссылки Mini App из VK-бота (`uid`, `ts`, `sig`).
- Проверка подписи и TTL на backend.
- Для status endpoint обязательна авторизация Bearer-токеном.

## 2. Обязательные env-переменные

```env
VK_PHONE_VERIFICATION_MINIAPP_ENABLED=true
VK_PHONE_VERIFICATION_MINIAPP_URL=https://<domain>/vk/miniapp
VK_PHONE_VERIFICATION_STATUS_URL=https://<domain>/api/v1/vk/miniapp/session/status
VK_PHONE_VERIFICATION_API_TOKEN=<strong-random-token>
VK_PHONE_VERIFICATION_LINK_SECRET=<strong-random-secret>
VK_PHONE_VERIFICATION_LINK_TTL_SECONDS=900

VK_PHONE_VERIFICATION_SERVICE_ENABLED=true
VK_PHONE_VERIFICATION_SERVICE_HOST=0.0.0.0
VK_PHONE_VERIFICATION_SERVICE_PORT=8085
VK_PHONE_VERIFICATION_SESSION_TTL_SECONDS=900
```

## 3. Запуск в Docker Compose

```bash
sudo docker compose up -d --build db-migrator vk-phone-verification-service vk-bot
```

Проверка:

```bash
sudo docker compose ps
sudo docker compose logs -f --tail=200 vk-phone-verification-service vk-bot
```

## 4. Nginx (рекомендуемая проксирующая схема)

Пример безопасного проксирования (внешний Nginx):

```nginx
server {
    listen 443 ssl http2;
    server_name <domain>;

    # Mini App UI
    location = /vk/miniapp {
        proxy_pass http://127.0.0.1:8085;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Mini App API
    location /api/v1/vk/miniapp/ {
        proxy_pass http://127.0.0.1:8085;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        client_max_body_size 64k;
        proxy_read_timeout 15s;
    }
}
```

Рекомендации:

- Не открывать порт `8085` наружу напрямую (доступ только через Nginx/localhost).
- Использовать длинные случайные значения `VK_PHONE_VERIFICATION_API_TOKEN` и `VK_PHONE_VERIFICATION_LINK_SECRET`.
- Ротация секретов по регламенту.

## 5. Безопасный rollback

```env
VK_PHONE_VERIFICATION_MINIAPP_ENABLED=false
VK_PHONE_VERIFICATION_SERVICE_ENABLED=false
```

После изменения env:

```bash
sudo docker compose up -d --build vk-bot vk-phone-verification-service
```

VK-бот автоматически вернется к ручному вводу телефона.

