# VK Mini App over Docker Nginx + Certbot (no host Nginx required)

This setup publishes VK Mini App endpoints on the same domain path:

- `/vk/miniapp`
- `/api/v1/vk/miniapp/session/start`
- `/api/v1/vk/miniapp/session/phone`

The status endpoint remains internal-only:

- `http://vk-phone-verification-service:8085/api/v1/vk/miniapp/session/status`

## 1) Required `.env` values

```env
VK_PHONE_VERIFICATION_MINIAPP_ENABLED=true
VK_PHONE_VERIFICATION_MINIAPP_URL=https://sobalbot.24vds.ru/vk/miniapp
VK_PHONE_VERIFICATION_STATUS_URL=http://vk-phone-verification-service:8085/api/v1/vk/miniapp/session/status
VK_PHONE_VERIFICATION_API_TOKEN=<strong-random-token>
VK_PHONE_VERIFICATION_LINK_SECRET=<strong-random-secret>
VK_PHONE_VERIFICATION_LINK_TTL_SECONDS=900

VK_PHONE_VERIFICATION_SERVICE_ENABLED=true
VK_PHONE_VERIFICATION_SERVICE_PORT=8085
VK_PHONE_VERIFICATION_SESSION_TTL_SECONDS=900

NGINX_HTTP_PORT=80
NGINX_HTTPS_PORT=443
TLS_DOMAIN=sobalbot.24vds.ru
TLS_EMAIL=admin@sobalbot.24vds.ru
```

## 2) Default run (normal operation)

```bash
sudo docker compose up -d --build
```

This is the normal command for every-day start/restart.

## 3) Issue first certificate (one-shot only)

```bash
sudo docker compose --profile tls-init run --rm certbot-init
```

Expected result: cert files appear in `/etc/letsencrypt/live/<TLS_DOMAIN>/`.

## 4) Activate HTTPS in nginx

```bash
sudo docker compose restart nginx
```

Notes:

- `nginx` is always started by default (`docker compose up -d`).
- `certbot-renew` is also started by default and renews certificates automatically.
- `nginx` entrypoint auto-selects config:
  - no cert yet -> HTTP bootstrap config;
  - cert exists -> HTTPS config.

## 5) Check

```bash
sudo docker compose ps
sudo docker compose logs -f --tail=200 nginx certbot-renew vk-phone-verification-service vk-bot
curl -I https://sobalbot.24vds.ru/vk/miniapp
```

## 6) Rollback

```env
VK_PHONE_VERIFICATION_MINIAPP_ENABLED=false
VK_PHONE_VERIFICATION_SERVICE_ENABLED=false
```

Then:

```bash
sudo docker compose up -d --build vk-bot vk-phone-verification-service
```
