#!/usr/bin/env python3
"""Read-only диагностика инцидентов баланса iiko.

Скрипт собирает факты для ошибки вида `IIKO-BAL-001`: identity, профиль,
тикеты, соседние ошибки, runtime-конфиг iiko и логи контейнеров за окно
инцидента. Все SQL-запросы выполняются внутри транзакции `READ ONLY`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


DEFAULT_PROJECT_DIR = "/var/www/vtelemax"
DEFAULT_BASE_URL = "https://api-ru.iiko.services/api/1"
SAFE_PLATFORMS = {"telegram", "vk", "max"}


def parse_args() -> argparse.Namespace:
    """Разбирает минимальный набор параметров расследования."""

    parser = argparse.ArgumentParser(
        description="Собрать read-only отчет по ошибке получения баланса iiko.",
    )
    parser.add_argument("--platform", default="telegram", choices=sorted(SAFE_PLATFORMS))
    parser.add_argument("--external-id", required=True)
    parser.add_argument("--phone-e164", default="")
    parser.add_argument("--ticket-suffix", default="")
    parser.add_argument("--error-code", default="IIKO-BAL-001")
    parser.add_argument("--incident-local", required=True, help="Например: 2026-05-19 12:05:41")
    parser.add_argument("--timezone", default="Asia/Yekaterinburg")
    parser.add_argument("--window-minutes", type=int, default=30)
    parser.add_argument("--project-dir", default=DEFAULT_PROJECT_DIR)
    parser.add_argument("--report-path", default="")
    parser.add_argument("--max-log-lines", type=int, default=300)
    parser.add_argument(
        "--live-iiko-readonly",
        action="store_true",
        help="Дополнительно выполнить read-only запрос customer/info в iiko.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    """Проверяет параметры до обращения к БД и docker."""

    if not re.fullmatch(r"[A-Za-z0-9:_@.+-]{1,128}", args.external_id):
        raise SystemExit("Некорректный --external-id.")
    if args.phone_e164 and not re.fullmatch(r"\+\d{10,15}", args.phone_e164):
        raise SystemExit("Некорректный --phone-e164. Нужен E.164, например +79829303027.")
    if args.ticket_suffix and not re.fullmatch(r"[A-Fa-f0-9]{1,12}", args.ticket_suffix):
        raise SystemExit("Некорректный --ticket-suffix.")
    if not re.fullmatch(r"IIKO-[A-Z]+-\d{3}", args.error_code):
        raise SystemExit("Некорректный --error-code.")
    if args.window_minutes <= 0 or args.window_minutes > 24 * 60:
        raise SystemExit("--window-minutes должен быть от 1 до 1440.")
    if args.max_log_lines <= 0:
        raise SystemExit("--max-log-lines должен быть положительным.")


def parse_incident_time(raw_value: str, timezone_name: str) -> datetime:
    """Преобразует локальное время инцидента в timezone-aware datetime."""

    normalized = raw_value.strip().replace("T", " ")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise SystemExit("Не удалось разобрать --incident-local.") from error
    if parsed.tzinfo is not None:
        return parsed
    return parsed.replace(tzinfo=ZoneInfo(timezone_name))


def default_report_path(args: argparse.Namespace) -> Path:
    """Формирует путь отчета в /tmp, если он не задан явно."""

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_external_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", args.external_id)
    return Path(f"/tmp/iiko_balance_incident_{safe_external_id}_{stamp}.txt")


def read_env_file(project_dir: Path) -> dict[str, str]:
    """Читает .env без раскрытия секретов наружу."""

    env_path = project_dir / ".env"
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def mask_value(raw_value: str) -> str:
    """Маскирует конфигурационные значения для отчета."""

    value = str(raw_value or "")
    if not value:
        return "EMPTY"
    if len(value) <= 8:
        return f"SET(len={len(value)})"
    return f"{value[:4]}...{value[-4:]} (len={len(value)})"


def render_iiko_config(env_values: dict[str, str]) -> str:
    """Возвращает безопасное представление iiko-конфига."""

    keys = [
        "IIKO_API_KEY",
        "IIKO_ORG_ID",
        "IIKO_BASE_URL",
        "PROFILE_SYNC_ENABLED",
        "PROFILE_SYNC_INTERVAL_SECONDS",
        "PROFILE_SYNC_BATCH_LIMIT",
        "PROFILE_SYNC_MAX_ATTEMPTS",
    ]
    lines = []
    for key in keys:
        value = env_values.get(key, "")
        if key in {"IIKO_API_KEY", "IIKO_ORG_ID"}:
            lines.append(f"{key}={mask_value(value)}")
        else:
            lines.append(f"{key}={value or '<default>'}")
    return "\n".join(lines)


def run_command(
    command: list[str],
    *,
    cwd: Path,
    input_text: str | None = None,
    timeout_seconds: int = 60,
) -> tuple[int, str]:
    """Запускает внешнюю read-only команду и возвращает код + объединенный вывод."""

    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as error:
        return 127, f"command not found: {error}"
    except subprocess.TimeoutExpired as error:
        output = error.stdout or ""
        return 124, f"{output}\nTIMEOUT after {timeout_seconds}s"
    return result.returncode, result.stdout


def shell_join(command: Iterable[str]) -> str:
    """Формирует читаемую строку команды для отчета."""

    return " ".join(shlex.quote(part) for part in command)


def detect_compose(project_dir: Path, report: list[str]) -> list[str]:
    """Определяет доступную команду docker compose."""

    candidates = (["docker", "compose"], ["docker-compose"])
    for candidate in candidates:
        code, output = run_command(candidate + ["version"], cwd=project_dir, timeout_seconds=15)
        report.append(section(f"Проверка команды: {shell_join(candidate + ['version'])}", output))
        if code == 0:
            return list(candidate)
    raise SystemExit("Не удалось найти docker compose/docker-compose.")


def sql_literal(value: str) -> str:
    """Безопасно экранирует строковый литерал для SQL-отчета."""

    return "'" + str(value).replace("'", "''") + "'"


def build_sql(args: argparse.Namespace, window_start_utc: datetime, window_end_utc: datetime) -> str:
    """Собирает read-only SQL-блок диагностики."""

    platform = sql_literal(args.platform)
    external_id = sql_literal(args.external_id)
    phone = sql_literal(args.phone_e164)
    error_code = sql_literal(args.error_code)
    ticket_suffix = sql_literal(args.ticket_suffix.upper())
    window_start = sql_literal(window_start_utc.isoformat())
    window_end = sql_literal(window_end_utc.isoformat())

    return f"""
\\pset footer off
\\x auto
BEGIN READ ONLY;
SET LOCAL statement_timeout = '10s';

\\echo [1] Identity: platform/external_id -> person/profile
SELECT
    pa.platform,
    pa.external_id,
    pa.lifecycle_status,
    pa.created_at AS account_created_at,
    p.person_id,
    ph.phone_e164,
    p.is_registered,
    p.is_legacy,
    p.is_moderator,
    p.phone_verified_at,
    p.phone_verification_method,
    p.first_name_input IS NOT NULL AS has_first_name,
    p.last_name_input IS NOT NULL AS has_last_name,
    p.gender,
    p.birth_date IS NOT NULL AS has_birth_date,
    p.email IS NOT NULL AS has_email,
    pps.rules_accepted AS platform_rules_accepted,
    pps.rules_accepted_at AS platform_rules_accepted_at,
    pps.notifications_allowed AS platform_notifications_allowed,
    pps.notifications_allowed_at AS platform_notifications_allowed_at,
    pps.is_registered AS platform_is_registered,
    pps.registered_at AS platform_registered_at
FROM platform_accounts pa
JOIN persons p ON p.person_id = pa.person_id
LEFT JOIN phones ph ON ph.person_id = p.person_id
LEFT JOIN person_platform_states pps
    ON pps.person_id = p.person_id AND pps.platform = pa.platform
WHERE pa.platform = {platform}
  AND pa.external_id = {external_id}
ORDER BY pa.created_at DESC;

\\echo [2] Accounts attached to the same person
WITH target AS (
    SELECT person_id
    FROM platform_accounts
    WHERE platform = {platform} AND external_id = {external_id}
)
SELECT
    pa.platform,
    pa.external_id,
    pa.lifecycle_status,
    pa.created_at
FROM platform_accounts pa
JOIN target t ON t.person_id = pa.person_id
ORDER BY pa.platform, pa.created_at;

\\echo [3] Phone uniqueness check
SELECT
    ph.phone_e164,
    count(*) AS phones_rows,
    count(DISTINCT ph.person_id) AS persons_count,
    string_agg(ph.person_id::text, ', ' ORDER BY ph.person_id::text) AS person_ids
FROM phones ph
WHERE ({phone} = '' OR ph.phone_e164 = {phone})
GROUP BY ph.phone_e164
ORDER BY ph.phone_e164;

\\echo [4] Target support tickets/messages around incident
WITH target AS (
    SELECT person_id
    FROM platform_accounts
    WHERE platform = {platform} AND external_id = {external_id}
),
ticket_messages AS (
    SELECT
        st.ticket_id,
        string_agg(left(sm.body, 1200), E'\\n--- message ---\\n' ORDER BY sm.created_at) AS bodies
    FROM support_tickets st
    JOIN support_messages sm ON sm.ticket_id = st.ticket_id
    GROUP BY st.ticket_id
)
SELECT
    st.created_at,
    st.updated_at,
    st.status,
    right(st.ticket_id::text, 4) AS ticket_suffix,
    st.ticket_id,
    st.source_platform,
    st.last_guest_platform,
    st.last_guest_external_id,
    tm.bodies
FROM support_tickets st
JOIN target t ON t.person_id = st.person_id
LEFT JOIN ticket_messages tm ON tm.ticket_id = st.ticket_id
WHERE st.created_at BETWEEN {window_start}::timestamptz AND {window_end}::timestamptz
   OR upper(right(st.ticket_id::text, 4)) = {ticket_suffix}
   OR tm.bodies ILIKE '%' || {error_code} || '%'
ORDER BY st.created_at;

\\echo [5] Same error code for other guests in the window
SELECT
    sm.created_at,
    right(st.ticket_id::text, 4) AS ticket_suffix,
    st.ticket_id,
    st.status,
    st.source_platform,
    st.last_guest_platform,
    st.last_guest_external_id,
    ph.phone_e164,
    left(sm.body, 900) AS body_preview
FROM support_messages sm
JOIN support_tickets st ON st.ticket_id = sm.ticket_id
LEFT JOIN phones ph ON ph.person_id = st.person_id
WHERE sm.created_at BETWEEN {window_start}::timestamptz AND {window_end}::timestamptz
  AND sm.body ILIKE '%' || {error_code} || '%'
ORDER BY sm.created_at;

\\echo [6] Profile sync queue for target person and window
WITH target AS (
    SELECT person_id
    FROM platform_accounts
    WHERE platform = {platform} AND external_id = {external_id}
)
SELECT
    q.created_at,
    q.updated_at,
    q.sync_id,
    q.person_id,
    q.source_platform,
    q.status,
    q.attempts,
    q.next_attempt_at,
    q.locked_at,
    left(coalesce(q.error_text, ''), 900) AS error_text_preview
FROM profile_sync_queue q
WHERE q.person_id IN (SELECT person_id FROM target)
   OR q.created_at BETWEEN {window_start}::timestamptz AND {window_end}::timestamptz
ORDER BY q.created_at DESC
LIMIT 50;

ROLLBACK;
"""


def run_psql(compose: list[str], project_dir: Path, sql: str) -> tuple[int, str, str]:
    """Выполняет SQL через psql внутри postgres-контейнера."""

    command = compose + [
        "exec",
        "-T",
        "postgres",
        "sh",
        "-lc",
        'psql -U "${POSTGRES_USER:-postgres}" '
        '-d "${POSTGRES_DB:-postgres}" '
        "-v ON_ERROR_STOP=1 -X -P pager=off -f -",
    ]
    code, output = run_command(command, cwd=project_dir, input_text=sql, timeout_seconds=60)
    return code, shell_join(command), output


def collect_logs(
    compose: list[str],
    args: argparse.Namespace,
    project_dir: Path,
    window_start_utc: datetime,
    window_end_utc: datetime,
) -> tuple[str, str]:
    """Собирает и фильтрует логи сервисов за окно инцидента."""

    since = window_start_utc.isoformat().replace("+00:00", "Z")
    until = window_end_utc.isoformat().replace("+00:00", "Z")
    services = [
        "telegram-bot",
        "telegram-delivery-worker",
        "profile-sync-worker",
        "vk-bot",
        "max-bot",
    ]
    command = compose + [
        "logs",
        "--no-color",
        "--since",
        since,
        "--until",
        until,
        "--tail",
        "2000",
        *services,
    ]
    _, output = run_command(command, cwd=project_dir, timeout_seconds=60)

    needles = {
        args.error_code.lower(),
        args.external_id.lower(),
        args.phone_e164.lower(),
        "balance",
        "баланс",
        "iiko",
        "ticket",
        "тикет",
        "loyalty",
    }
    needles.discard("")
    matched_lines = []
    for line in output.splitlines():
        lowered = line.lower()
        if any(needle in lowered for needle in needles):
            matched_lines.append(line)
        if len(matched_lines) >= args.max_log_lines:
            matched_lines.append(f"... trimmed to {args.max_log_lines} matched log lines ...")
            break

    filtered = "\n".join(matched_lines) if matched_lines else "Совпадений в логах не найдено."
    return shell_join(command), filtered


def live_iiko_probe(args: argparse.Namespace, env_values: dict[str, str]) -> str:
    """Опционально проверяет customer/info в iiko без изменения данных."""

    if not args.phone_e164:
        return "Пропущено: не задан --phone-e164."

    api_key = env_values.get("IIKO_API_KEY", "")
    org_id = env_values.get("IIKO_ORG_ID", "")
    base_url = env_values.get("IIKO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    if not api_key or not org_id:
        return "Пропущено: IIKO_API_KEY/IIKO_ORG_ID не заданы в .env."

    try:
        token_body = post_json(
            url=f"{base_url}/access_token",
            payload={"apiLogin": api_key},
            token=None,
            timeout_seconds=10,
        )
        token = str(token_body.get("token") or "").strip()
        if not token:
            return "Ошибка live-probe: iiko вернул пустой access token."

        customer_body = post_json(
            url=f"{base_url}/loyalty/iiko/customer/info",
            payload={
                "phone": args.phone_e164,
                "type": "phone",
                "organizationId": org_id,
            },
            token=token,
            timeout_seconds=10,
        )
    except HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        return f"HTTPError: status={error.code}, body_preview={raw[:500]}"
    except (TimeoutError, URLError) as error:
        return f"NetworkError: {error}"

    wallets = customer_body.get("walletBalances") or []
    cards = customer_body.get("cards") or []
    balance_values = []
    if isinstance(wallets, list):
        for wallet in wallets:
            if isinstance(wallet, dict) and "balance" in wallet:
                balance_values.append(str(wallet.get("balance")))
    summary = {
        "customer_id_present": bool(str(customer_body.get("id") or "").strip()),
        "wallets_count": len(wallets) if isinstance(wallets, list) else 0,
        "cards_count": len(cards) if isinstance(cards, list) else 0,
        "balance_values": balance_values,
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


def post_json(
    *,
    url: str,
    payload: dict[str, object],
    token: str | None,
    timeout_seconds: int,
) -> dict[str, object]:
    """Выполняет POST JSON и возвращает JSON-объект."""

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        url=url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(raw or "{}")
    return parsed if isinstance(parsed, dict) else {}


def section(title: str, body: str) -> str:
    """Форматирует секцию отчета."""

    return f"\n\n===== {title} =====\n{body.strip()}\n"


def main() -> int:
    """Точка входа диагностического скрипта."""

    args = parse_args()
    validate_args(args)

    project_dir = Path(args.project_dir).resolve()
    report_path = Path(args.report_path) if args.report_path else default_report_path(args)
    incident_local = parse_incident_time(args.incident_local, args.timezone)
    incident_utc = incident_local.astimezone(timezone.utc)
    window_delta = timedelta(minutes=args.window_minutes)
    window_start_utc = incident_utc - window_delta
    window_end_utc = incident_utc + window_delta

    report: list[str] = []
    report.append(
        "IIKO balance incident read-only report\n"
        f"generated_at_utc={datetime.now(timezone.utc).isoformat()}\n"
        f"project_dir={project_dir}\n"
        f"platform={args.platform}\n"
        f"external_id={args.external_id}\n"
        f"phone_e164={args.phone_e164 or '<not provided>'}\n"
        f"ticket_suffix={args.ticket_suffix or '<not provided>'}\n"
        f"error_code={args.error_code}\n"
        f"incident_local={incident_local.isoformat()}\n"
        f"incident_utc={incident_utc.isoformat()}\n"
        f"window_utc={window_start_utc.isoformat()} .. {window_end_utc.isoformat()}\n"
    )

    env_values = read_env_file(project_dir)
    report.append(section("Runtime iiko config (.env masked)", render_iiko_config(env_values)))

    compose = detect_compose(project_dir, report)
    ps_code, ps_command, ps_output = run_command_with_text(
        compose + ["ps"],
        project_dir=project_dir,
        timeout_seconds=30,
    )
    report.append(section(f"Команда: {ps_command} (exit={ps_code})", ps_output))

    sql = build_sql(args, window_start_utc, window_end_utc)
    psql_code, psql_command, psql_output = run_psql(compose, project_dir, sql)
    report.append(section(f"Команда SQL: {psql_command} (exit={psql_code})", psql_output))

    logs_command, logs_output = collect_logs(
        compose,
        args,
        project_dir,
        window_start_utc,
        window_end_utc,
    )
    report.append(section(f"Команда логов: {logs_command}", logs_output))

    if args.live_iiko_readonly:
        report.append(section("Live iiko customer/info read-only probe", live_iiko_probe(args, env_values)))
    else:
        report.append(section("Live iiko customer/info read-only probe", "Пропущено: флаг не задан."))

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("".join(report), encoding="utf-8")
    print(f"REPORT_PATH={report_path}")
    return 0 if psql_code == 0 else 2


def run_command_with_text(
    command: list[str],
    *,
    project_dir: Path,
    timeout_seconds: int,
) -> tuple[int, str, str]:
    """Запускает команду и сразу возвращает printable-представление."""

    code, output = run_command(command, cwd=project_dir, timeout_seconds=timeout_seconds)
    return code, shell_join(command), output


if __name__ == "__main__":
    sys.exit(main())
