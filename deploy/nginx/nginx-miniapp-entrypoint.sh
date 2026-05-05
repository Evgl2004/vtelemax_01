#!/bin/sh
set -eu

DOMAIN="${TLS_DOMAIN:-sobalbot.24vds.ru}"
CHECK_INTERVAL_SECONDS="${NGINX_CONFIG_CHECK_INTERVAL_SECONDS:-300}"
SAGUR_IP_ALLOWLIST="${SAGUR_INTEGRATION_IP_ALLOWLIST:-}"
SAGUR_RATE_LIMIT_RPM="${SAGUR_INTEGRATION_RATE_LIMIT_RPM:-60}"
SAGUR_SERVICE_PORT="${SAGUR_INTEGRATION_SERVICE_PORT:-8086}"

HTTP_TEMPLATE="/etc/nginx/templates/vk-miniapp-http.conf"
TLS_TEMPLATE="/etc/nginx/templates/vk-miniapp-tls.conf"
ACTIVE_CONFIG="/etc/nginx/conf.d/default.conf"

CERT_PATH="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
KEY_PATH="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"

render_http_config() {
  ALLOWLIST_BLOCK="$(build_sagur_allowlist_block)"
  sed \
    -e "s|__SAGUR_RATE_LIMIT_RPM__|${SAGUR_RATE_LIMIT_RPM}|g" \
    -e "s|__SAGUR_SERVICE_PORT__|${SAGUR_SERVICE_PORT}|g" \
    "${HTTP_TEMPLATE}" \
    | awk -v block="${ALLOWLIST_BLOCK}" '
      { if ($0 ~ /__SAGUR_ALLOWLIST_BLOCK__/) { print block; next } print }
    ' > "${ACTIVE_CONFIG}"
}

render_tls_config() {
  ALLOWLIST_BLOCK="$(build_sagur_allowlist_block)"
  sed \
    -e "s|__TLS_DOMAIN__|${DOMAIN}|g" \
    -e "s|__SAGUR_RATE_LIMIT_RPM__|${SAGUR_RATE_LIMIT_RPM}|g" \
    -e "s|__SAGUR_SERVICE_PORT__|${SAGUR_SERVICE_PORT}|g" \
    "${TLS_TEMPLATE}" \
    | awk -v block="${ALLOWLIST_BLOCK}" '
      { if ($0 ~ /__SAGUR_ALLOWLIST_BLOCK__/) { print block; next } print }
    ' > "${ACTIVE_CONFIG}"
}

build_sagur_allowlist_block() {
  if [ -z "${SAGUR_IP_ALLOWLIST}" ]; then
    printf '%s\n' 'deny all;'
    return 0
  fi

  OLD_IFS="$IFS"
  IFS=','
  for token in ${SAGUR_IP_ALLOWLIST}; do
    ip="$(echo "${token}" | xargs)"
    if [ -n "${ip}" ]; then
      printf 'allow %s;\n' "${ip}"
    fi
  done
  IFS="$OLD_IFS"
  printf '%s\n' 'deny all;'
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

current_file_mtime() {
  if [ ! -f "$1" ]; then
    echo ""
    return 0
  fi
  stat -c %Y "$1" 2>/dev/null || echo ""
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
LAST_CERT_MTIME="$(current_file_mtime "${CERT_PATH}")"
LAST_KEY_MTIME="$(current_file_mtime "${KEY_PATH}")"

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
    CURRENT_CERT_MTIME="$(current_file_mtime "${CERT_PATH}")"
    CURRENT_KEY_MTIME="$(current_file_mtime "${KEY_PATH}")"
    if [ "${CURRENT_CERT_MTIME}" != "${LAST_CERT_MTIME}" ] || [ "${CURRENT_KEY_MTIME}" != "${LAST_KEY_MTIME}" ]; then
      LAST_CERT_MTIME="${CURRENT_CERT_MTIME}"
      LAST_KEY_MTIME="${CURRENT_KEY_MTIME}"
      CURRENT_TLS_FINGERPRINT="$(current_tls_fingerprint)"
      if [ -n "${CURRENT_TLS_FINGERPRINT}" ] && [ "${CURRENT_TLS_FINGERPRINT}" != "${LAST_TLS_FINGERPRINT}" ]; then
        LAST_TLS_FINGERPRINT="${CURRENT_TLS_FINGERPRINT}"
        echo "[nginx-miniapp] TLS certificate changed, reloading nginx."
        nginx -s reload || true
      fi
    fi
  else
    LAST_TLS_FINGERPRINT=""
    LAST_CERT_MTIME=""
    LAST_KEY_MTIME=""
  fi

  if ! kill -0 "${NGINX_PID}" 2>/dev/null; then
    break
  fi
done

wait "${NGINX_PID}"
