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
    assert "%IIKO-BAL-001%" in sql
    assert "%IIKO-CARD-001%" in sql
