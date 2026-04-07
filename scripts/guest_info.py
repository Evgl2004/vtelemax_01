"""CLI-утилита для получения детальной информации о госте по телефону.

Сценарий:
1. Находит пользователя по телефону в формате E.164.
2. Выполняет SQL-запрос, аналогичный ручному запросу через docker compose exec.
3. Выводит структурированные данные по всем трём платформам (telegram, vk, max).

Пример использования:
    python scripts/guest_info.py --phone +79129923438
    python scripts/guest_info.py --phone +79129923438 --json
    python scripts/guest_info.py --phone +79129923438 --raw-sql
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
from vtelemax.tools.guest_info import get_guest_info_by_phone, GuestInfo, GuestPlatformInfo


def _format_datetime(dt: datetime | None) -> str | None:
    """Форматирует datetime в строку ISO для JSON."""
    return dt.isoformat() if dt else None


def _print_table(guest_info: GuestInfo) -> None:
    """Выводит информацию о госте в виде таблицы."""
    print(f"Person ID: {guest_info.person_id}")
    print(f"Телефон: {guest_info.phone_e164}")
    print(f"Legacy: {guest_info.is_legacy}")
    print(f"Профиль зарегистрирован: {guest_info.profile_is_registered}")
    print(f"Имя: {guest_info.first_name_input or 'NULL'}")
    print(f"Метод верификации телефона: {guest_info.phone_verification_method or 'NULL'}")
    print()
    print("Платформы:")
    print("-" * 120)
    print(
        f"{'Platform':<10} {'External ID':<30} {'Rules':<6} {'Rules At':<20} "
        f"{'Notif':<6} {'Notif At':<20} {'Registered':<10} {'Registered At':<20}"
    )
    print("-" * 120)
    for platform in guest_info.platforms:
        rules_accepted = "✓" if platform.rules_accepted else "✗" if platform.rules_accepted is False else "NULL"
        notifications_allowed = "✓" if platform.notifications_allowed else "✗" if platform.notifications_allowed is False else "NULL"
        is_registered = "✓" if platform.is_registered else "✗" if platform.is_registered is False else "NULL"
        rules_at = platform.rules_accepted_at.isoformat() if platform.rules_accepted_at else "NULL"
        notif_at = platform.notifications_allowed_at.isoformat() if platform.notifications_allowed_at else "NULL"
        registered_at = platform.registered_at.isoformat() if platform.registered_at else "NULL"
        print(
            f"{platform.platform:<10} {platform.external_id or 'NULL':<30} "
            f"{rules_accepted:<6} {rules_at:<20} "
            f"{notifications_allowed:<6} {notif_at:<20} "
            f"{is_registered:<10} {registered_at:<20}"
        )
    print("-" * 120)


def _print_json(guest_info: GuestInfo) -> None:
    """Выводит информацию о госте в формате JSON."""
    def serialize(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, GuestPlatformInfo):
            return {
                "platform": obj.platform,
                "external_id": obj.external_id,
                "rules_accepted": obj.rules_accepted,
                "rules_accepted_at": _format_datetime(obj.rules_accepted_at),
                "notifications_allowed": obj.notifications_allowed,
                "notifications_allowed_at": _format_datetime(obj.notifications_allowed_at),
                "is_registered": obj.is_registered,
                "registered_at": _format_datetime(obj.registered_at),
            }
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    data = {
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
                "rules_accepted_at": _format_datetime(p.rules_accepted_at),
                "notifications_allowed": p.notifications_allowed,
                "notifications_allowed_at": _format_datetime(p.notifications_allowed_at),
                "is_registered": p.is_registered,
                "registered_at": _format_datetime(p.registered_at),
            }
            for p in guest_info.platforms
        ],
    }
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _print_raw_sql(session: Session, phone_e164: str) -> None:
    """Выполняет и выводит сырой SQL-запрос (как в исходной задаче)."""
    from sqlalchemy import text
    sql = """
    WITH target AS (
        SELECT
            p.person_id,
            ph.phone_e164,
            p.is_legacy,
            p.is_registered AS profile_is_registered,
            p.first_name_input,
            p.phone_verification_method
        FROM persons p
        JOIN phones ph ON ph.person_id = p.person_id
        WHERE ph.phone_e164 = :phone_e164
    ),
    platforms AS (
        SELECT unnest(ARRAY['telegram','vk','max'])::varchar(16) AS platform
    )
    SELECT
        t.person_id,
        t.phone_e164,
        pl.platform,
        pa.external_id,
        s.rules_accepted,
        s.rules_accepted_at,
        s.notifications_allowed,
        s.notifications_allowed_at,
        s.is_registered AS platform_is_registered,
        s.registered_at,
        t.profile_is_registered,
        t.is_legacy,
        t.first_name_input,
        t.phone_verification_method
    FROM target t
    CROSS JOIN platforms pl
    LEFT JOIN person_platform_states s
        ON s.person_id = t.person_id AND s.platform = pl.platform
    LEFT JOIN platform_accounts pa
        ON pa.person_id = t.person_id AND pa.platform = pl.platform
    ORDER BY CASE pl.platform
        WHEN 'telegram' THEN 1
        WHEN 'vk' THEN 2
        WHEN 'max' THEN 3
        ELSE 99
    END;
    """
    result = session.execute(text(sql), {"phone_e164": phone_e164})
    rows = result.all()
    if not rows:
        print(f"Телефон {phone_e164} не найден.")
        return

    # Заголовки
    headers = [
        "person_id", "phone_e164", "platform", "external_id",
        "rules_accepted", "rules_accepted_at", "notifications_allowed", "notifications_allowed_at",
        "platform_is_registered", "registered_at",
        "profile_is_registered", "is_legacy", "first_name_input", "phone_verification_method"
    ]
    print(" | ".join(headers))
    print("-" * 150)
    for row in rows:
        values = []
        for val in row:
            if val is None:
                values.append("NULL")
            elif isinstance(val, datetime):
                values.append(val.isoformat())
            else:
                values.append(str(val))
        print(" | ".join(values))


def _build_parser() -> argparse.ArgumentParser:
    """Создает parser аргументов командной строки."""
    parser = argparse.ArgumentParser(
        description=(
            "Выводит детальную информацию о госте по номеру телефона "
            "по всем трём платформам (telegram, vk, max)."
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
        help="Вывести сырой результат SQL-запроса (таблицей).",
    )
    return parser


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
        if args.raw_sql:
            _print_raw_sql(session, phone_e164)
            return 0

        guest_info = get_guest_info_by_phone(session, phone_e164)
        if guest_info is None:
            print(f"[guest-info] Пользователь с телефоном {phone_e164} не найден в PostgreSQL.")
            return 1

        if args.json:
            _print_json(guest_info)
        else:
            _print_table(guest_info)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())