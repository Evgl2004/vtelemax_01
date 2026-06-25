"""Unit-тесты read-моделей репозитория купонов SAGUR."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy import select
from sqlalchemy.orm import Session

from vtelemax.infrastructure.postgres import (
    Base,
    CouponAlreadyAssignedError,
    PersonCouponRow,
    PersonRow,
    SagurCouponEventRow,
    SQLAlchemySagurCouponsRepository,
    build_session_factory,
)


def test_coupon_ui_reads_hide_inactive_statuses_even_when_visible_flag_is_true() -> None:
    """Проверяет защиту от старых данных: неактивные статусы не попадают в UI-списки."""

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    person_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    now = datetime(2026, 5, 15, 8, 30, tzinfo=timezone.utc)

    with session_factory() as session:
        session.add(PersonRow(person_id=person_id))
        session.add_all(
            [
                _coupon_row(
                    coupon_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
                    person_id=person_id,
                    coupon_code="GLOBAL-SENT",
                    venue_code="__global__",
                    status="sent",
                    now=now,
                ),
                _coupon_row(
                    coupon_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
                    person_id=person_id,
                    coupon_code="GLOBAL-EXPIRED",
                    venue_code="__global__",
                    status="expired",
                    now=now,
                ),
                _coupon_row(
                    coupon_id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
                    person_id=person_id,
                    coupon_code="NANI-SENT",
                    venue_code="nani",
                    venue_name="Грузинка Нани",
                    status="sent",
                    now=now,
                ),
                _coupon_row(
                    coupon_id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
                    person_id=person_id,
                    coupon_code="NANI-USED",
                    venue_code="nani",
                    venue_name="Грузинка Нани",
                    status="used",
                    now=now,
                ),
                _coupon_row(
                    coupon_id=UUID("99999999-9999-4999-8999-999999999999"),
                    person_id=person_id,
                    coupon_code="NANI-USED-LATE",
                    venue_code="nani",
                    venue_name="Р“СЂСѓР·РёРЅРєР° РќР°РЅРё",
                    status="used_after_campaign",
                    now=now,
                ),
                _coupon_row(
                    coupon_id=UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
                    person_id=person_id,
                    coupon_code="SUSAMI-CANCELED",
                    venue_code="susami",
                    venue_name="Сами Сусами",
                    status="canceled",
                    now=now,
                ),
            ]
        )
        session.commit()

    with session_factory() as session:
        repository = SQLAlchemySagurCouponsRepository(session)

        assert repository.count_visible_global_coupons(person_id=person_id) == 1

        venues = repository.list_visible_venues(person_id=person_id)
        assert [(venue.venue_code, venue.coupons_count) for venue in venues] == [("nani", 1)]

        coupons = repository.list_visible_coupons(person_id=person_id, venue_code="nani")
        assert [coupon.coupon_code for coupon in coupons] == ["NANI-SENT"]


def test_status_update_canceled_releases_coupon_and_allows_reassignment() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    first_person_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    second_person_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    coupon_series = "SER-REUSE"
    coupon_code = "REUSE-2026-0001"
    now = datetime(2026, 5, 15, 9, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        session.add_all(
            [
                PersonRow(person_id=first_person_id),
                PersonRow(person_id=second_person_id),
            ]
        )
        session.commit()

        repository = SQLAlchemySagurCouponsRepository(session)
        assignment_event_id = uuid4()
        assigned = repository.apply_event(
            event_id=assignment_event_id,
            direction="assignments",
            sent_at=now,
            payload_raw={
                "campaign_id": "CMP-CANCEL-1",
                "assignment_id": "ASN-1",
                "person_id": str(first_person_id),
                "phone_e164": "+79990000001",
                "coupon_series": coupon_series,
                "coupon_code": coupon_code,
                "venue_code": "nani",
                "venue_name": "Nani",
                "promo_text": "Dessert",
                "status": "reserved",
            },
        )
        session.commit()

        assert assigned.deduplicated is False
        assert assigned.coupon_id is not None
        assert repository.list_visible_coupons(person_id=first_person_id, venue_code="nani")

        cancel_event_id = uuid4()
        canceled = repository.apply_event(
            event_id=cancel_event_id,
            direction="status_update",
            sent_at=now,
            payload_raw={
                "campaign_id": "CMP-CANCEL-1",
                "assignment_id": "ASN-1",
                "person_id": str(first_person_id),
                "phone_e164": "+79990000001",
                "coupon_series": coupon_series,
                "coupon_code": coupon_code,
                "status": "canceled",
                "status_at": "2026-05-15T09:01:00Z",
                "meta": {"cancel_reason": "campaign_cancelled"},
            },
        )
        session.commit()

        assert canceled.deduplicated is False
        assert canceled.coupon_id == assigned.coupon_id
        assert repository.list_visible_coupons(person_id=first_person_id, venue_code="nani") == ()
        assert _person_coupon_rows(session, coupon_code=coupon_code) == ()
        assert session.get(SagurCouponEventRow, cancel_event_id) is not None

        duplicate_cancel = repository.apply_event(
            event_id=cancel_event_id,
            direction="status_update",
            sent_at=now,
            payload_raw={
                "person_id": str(first_person_id),
                "coupon_series": coupon_series,
                "coupon_code": coupon_code,
                "status": "canceled",
            },
        )
        session.commit()

        assert duplicate_cancel.deduplicated is True
        assert _person_coupon_rows(session, coupon_code=coupon_code) == ()

        repeated_cancel = repository.apply_event(
            event_id=uuid4(),
            direction="status_update",
            sent_at=now,
            payload_raw={
                "campaign_id": "CMP-CANCEL-1",
                "assignment_id": "ASN-1",
                "person_id": str(first_person_id),
                "phone_e164": "+79990000001",
                "coupon_series": coupon_series,
                "coupon_code": coupon_code,
                "status": "canceled",
            },
        )
        session.commit()

        assert repeated_cancel.deduplicated is False
        assert repeated_cancel.coupon_id is None
        assert _person_coupon_rows(session, coupon_code=coupon_code) == ()

        reassigned = repository.apply_event(
            event_id=uuid4(),
            direction="assignments",
            sent_at=now,
            payload_raw={
                "campaign_id": "CMP-CANCEL-2",
                "assignment_id": "ASN-2",
                "person_id": str(second_person_id),
                "phone_e164": "+79990000002",
                "coupon_series": coupon_series,
                "coupon_code": coupon_code,
                "venue_code": "susami",
                "venue_name": "Susami",
                "promo_text": "Tea",
                "status": "reserved",
            },
        )
        session.commit()

        assert reassigned.deduplicated is False
        assert reassigned.coupon_id is not None
        assert reassigned.coupon_id != assigned.coupon_id
        assert repository.list_visible_coupons(person_id=first_person_id, venue_code="nani") == ()
        second_person_coupons = repository.list_visible_coupons(
            person_id=second_person_id,
            venue_code="susami",
        )
        assert [coupon.coupon_code for coupon in second_person_coupons] == [coupon_code]
        assert [row.person_id for row in _person_coupon_rows(session, coupon_code=coupon_code)] == [
            second_person_id
        ]


def test_apply_event_flushes_coupon_event_before_coupon_row_for_fk_order() -> None:
    """Проверяет порядок записи события и купона при включенных FK как в PostgreSQL."""

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @event.listens_for(engine, "connect")
    def _set_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    person_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    event_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    now = datetime(2026, 5, 18, 12, 23, tzinfo=timezone.utc)

    with session_factory() as session:
        session.add(PersonRow(person_id=person_id))
        session.commit()

        repository = SQLAlchemySagurCouponsRepository(session)
        applied = repository.apply_event(
            event_id=event_id,
            direction="assignments",
            sent_at=now,
            payload_raw={
                "person_id": str(person_id),
                "coupon_series": "E2E_SAMI_20260516_0732",
                "coupon_code": "E2E-OVT89GWN",
                "venue_code": "c9a0df27-11dc-4bee-83a3-f0a5aa16c185",
                "venue_name": "Сами Сусами",
                "promo_text": "Подарок по персональному купону E2E-OVT89GWN.",
                "status": "reserved",
            },
        )
        session.commit()

        assert applied.deduplicated is False
        assert session.get(SagurCouponEventRow, event_id) is not None
        rows = _person_coupon_rows(session, coupon_code="E2E-OVT89GWN")
        assert len(rows) == 1
        assert rows[0].last_event_id == event_id


def test_assignments_store_valid_until_and_status_update_preserves_it_when_missing() -> None:
    """Проверяет хранение срока действия купона из machine-readable поля valid_until."""

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    person_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    coupon_code = "VALID-UNTIL-0001"
    now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)
    expected_valid_until = datetime(2026, 5, 18, 18, 59, 59, tzinfo=timezone.utc)

    with session_factory() as session:
        session.add(PersonRow(person_id=person_id))
        session.commit()

        repository = SQLAlchemySagurCouponsRepository(session)
        repository.apply_event(
            event_id=uuid4(),
            direction="assignments",
            sent_at=now,
            payload_raw={
                "person_id": str(person_id),
                "coupon_series": "SER-VALID",
                "coupon_code": coupon_code,
                "venue_code": "susami",
                "venue_name": "Сами Сусами",
                "promo_text": "Кофе по купону",
                "status": "reserved",
                "valid_until": "2026-05-18T23:59:59+05:00",
            },
        )
        session.commit()

        row = _person_coupon_rows(session, coupon_code=coupon_code)[0]
        assert _as_aware_utc(row.valid_until) == expected_valid_until

        repository.apply_event(
            event_id=uuid4(),
            direction="status_update",
            sent_at=now,
            payload_raw={
                "person_id": str(person_id),
                "coupon_series": "SER-VALID",
                "coupon_code": coupon_code,
                "status": "used",
            },
        )
        session.commit()

    row = _person_coupon_rows(session, coupon_code=coupon_code)[0]
    assert row.status == "used"
    assert _as_aware_utc(row.valid_until) == expected_valid_until


def test_coupon_title_is_stored_updated_and_not_erased_by_missing_status_update() -> None:
    """Проверяет безопасное хранение пользовательского названия купона из SAGUR."""

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    person_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    coupon_code = "TITLE-2026-0001"
    now = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        session.add(PersonRow(person_id=person_id))
        session.commit()

        repository = SQLAlchemySagurCouponsRepository(session)
        repository.apply_event(
            event_id=uuid4(),
            direction="assignments",
            sent_at=now,
            payload_raw={
                "person_id": str(person_id),
                "coupon_series": "SER-TITLE",
                "coupon_code": coupon_code,
                "coupon_title": "  Купон на сет «Канпети»  ",
                "venue_code": "susami",
                "venue_name": "Сами Сусами",
                "status": "reserved",
            },
        )
        session.commit()

        row = _person_coupon_rows(session, coupon_code=coupon_code)[0]
        assert row.coupon_title == "Купон на сет «Канпети»"
        coupons = repository.list_visible_coupons(person_id=person_id, venue_code="susami")
        assert coupons[0].coupon_title == "Купон на сет «Канпети»"

        repository.apply_event(
            event_id=uuid4(),
            direction="status_update",
            sent_at=now,
            payload_raw={
                "person_id": str(person_id),
                "coupon_series": "SER-TITLE",
                "coupon_code": coupon_code,
                "status": "sent",
            },
        )
        session.commit()

        row = _person_coupon_rows(session, coupon_code=coupon_code)[0]
        assert row.coupon_title == "Купон на сет «Канпети»"

        repository.apply_event(
            event_id=uuid4(),
            direction="status_update",
            sent_at=now,
            payload_raw={
                "person_id": str(person_id),
                "coupon_series": "SER-TITLE",
                "coupon_code": coupon_code,
                "coupon_title": "",
                "status": "sent",
            },
        )
        session.commit()

        row = _person_coupon_rows(session, coupon_code=coupon_code)[0]
        assert row.coupon_title == "Купон на сет «Канпети»"

        repository.apply_event(
            event_id=uuid4(),
            direction="status_update",
            sent_at=now,
            payload_raw={
                "person_id": str(person_id),
                "coupon_series": "SER-TITLE",
                "coupon_code": coupon_code,
                "coupon_title": "Новое название купона",
                "status": "sent",
            },
        )
        session.commit()

        row = _person_coupon_rows(session, coupon_code=coupon_code)[0]
        assert row.coupon_title == "Новое название купона"


def test_assignments_rejects_reuse_of_used_coupon_without_release() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    first_person_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    second_person_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    coupon_series = "SER-USED"
    coupon_code = "USED-2026-0001"
    now = datetime(2026, 5, 15, 9, 30, tzinfo=timezone.utc)

    with session_factory() as session:
        session.add_all(
            [
                PersonRow(person_id=first_person_id),
                PersonRow(person_id=second_person_id),
            ]
        )
        session.commit()

        repository = SQLAlchemySagurCouponsRepository(session)
        repository.apply_event(
            event_id=uuid4(),
            direction="assignments",
            sent_at=now,
            payload_raw={
                "person_id": str(first_person_id),
                "coupon_series": coupon_series,
                "coupon_code": coupon_code,
                "venue_code": "nani",
                "status": "reserved",
            },
        )
        session.commit()

        repository.apply_event(
            event_id=uuid4(),
            direction="status_update",
            sent_at=now,
            payload_raw={
                "person_id": str(first_person_id),
                "coupon_series": coupon_series,
                "coupon_code": coupon_code,
                "status": "used",
            },
        )
        session.commit()

        with pytest.raises(CouponAlreadyAssignedError):
            repository.apply_event(
                event_id=uuid4(),
                direction="assignments",
                sent_at=now,
                payload_raw={
                    "person_id": str(second_person_id),
                    "coupon_series": coupon_series,
                    "coupon_code": coupon_code,
                    "venue_code": "susami",
                    "status": "reserved",
                },
            )


def test_used_after_campaign_is_terminal_and_not_reassignable() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    first_person_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    second_person_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    coupon_series = "SER-LATE"
    coupon_code = "LATE-2026-0001"
    now = datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        session.add_all(
            [
                PersonRow(person_id=first_person_id),
                PersonRow(person_id=second_person_id),
            ]
        )
        session.commit()

        repository = SQLAlchemySagurCouponsRepository(session)
        assigned = repository.apply_event(
            event_id=uuid4(),
            direction="assignments",
            sent_at=now,
            payload_raw={
                "person_id": str(first_person_id),
                "coupon_series": coupon_series,
                "coupon_code": coupon_code,
                "venue_code": "nani",
                "status": "reserved",
            },
        )
        session.commit()

        expired = repository.apply_event(
            event_id=uuid4(),
            direction="status_update",
            sent_at=now,
            payload_raw={
                "person_id": str(first_person_id),
                "coupon_series": coupon_series,
                "coupon_code": coupon_code,
                "status": "expired",
            },
        )
        session.commit()

        used_after_campaign = repository.apply_event(
            event_id=uuid4(),
            direction="status_update",
            sent_at=now,
            payload_raw={
                "person_id": str(first_person_id),
                "coupon_series": coupon_series,
                "coupon_code": coupon_code,
                "status": "used_after_campaign",
                "meta": {
                    "remove_from_guest": True,
                    "release_to_pool": False,
                    "used_after_campaign": True,
                },
            },
        )
        session.commit()

        assert expired.coupon_id == assigned.coupon_id
        assert used_after_campaign.coupon_id == assigned.coupon_id
        assert repository.list_visible_coupons(person_id=first_person_id, venue_code="nani") == ()
        rows = _person_coupon_rows(session, coupon_code=coupon_code)
        assert len(rows) == 1
        assert rows[0].status == "used_after_campaign"
        assert rows[0].is_visible is False

        with pytest.raises(CouponAlreadyAssignedError):
            repository.apply_event(
                event_id=uuid4(),
                direction="assignments",
                sent_at=now,
                payload_raw={
                    "person_id": str(second_person_id),
                    "coupon_series": coupon_series,
                    "coupon_code": coupon_code,
                    "venue_code": "susami",
                    "status": "reserved",
                },
            )


def _coupon_row(
    *,
    coupon_id: UUID,
    person_id: UUID,
    coupon_code: str,
    venue_code: str,
    status: str,
    now: datetime,
    venue_name: str | None = None,
) -> PersonCouponRow:
    return PersonCouponRow(
        coupon_id=coupon_id,
        person_id=person_id,
        coupon_series="SER-A",
        coupon_code=coupon_code,
        campaign_id="CMP-1",
        venue_code=venue_code,
        venue_name=venue_name,
        promo_text="Подарочный десерт",
        status=status,
        is_visible=True,
        created_at=now,
        updated_at=now,
    )


def _person_coupon_rows(session: Session, *, coupon_code: str) -> tuple[PersonCouponRow, ...]:
    rows = session.execute(
        select(PersonCouponRow)
        .where(PersonCouponRow.coupon_code == coupon_code)
        .order_by(PersonCouponRow.created_at.asc())
    ).scalars()
    return tuple(rows)


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
