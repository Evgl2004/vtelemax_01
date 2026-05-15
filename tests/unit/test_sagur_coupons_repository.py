"""Unit-тесты read-моделей репозитория купонов SAGUR."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy import select
from sqlalchemy.orm import Session

from vtelemax.infrastructure.postgres import (
    Base,
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
