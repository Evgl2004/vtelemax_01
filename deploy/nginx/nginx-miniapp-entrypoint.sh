#!/bin/sh
set -eu

DOMAIN="${TLS_DOMAIN:-sobalbot.24vds.ru}"
CHECK_INTERVAL_SECONDS="${NGINX_CONFIG_CHECK_INTERVAL_SECONDS:-300}"

HTTP_TEMPLATE="/etc/nginx/templates/vk-miniapp-http.conf"
TLS_TEMPLATE="/etc/nginx/templates/vk-miniapp-tls.conf"
ACTIVE_CONFIG="/etc/nginx/conf.d/default.conf"

CERT_PATH="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
KEY_PATH="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"

render_http_config() {
  cp "${HTTP_TEMPLATE}" "${ACTIVE_CONFIG}"
}

render_tls_config() {
  sed "s|__TLS_DOMAIN__|${DOMAIN}|g" "${TLS_TEMPLATE}" > "${ACTIVE_CONFIG}"
}

is_tls_available() {
  [ -f "${CERT_PATH}" ] && [ -f "${KEY_PATH}" ]
}

is_active_config_tls() {
  grep -q "listen 443 ssl" "${ACTIVE_CONFIG}" 2>/dev/null
}

current_tls_fingerprint() {
  if ! is_tls_available; then
    echo ""
    return 0
  fi
  cat "${CERT_PATH}" "${KEY_PATH}" 2>/dev/null | cksum | awk '{print $1}'
}

apply_best_config() {
  if is_tls_available; then
    if is_active_config_tls; then
      return 1
    fi
    echo "[nginx-miniapp] TLS certificate found, enabling HTTPS config for ${DOMAIN}."
    render_tls_config
    return 0
  fi

  if is_active_config_tls; then
    echo "[nginx-miniapp] TLS certificate not found, switching to HTTP bootstrap config."
    render_http_config
    return 0
  fi
  return 1
}

if is_tls_available; then
  render_tls_config
else
  render_http_config
fi

LAST_TLS_FINGERPRINT="$(current_tls_fingerprint)"

nginx -g "daemon off;" &
NGINX_PID=$!

while kill -0 "${NGINX_PID}" 2>/dev/null; do
  sleep "${CHECK_INTERVAL_SECONDS}"
  if apply_best_config; then
    LAST_TLS_FINGERPRINT="$(current_tls_fingerprint)"
    echo "[nginx-miniapp] Config changed, reloading nginx."
    nginx -s reload || true
    continue
  fi

  if is_tls_available && is_active_config_tls; then
    CURRENT_TLS_FINGERPRINT="$(current_tls_fingerprint)"
    if [ -n "${CURRENT_TLS_FINGERPRINT}" ] && [ "${CURRENT_TLS_FINGERPRINT}" != "${LAST_TLS_FINGERPRINT}" ]; then
      LAST_TLS_FINGERPRINT="${CURRENT_TLS_FINGERPRINT}"
      echo "[nginx-miniapp] TLS certificate changed, reloading nginx."
      nginx -s reload || true
    fi
  else
    LAST_TLS_FINGERPRINT=""
  fi

  if ! kill -0 "${NGINX_PID}" 2>/dev/null; then
    break
  fi
done

wait "${NGINX_PID}"
