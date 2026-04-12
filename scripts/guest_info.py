"""CLI-утилита получения детальной информации о госте по телефону.

Сценарий:

1. Находит пользователя по телефону в формате E.164.
2. Показывает данные профиля и платформенные состояния регистрации.
3. Поддерживает форматы вывода: таблица, JSON и сырой SQL-вид.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from vtelemax.core import normalize_phone
from vtelemax.infrastructure.postgres import build_engine
from vtelemax.settings import AppSettings
from vtelemax.tools.guest_info import (
    GuestInfo,
    get_guest_info_by_phone,
    get_guest_info_rows_by_phone,
)


def _format_datetime(value: datetime | None) -> str:
    """Форматирует дату/время для читаемого вывода."""

    return value.isoformat() if value is not None else "NULL"


def _build_parser() -> argparse.ArgumentParser:
    """Создает parser аргументов командной строки."""

    parser = argparse.ArgumentParser(
        description=(
            "Показывает детальную информацию о госте по телефону "
            "для платформ telegram/vk/max."
        )
    )
    parser.add_argument(
        "--phone",
        required=True,
        help="Телефон пользователя (например, +79991234567).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Вывести результат в формате JSON.",
    )
    parser.add_argument(
        "--raw-sql",
        action="store_true",
        help="Вывести сырой результат SQL-выборки (как таблицу строк).",
    )
    return parser


def _print_guest_table(guest_info: GuestInfo) -> None:
    """Печатает сводку гостя и платформенных состояний в табличном формате."""

    print(f"Person ID: {guest_info.person_id}")
    print(f"Телефон: {guest_info.phone_e164}")
    print(f"Legacy: {guest_info.is_legacy}")
    print(f"Профиль зарегистрирован: {guest_info.profile_is_registered}")
    print(f"Имя: {guest_info.first_name_input or 'NULL'}")
    print(f"Метод верификации телефона: {guest_info.phone_verification_method or 'NULL'}")
    print()
    print("Платформы:")
    print("-" * 160)
    print(
        f"{'Platform':<10} {'External ID':<24} {'Rules':<6} {'Rules At':<28} "
        f"{'Notif':<6} {'Notif At':<28} {'Registered':<10} {'Registered At':<28}"
    )
    print("-" * 160)

    for platform in guest_info.platforms:
        rules = "✓" if platform.rules_accepted else "✗" if platform.rules_accepted is False else "NULL"
        notif = "✓" if platform.notifications_allowed else "✗" if platform.notifications_allowed is False else "NULL"
        reg = "✓" if platform.is_registered else "✗" if platform.is_registered is False else "NULL"
        print(
            f"{platform.platform:<10} "
            f"{(platform.external_id or 'NULL'):<24} "
            f"{rules:<6} {_format_datetime(platform.rules_accepted_at):<28} "
            f"{notif:<6} {_format_datetime(platform.notifications_allowed_at):<28} "
            f"{reg:<10} {_format_datetime(platform.registered_at):<28}"
        )
    print("-" * 160)


def _print_guest_json(guest_info: GuestInfo) -> None:
    """Печатает сводку гостя в JSON-формате."""

    data: dict[str, Any] = {
        "person_id": str(guest_info.person_id),
        "phone_e164": guest_info.phone_e164,
        "is_legacy": guest_info.is_legacy,
        "profile_is_registered": guest_info.profile_is_registered,
        "first_name_input": guest_info.first_name_input,
        "phone_verification_method": guest_info.phone_verification_method,
        "platforms": [
            {
                "platform": p.platform,
                "external_id": p.external_id,
                "rules_accepted": p.rules_accepted,
                "rules_accepted_at": p.rules_accepted_at.isoformat() if p.rules_accepted_at else None,
                "notifications_allowed": p.notifications_allowed,
                "notifications_allowed_at": p.notifications_allowed_at.isoformat() if p.notifications_allowed_at else None,
                "is_registered": p.is_registered,
                "registered_at": p.registered_at.isoformat() if p.registered_at else None,
            }
            for p in guest_info.platforms
        ],
    }
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _print_raw_rows(rows: tuple[dict[str, Any], ...]) -> None:
    """Печатает сырой SQL-вид строк результата."""

    if not rows:
        print("Нет данных.")
        return

    headers = list(rows[0].keys())
    print(" | ".join(headers))
    print("-" * 180)
    for row in rows:
        values: list[str] = []
        for header in headers:
            value = row.get(header)
            if value is None:
                values.append("NULL")
            elif isinstance(value, datetime):
                values.append(value.isoformat())
            else:
                values.append(str(value))
        print(" | ".join(values))


def main() -> int:
    """Точка входа CLI-утилиты."""

    parser = _build_parser()
    args = parser.parse_args()

    try:
        phone_e164 = normalize_phone(args.phone)
    except ValueError as error:
        print(f"[guest-info] Некорректный номер телефона: {error}", file=sys.stderr)
        return 2

    settings = AppSettings()
    engine = build_engine(settings.postgres_sqlalchemy_dsn, echo=settings.postgres_echo)

    with Session(engine) as session:
        rows = get_guest_info_rows_by_phone(session, phone_e164)
        if not rows:
            print(f"[guest-info] Пользователь с телефоном {phone_e164} не найден в PostgreSQL.")
            return 1

        if args.raw_sql:
            _print_raw_rows(rows)
            return 0

        guest_info = get_guest_info_by_phone(session, phone_e164)
        if guest_info is None:
            print(f"[guest-info] Пользователь с телефоном {phone_e164} не найден в PostgreSQL.")
            return 1

        if args.json:
            _print_guest_json(guest_info)
        else:
            _print_guest_table(guest_info)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

