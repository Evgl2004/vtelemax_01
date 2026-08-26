"""Тесты read-only диагностического скрипта iiko."""

from __future__ import annotations

import argparse
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "diagnose_iiko_balance_incident.py"
SPEC = importlib.util.spec_from_file_location("diagnose_iiko_balance_incident", SCRIPT_PATH)
assert SPEC is not None
diagnostic_script = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(diagnostic_script)


def test_normalize_error_codes_accepts_repeated_and_comma_separated_values() -> None:
    """Проверяет, что CLI может принимать несколько iiko-кодов без дублей."""

    assert diagnostic_script.normalize_error_codes(
        ["iiko-card-001, IIKO-CARD-003", "IIKO-CARD-001"]
    ) == ("IIKO-CARD-001", "IIKO-CARD-003")


def test_render_known_codes_contains_balance_and_card_codes() -> None:
    """Проверяет справочник кодов для оператора диагностики."""

    output = diagnostic_script.render_known_codes()

    assert "IIKO-BAL-001" in output
    assert "IIKO-CARD-003" in output


def test_validate_args_sets_primary_error_code_for_card_incident() -> None:
    """Проверяет валидацию параметров для ошибки виртуальной карты."""

    args = argparse.Namespace(
        external_id="5833652675",
        phone_e164="+79829303027",
        ticket_suffix="8E5D",
        error_code=["IIKO-CARD-003"],
        incident_local="2026-05-19 12:05:41",
        window_minutes=10,
        max_log_lines=50,
    )

    diagnostic_script.validate_args(args)

    assert args.error_codes == ("IIKO-CARD-003",)
    assert args.primary_error_code == "IIKO-CARD-003"


def test_validate_args_rejects_invalid_iiko_code() -> None:
    """Проверяет, что некорректный код не попадет в SQL/логи."""

    args = argparse.Namespace(
        external_id="5833652675",
        phone_e164="",
        ticket_suffix="",
        error_code=["BAD-CODE"],
        incident_local="2026-05-19 12:05:41",
        window_minutes=10,
        max_log_lines=50,
    )

    with pytest.raises(SystemExit):
        diagnostic_script.validate_args(args)


def test_build_sql_searches_all_error_codes_read_only() -> None:
    """Проверяет, что SQL остается read-only и ищет все переданные коды."""

    args = argparse.Namespace(
        platform="telegram",
        external_id="5833652675",
        phone_e164="+79829303027",
        ticket_suffix="8E5D",
        error_codes=("IIKO-BAL-001", "IIKO-CARD-001"),
    )
    sql = diagnostic_script.build_sql(
        args,
        datetime(2026, 5, 19, 7, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 19, 7, 10, tzinfo=timezone.utc),
    )

    assert "BEGIN READ ONLY" in sql
    assert "ROLLBACK" in sql
    assert "ILIKE ANY" in sql
    assert "Same iiko error codes for other tickets" in sql
    assert "count(DISTINCT sm.message_id) AS matched_messages_count" in sql
    assert "string_agg(DISTINCT matched.code" in sql
    assert "GROUP BY\n    st.ticket_id" in sql
    assert "%IIKO-BAL-001%" in sql
    assert "%IIKO-CARD-001%" in sql


def test_build_sql_limits_phone_check_to_target_person_when_phone_missing() -> None:
    """Проверяет, что отчет без телефона не разворачивает всю таблицу phones."""

    args = argparse.Namespace(
        platform="max",
        external_id="210098639",
        phone_e164="",
        ticket_suffix="78A8",
        error_codes=("IIKO-BAL-001",),
    )
    sql = diagnostic_script.build_sql(
        args,
        datetime(2026, 4, 22, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 22, 10, 20, tzinfo=timezone.utc),
    )

    assert "OR ('' = '' AND ph.person_id IN (SELECT person_id FROM target))" in sql
    assert "WHERE ('' = '' OR ph.phone_e164 = '')" not in sql


def test_render_iiko_config_masks_new_authentication_parameters() -> None:
    """Проверяет маскирование новых реквизитов авторизации в отчёте."""

    output = diagnostic_script.render_iiko_config(
        {
            "IIKO_AUTH_VERSION": "v2",
            "IIKO_APP_ID": "application-id",
            "IIKO_CLIENT_SECRET": "client-secret-value",
            "IIKO_CLOUD_API_KEY": "cloud-api-key-value",
            "IIKO_ORG_ID": "organization-id",
            "IIKO_AUTH_URL": "https://example.test/api/v2/access_token",
        }
    )

    assert "IIKO_AUTH_VERSION=v2" in output
    assert "application-id" not in output
    assert "client-secret-value" not in output
    assert "cloud-api-key-value" not in output
    assert "organization-id" not in output
    assert "IIKO_AUTH_URL=https://example.test/api/v2/access_token" in output


def test_live_iiko_probe_can_explicitly_use_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Проверяет отдельный диагностический запрос через новую авторизацию."""

    calls: list[dict[str, object]] = []
    responses = [
        {"token": "v2-token"},
        {
            "id": "customer-1",
            "walletBalances": [{"balance": 125}],
            "cards": [{"number": "card-1"}],
        },
    ]

    def fake_post_json(
        *,
        url: str,
        payload: dict[str, object],
        token: str | None,
        timeout_seconds: int,
    ) -> dict[str, object]:
        calls.append(
            {
                "url": url,
                "payload": payload,
                "token": token,
                "timeout_seconds": timeout_seconds,
            }
        )
        return responses.pop(0)

    monkeypatch.setattr(diagnostic_script, "post_json", fake_post_json)
    args = argparse.Namespace(
        phone_e164="+79120000000",
        iiko_auth_version="v2",
    )
    env_values = {
        "IIKO_AUTH_VERSION": "v1",
        "IIKO_APP_ID": "app-id",
        "IIKO_CLIENT_SECRET": "client-secret",
        "IIKO_CLOUD_API_KEY": "cloud-key",
        "IIKO_ORG_ID": "org-1",
        "IIKO_AUTH_URL": "https://example.test/api/v2/access_token",
        "IIKO_BASE_URL": "https://example.test/api/1",
    }

    output = diagnostic_script.live_iiko_probe(args, env_values)

    assert '"customer_id_present": true' in output
    assert calls == [
        {
            "url": "https://example.test/api/v2/access_token",
            "payload": {
                "appId": "app-id",
                "clientSecret": "client-secret",
                "apiKey": "cloud-key",
            },
            "token": None,
            "timeout_seconds": 10,
        },
        {
            "url": "https://example.test/api/1/loyalty/iiko/customer/info",
            "payload": {
                "phone": "+79120000000",
                "type": "phone",
                "organizationId": "org-1",
            },
            "token": "v2-token",
            "timeout_seconds": 10,
        },
    ]
