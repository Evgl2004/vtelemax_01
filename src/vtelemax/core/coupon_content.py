"""Единый контент пользовательского контура купонов SAGUR.

Модуль не зависит от SQLAlchemy и SDK мессенджеров. Он отвечает только за
бизнес-правила отображения купонов: какие разделы показывать, как подписывать
кнопки и какой текст отправлять рядом с QR-кодом.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

GLOBAL_COUPON_VENUE_CODE = "__global__"
GLOBAL_COUPON_SCOPE_KEY = "global"
COUPON_ACTIVE_STATUSES = frozenset({"reserved", "sent"})
COUPON_INACTIVE_STATUSES = frozenset(
    {"used", "used_after_campaign", "expired", "canceled", "error"}
)


class CouponVenueLike(Protocol):
    """Минимальный контракт заведения с купонами для построения UI."""

    venue_code: str
    venue_name: str
    coupons_count: int


class CouponItemLike(Protocol):
    """Минимальный контракт купона для построения списков и карточки."""

    coupon_id: UUID
    coupon_series: str
    coupon_code: str
    campaign_id: str | None
    venue_code: str
    venue_name: str | None
    promo_text: str | None
    status: str
    is_visible: bool
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CouponScopeView:
    """Раздел купонов, который пользователь видит на корневом экране."""

    scope_key: str
    venue_code: str
    title: str
    label: str
    coupons_count: int


@dataclass(frozen=True, slots=True)
class CouponListItemView:
    """Кнопка конкретного купона в списке выбранного раздела."""

    coupon_id: UUID
    coupon_id_hex: str
    label: str
    coupon_tail4: str


@dataclass(frozen=True, slots=True)
class CouponsRootView:
    """Содержимое корневого экрана раздела «Купоны»."""

    text: str
    scopes: tuple[CouponScopeView, ...]
    is_empty: bool


@dataclass(frozen=True, slots=True)
class CouponsListView:
    """Содержимое экрана списка купонов внутри одного раздела."""

    text: str
    items: tuple[CouponListItemView, ...]
    is_empty: bool


@dataclass(frozen=True, slots=True)
class CouponCardView:
    """Содержимое карточки купона и payload для QR-кода."""

    text: str
    qr_payload: str
    coupon_tail4: str


def is_coupon_visible_for_guest(*, status: str, is_visible: bool) -> bool:
    """Возвращает, можно ли показывать купон гостю в активном списке.

    Проверка дублирует доменное правило на уровне UI: даже если в БД по старым
    данным остался `is_visible=True`, неактивные статусы не попадут в меню.
    """

    normalized_status = str(status or "").strip().lower()
    return bool(is_visible) and normalized_status in COUPON_ACTIVE_STATUSES


def build_coupons_root_view(
    *,
    global_count: int,
    venues: tuple[CouponVenueLike, ...],
) -> CouponsRootView:
    """Строит корневой экран купонов с разделами «Общие» и заведениями."""

    scopes: list[CouponScopeView] = []
    normalized_global_count = max(int(global_count or 0), 0)
    if normalized_global_count > 0:
        scopes.append(
            CouponScopeView(
                scope_key=GLOBAL_COUPON_SCOPE_KEY,
                venue_code=GLOBAL_COUPON_VENUE_CODE,
                title="Общие купоны",
                label=f"🎟️ Общие ({normalized_global_count})",
                coupons_count=normalized_global_count,
            )
        )

    for venue in venues:
        coupons_count = max(int(getattr(venue, "coupons_count", 0) or 0), 0)
        venue_code = str(getattr(venue, "venue_code", "") or "").strip()
        if coupons_count <= 0 or not venue_code or venue_code == GLOBAL_COUPON_VENUE_CODE:
            continue
        venue_name = str(getattr(venue, "venue_name", "") or venue_code).strip() or venue_code
        scopes.append(
            CouponScopeView(
                scope_key=venue_code,
                venue_code=venue_code,
                title=venue_name,
                label=f"🏠 {venue_name} ({coupons_count})",
                coupons_count=coupons_count,
            )
        )

    if not scopes:
        return CouponsRootView(
            text=(
                "🎟️ Купоны\n\n"
                "Сейчас активных купонов нет. Как только SAGUR пришлет новый купон, "
                "он появится здесь автоматически."
            ),
            scopes=(),
            is_empty=True,
        )

    return CouponsRootView(
        text=(
            "🎟️ Купоны\n\n"
            "Выберите раздел: общие купоны или заведение, где сейчас есть активные предложения."
        ),
        scopes=tuple(scopes),
        is_empty=False,
    )


def build_coupons_list_view(
    *,
    scope_title: str,
    coupons: tuple[CouponItemLike, ...],
) -> CouponsListView:
    """Строит список активных купонов внутри выбранного раздела."""

    title = str(scope_title or "Купоны").strip() or "Купоны"
    visible_coupons = tuple(
        coupon
        for coupon in coupons
        if is_coupon_visible_for_guest(status=coupon.status, is_visible=coupon.is_visible)
    )
    items = tuple(_build_coupon_list_item(coupon) for coupon in visible_coupons)

    if not items:
        return CouponsListView(
            text=(
                f"🎟️ {title}\n\n"
                "В этом разделе сейчас нет активных купонов. Вернитесь назад и выберите другой раздел."
            ),
            items=(),
            is_empty=True,
        )

    return CouponsListView(
        text=(
            f"🎟️ {title}\n\n"
            "Выберите купон. В списке показываем последние 4 символа кода, "
            "а полный QR отправим после открытия."
        ),
        items=items,
        is_empty=False,
    )


def build_coupon_card_view(coupon: CouponItemLike) -> CouponCardView | None:
    """Строит текст карточки купона и возвращает код для QR.

    Если купон уже стал неактивным, возвращаем `None`: адаптер покажет
    безопасный экран «купон недоступен» вместо отправки устаревшего QR.
    """

    if not is_coupon_visible_for_guest(status=coupon.status, is_visible=coupon.is_visible):
        return None

    coupon_code = str(coupon.coupon_code or "").strip()
    if not coupon_code:
        return None

    tail4 = coupon_tail4(coupon_code)
    promo_text = str(coupon.promo_text or "").strip() or "Купон SAGUR"
    venue_name = _resolve_coupon_venue_name(coupon)
    status_text = _format_coupon_status(coupon.status)
    updated_at_text = _format_coupon_datetime(getattr(coupon, "updated_at", None))

    lines = [
        "🎟️ Купон открыт",
        "",
        f"🏷️ Предложение: {promo_text}",
        f"🏠 Заведение: {venue_name}",
        f"🔢 Код купона: {coupon_code}",
        f"🔎 Последние 4 символа: {tail4}",
        f"📌 Статус: {status_text}",
    ]
    coupon_series = str(coupon.coupon_series or "").strip()
    if coupon_series:
        lines.append(f"🧾 Серия: {coupon_series}")
    campaign_id = str(coupon.campaign_id or "").strip()
    if campaign_id:
        lines.append(f"🏁 Кампания: {campaign_id}")
    if updated_at_text:
        lines.append(f"🕒 Обновлено: {updated_at_text}")
    lines.extend(
        [
            "",
            "Покажите QR-код сотруднику заведения. Если QR не считывается, можно назвать код купона.",
        ]
    )
    return CouponCardView(text="\n".join(lines), qr_payload=coupon_code, coupon_tail4=tail4)


def coupon_tail4(coupon_code: str) -> str:
    """Возвращает последние 4 символа кода купона для компактного списка."""

    normalized = str(coupon_code or "").strip()
    return normalized[-4:] if len(normalized) > 4 else normalized


def _build_coupon_list_item(coupon: CouponItemLike) -> CouponListItemView:
    tail4 = coupon_tail4(coupon.coupon_code)
    return CouponListItemView(
        coupon_id=coupon.coupon_id,
        coupon_id_hex=coupon.coupon_id.hex,
        label=f"🎟️ Купон • {tail4}",
        coupon_tail4=tail4,
    )


def _resolve_coupon_venue_name(coupon: CouponItemLike) -> str:
    venue_name = str(coupon.venue_name or "").strip()
    if venue_name:
        return venue_name
    venue_code = str(coupon.venue_code or "").strip()
    if not venue_code or venue_code == GLOBAL_COUPON_VENUE_CODE:
        return "Общие купоны"
    return venue_code


def _format_coupon_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "reserved":
        return "зарезервирован"
    if normalized == "sent":
        return "активен"
    return normalized or "неизвестен"


def _format_coupon_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    return normalized.strftime("%d.%m.%Y %H:%M")
