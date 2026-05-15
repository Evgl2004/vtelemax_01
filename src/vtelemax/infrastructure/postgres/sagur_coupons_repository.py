"""PostgreSQL repository for SAGUR coupon events and guest coupons."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from .schema import PersonCouponRow, SagurCouponEventRow

_GLOBAL_VENUE_CODE = "__global__"
_COUPON_ACTIVE_STATUSES = {"reserved", "sent"}
_COUPON_ALLOWED_STATUSES = _COUPON_ACTIVE_STATUSES | {"used", "expired", "canceled", "error"}


@dataclass(frozen=True, slots=True)
class IncomingCouponPayload:
    """Normalized payload for coupon assignment/status events."""

    campaign_id: str | None
    guest_id: str | None
    person_id: UUID
    phone_e164: str | None
    coupon_series: str
    coupon_code: str
    venue_code: str
    venue_name: str | None
    promo_text: str | None
    status: str
    vtelemax_sync_status: str | None

    @classmethod
    def from_raw(cls, payload: dict[str, object]) -> "IncomingCouponPayload":
        def _s(value: object | None) -> str | None:
            if value is None:
                return None
            text = str(value).strip()
            return text or None

        person_raw = _s(payload.get("person_id"))
        if not person_raw:
            raise ValueError("payload.person_id is required")
        try:
            person_id = UUID(person_raw)
        except ValueError as exc:
            raise ValueError("payload.person_id is invalid UUID") from exc

        coupon_series = _s(payload.get("coupon_series"))
        if not coupon_series:
            raise ValueError("payload.coupon_series is required")
        coupon_code = _s(payload.get("coupon_code"))
        if not coupon_code:
            raise ValueError("payload.coupon_code is required")

        status = (_s(payload.get("status")) or "reserved").lower()
        if status not in _COUPON_ALLOWED_STATUSES:
            raise ValueError("payload.status is unsupported")

        venue_code = _s(payload.get("venue_code")) or _GLOBAL_VENUE_CODE
        return cls(
            campaign_id=_s(payload.get("campaign_id")),
            guest_id=_s(payload.get("guest_id")),
            person_id=person_id,
            phone_e164=_s(payload.get("phone_e164")),
            coupon_series=coupon_series,
            coupon_code=coupon_code,
            venue_code=venue_code,
            venue_name=_s(payload.get("venue_name")),
            promo_text=_s(payload.get("promo_text")),
            status=status,
            vtelemax_sync_status=_s(payload.get("vtelemax_sync_status")),
        )


@dataclass(frozen=True, slots=True)
class CouponUiVenue:
    """Visible venue with coupon counter for root coupon menu."""

    venue_code: str
    venue_name: str
    coupons_count: int


@dataclass(frozen=True, slots=True)
class CouponUiItem:
    """Coupon projection for bot UI."""

    coupon_id: UUID
    person_id: UUID
    coupon_series: str
    coupon_code: str
    campaign_id: str | None
    venue_code: str
    venue_name: str | None
    promo_text: str | None
    status: str
    is_visible: bool
    updated_at: datetime

    @property
    def coupon_tail4(self) -> str:
        """Last 4 symbols for compact list label."""

        value = (self.coupon_code or "").strip()
        if len(value) <= 4:
            return value
        return value[-4:]


@dataclass(frozen=True, slots=True)
class ApplyCouponEventResult:
    """Result of SAGUR coupon event application."""

    deduplicated: bool
    coupon_id: UUID | None = None


class SQLAlchemySagurCouponsRepository:
    """Repository that handles incoming coupon events and coupon reads for UI."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def apply_event(
        self,
        *,
        event_id: UUID,
        direction: str,
        sent_at: datetime | None,
        payload_raw: dict[str, object],
    ) -> ApplyCouponEventResult:
        """Applies a coupon event once (idempotent by event_id)."""

        existing_event = self._session.get(SagurCouponEventRow, event_id)
        if existing_event is not None:
            return ApplyCouponEventResult(deduplicated=True, coupon_id=None)

        if direction not in {"assignments", "status_update"}:
            raise ValueError("direction must be assignments or status_update")

        payload = IncomingCouponPayload.from_raw(payload_raw)

        self._session.add(
            SagurCouponEventRow(
                event_id=event_id,
                direction=direction,
                sent_at=sent_at,
                payload_json=payload_raw,
            )
        )

        is_visible = payload.status in _COUPON_ACTIVE_STATUSES
        venue_code = payload.venue_code or _GLOBAL_VENUE_CODE
        existing_coupon = self._session.execute(
            select(PersonCouponRow).where(
                and_(
                    PersonCouponRow.person_id == payload.person_id,
                    PersonCouponRow.coupon_series == payload.coupon_series,
                    PersonCouponRow.coupon_code == payload.coupon_code,
                )
            )
        ).scalar_one_or_none()

        # SAGUR treats canceled as a release: remove the guest binding instead of
        # keeping a hidden terminal coupon, so the code can be assigned again.
        if direction == "status_update" and payload.status == "canceled":
            if existing_coupon is None:
                return ApplyCouponEventResult(deduplicated=False, coupon_id=None)

            released_coupon_id = existing_coupon.coupon_id
            self._session.delete(existing_coupon)
            return ApplyCouponEventResult(deduplicated=False, coupon_id=released_coupon_id)

        if existing_coupon is None:
            coupon_id = uuid4()
            self._session.add(
                PersonCouponRow(
                    coupon_id=coupon_id,
                    person_id=payload.person_id,
                    coupon_series=payload.coupon_series,
                    coupon_code=payload.coupon_code,
                    campaign_id=payload.campaign_id,
                    venue_code=venue_code,
                    venue_name=payload.venue_name,
                    promo_text=payload.promo_text,
                    status=payload.status,
                    is_visible=is_visible,
                    last_event_id=event_id,
                )
            )
            return ApplyCouponEventResult(deduplicated=False, coupon_id=coupon_id)

        existing_coupon.campaign_id = payload.campaign_id
        existing_coupon.venue_code = venue_code
        existing_coupon.venue_name = payload.venue_name
        existing_coupon.promo_text = payload.promo_text
        existing_coupon.status = payload.status
        existing_coupon.is_visible = is_visible
        existing_coupon.last_event_id = event_id
        return ApplyCouponEventResult(deduplicated=False, coupon_id=existing_coupon.coupon_id)

    def count_visible_global_coupons(self, *, person_id: UUID) -> int:
        """Returns count of visible global coupons for person."""

        rows = self._session.execute(
            select(PersonCouponRow.coupon_id).where(
                PersonCouponRow.person_id == person_id,
                PersonCouponRow.is_visible.is_(True),
                PersonCouponRow.status.in_(_COUPON_ACTIVE_STATUSES),
                PersonCouponRow.venue_code == _GLOBAL_VENUE_CODE,
            )
        ).all()
        return len(rows)

    def list_visible_venues(self, *, person_id: UUID) -> tuple[CouponUiVenue, ...]:
        """Lists non-global venues with visible coupons for person."""

        rows = self._session.execute(
            select(
                PersonCouponRow.venue_code,
                PersonCouponRow.venue_name,
            )
            .where(
                PersonCouponRow.person_id == person_id,
                PersonCouponRow.is_visible.is_(True),
                PersonCouponRow.status.in_(_COUPON_ACTIVE_STATUSES),
                PersonCouponRow.venue_code != _GLOBAL_VENUE_CODE,
            )
            .order_by(
                PersonCouponRow.venue_name.asc().nulls_last(),
                PersonCouponRow.venue_code.asc(),
                PersonCouponRow.updated_at.desc(),
            )
        ).all()

        grouped: dict[tuple[str, str], int] = {}
        for row in rows:
            code = str(row.venue_code or "").strip() or _GLOBAL_VENUE_CODE
            name = str(row.venue_name or code).strip() or code
            key = (code, name)
            grouped[key] = grouped.get(key, 0) + 1

        venues = tuple(
            CouponUiVenue(venue_code=code, venue_name=name, coupons_count=count)
            for (code, name), count in grouped.items()
        )
        return venues

    def list_visible_coupons(
        self,
        *,
        person_id: UUID,
        venue_code: str,
    ) -> tuple[CouponUiItem, ...]:
        """Lists visible coupons for person in one venue (or __global__)."""

        normalized_venue_code = (venue_code or "").strip() or _GLOBAL_VENUE_CODE
        rows = self._session.execute(
            select(PersonCouponRow).where(
                PersonCouponRow.person_id == person_id,
                PersonCouponRow.is_visible.is_(True),
                PersonCouponRow.status.in_(_COUPON_ACTIVE_STATUSES),
                PersonCouponRow.venue_code == normalized_venue_code,
            )
            .order_by(PersonCouponRow.updated_at.desc(), PersonCouponRow.created_at.desc())
        ).scalars().all()
        return tuple(_to_coupon_ui_item(row) for row in rows)

    def get_coupon(
        self,
        *,
        person_id: UUID,
        coupon_id: UUID,
    ) -> CouponUiItem | None:
        """Returns coupon by id for person (visible and hidden)."""

        row = self._session.execute(
            select(PersonCouponRow).where(
                PersonCouponRow.person_id == person_id,
                PersonCouponRow.coupon_id == coupon_id,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return _to_coupon_ui_item(row)


def _to_coupon_ui_item(row: PersonCouponRow) -> CouponUiItem:
    return CouponUiItem(
        coupon_id=row.coupon_id,
        person_id=row.person_id,
        coupon_series=row.coupon_series,
        coupon_code=row.coupon_code,
        campaign_id=row.campaign_id,
        venue_code=row.venue_code,
        venue_name=row.venue_name,
        promo_text=row.promo_text,
        status=row.status,
        is_visible=bool(row.is_visible),
        updated_at=row.updated_at,
    )
