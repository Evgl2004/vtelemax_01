"""Тесты утилит точечной очистки тестового пользователя."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from vtelemax.infrastructure.postgres import (
    Base,
    PersonRow,
    PhoneRow,
    PlatformAccountRow,
    SupportMessageRow,
    SupportTicketRow,
)
from vtelemax.tools.user_reset import (
    PersonResetAccount,
    build_default_redis_patterns,
    collect_matching_redis_keys,
    delete_person_by_id,
    delete_redis_keys,
    get_person_snapshot_by_phone,
)


@dataclass
class _FakeRedis:
    """Минимальная тестовая реализация Redis-клиента для scan/delete."""

    keys: list[str]

    def scan_iter(self, match: str | None = None, count: int = 1000):  # noqa: ARG002
        for key in self.keys:
            if match is None or fnmatch.fnmatch(key, match):
                yield key.encode("utf-8")

    def delete(self, *keys: str) -> int:
        before = set(self.keys)
        to_delete = set(keys)
        self.keys = [key for key in self.keys if key not in to_delete]
        return len(before - set(self.keys))


def test_build_default_redis_patterns_contains_phone_and_accounts() -> None:
    """Проверяет формирование default-шаблонов Redis по телефону и аккаунтам."""

    patterns = build_default_redis_patterns(
        phone_e164="+79991234567",
        accounts=(
            PersonResetAccount(platform="telegram", external_id="571682735"),
            PersonResetAccount(platform="vk", external_id="1069961024"),
        ),
    )

    assert any("+79991234567" in pattern for pattern in patterns)
    assert any("79991234567" in pattern for pattern in patterns)
    assert any("telegram" in pattern and "571682735" in pattern for pattern in patterns)
    assert any("vk" in pattern and "1069961024" in pattern for pattern in patterns)


def test_collect_matching_redis_keys_deduplicates_keys() -> None:
    """Проверяет дедупликацию ключей, совпавших сразу по нескольким шаблонам."""

    redis_client = _FakeRedis(
        keys=[
            "vtelemax:state:telegram:571682735",
            "vtelemax:state:vk:1069961024",
            "other:key",
        ]
    )
    patterns = [
        "vtelemax:*571682735*",
        "vtelemax:state:*",
    ]

    matched = collect_matching_redis_keys(redis_client, patterns, scan_count=10)

    assert matched == [
        "vtelemax:state:telegram:571682735",
        "vtelemax:state:vk:1069961024",
    ]


def test_delete_redis_keys_returns_deleted_count() -> None:
    """Проверяет количество удаленных ключей в Redis helper."""

    redis_client = _FakeRedis(
        keys=[
            "vtelemax:state:telegram:1",
            "vtelemax:state:vk:2",
        ]
    )

    deleted = delete_redis_keys(redis_client, ["vtelemax:state:vk:2"])

    assert deleted == 1
    assert redis_client.keys == ["vtelemax:state:telegram:1"]


def test_get_snapshot_and_delete_person_cascade() -> None:
    """Проверяет снимок пользователя и каскадное удаление из PostgreSQL."""

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    # Для SQLite каскадные удаления по FK нужно явно включать через PRAGMA.
    event.listen(
        engine,
        "connect",
        lambda dbapi_connection, _: dbapi_connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)

    person_id = uuid4()
    phone_id = uuid4()
    account_tg_id = uuid4()
    account_vk_id = uuid4()
    ticket_id = uuid4()
    message_id = uuid4()

    with Session(engine) as session:
        session.add(PersonRow(person_id=person_id))
        session.add(PhoneRow(phone_id=phone_id, person_id=person_id, phone_e164="+79991234567"))
        session.add(
            PlatformAccountRow(
                account_id=account_tg_id,
                person_id=person_id,
                platform="telegram",
                external_id="571682735",
            )
        )
        session.add(
            PlatformAccountRow(
                account_id=account_vk_id,
                person_id=person_id,
                platform="vk",
                external_id="1069961024",
            )
        )
        session.add(
            SupportTicketRow(
                ticket_id=ticket_id,
                person_id=person_id,
                source_platform="telegram",
            )
        )
        session.flush()
        session.add(
            SupportMessageRow(
                message_id=message_id,
                ticket_id=ticket_id,
                author="guest",
                body="Тестовый вопрос",
                source_platform="telegram",
            )
        )
        session.commit()

        snapshot = get_person_snapshot_by_phone(session, "+79991234567")
        assert snapshot is not None
        assert snapshot.person_id == person_id
        assert snapshot.tickets_count == 1
        assert snapshot.messages_count == 1
        assert len(snapshot.accounts) == 2

        deleted_count = delete_person_by_id(session, person_id)
        session.commit()
        assert deleted_count == 1

        assert get_person_snapshot_by_phone(session, "+79991234567") is None
        assert session.execute(select(PersonRow)).scalars().all() == []
        assert session.execute(select(PhoneRow)).scalars().all() == []
        assert session.execute(select(PlatformAccountRow)).scalars().all() == []
        assert session.execute(select(SupportTicketRow)).scalars().all() == []
        assert session.execute(select(SupportMessageRow)).scalars().all() == []
