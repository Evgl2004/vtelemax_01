"""Unit-тесты read-моделей репозитория купонов SAGUR."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import create_engine

from vtelemax.infrastructure.postgres import (
    Base,
    PersonCouponRow,
    PersonRow,
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
