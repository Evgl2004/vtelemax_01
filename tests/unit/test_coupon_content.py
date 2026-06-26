"""Тесты общего контента пользовательского контура купонов."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from vtelemax.core import (
    GLOBAL_COUPON_SCOPE_KEY,
    GLOBAL_COUPON_VENUE_CODE,
    build_coupon_card_view,
    build_coupon_card_view_for_markup,
    build_coupons_list_view,
    build_coupons_root_view,
    coupon_tail4,
    coupon_tail6,
    is_coupon_delivery_text,
    is_coupon_visible_for_guest,
)


@dataclass(frozen=True, slots=True)
class _Venue:
    venue_code: str
    venue_name: str
    coupons_count: int


@dataclass(frozen=True, slots=True)
class _Coupon:
    coupon_id: UUID
    coupon_series: str
    coupon_code: str
    campaign_id: str | None
    venue_code: str
    venue_name: str | None
    promo_text: str | None
    valid_until: datetime | None
    status: str
    is_visible: bool
    updated_at: datetime
    coupon_title: str | None = None


def _coupon(
    code: str,
    *,
    status: str = "sent",
    is_visible: bool = True,
    venue_code: str = "nani",
    venue_name: str | None = "Грузинка Нани",
    promo_text: str | None = "Подарочный десерт",
    valid_until: datetime | None = None,
    coupon_title: str | None = None,
) -> _Coupon:
    return _Coupon(
        coupon_id=UUID("11111111-1111-4111-8111-111111111111"),
        coupon_series="SERIES-A",
        coupon_code=code,
        campaign_id="CMP-2026",
        venue_code=venue_code,
        venue_name=venue_name,
        promo_text=promo_text,
        valid_until=valid_until,
        status=status,
        is_visible=is_visible,
        updated_at=datetime(2026, 5, 15, 8, 30, tzinfo=timezone.utc),
        coupon_title=coupon_title,
    )


def test_coupons_root_view_shows_global_only_when_global_coupons_exist() -> None:
    """Проверяет корневой экран: «Общие» появляется только при глобальных купонах."""

    view = build_coupons_root_view(
        global_count=2,
        venues=(
            _Venue(venue_code="nani", venue_name="Грузинка Нани", coupons_count=3),
            _Venue(venue_code="empty", venue_name="Пустое заведение", coupons_count=0),
            _Venue(venue_code=GLOBAL_COUPON_VENUE_CODE, venue_name="Системный глобальный код", coupons_count=9),
        ),
    )

    assert view.is_empty is False
    assert [scope.scope_key for scope in view.scopes] == [GLOBAL_COUPON_SCOPE_KEY, "nani"]
    assert view.scopes[0].label == "🎟️ Общие (2)"
    assert view.scopes[1].label == "💃 Грузинка Нани (3)"


def test_coupons_root_view_hides_global_when_only_venues_have_coupons() -> None:
    """Проверяет, что кнопка «Общие» не показывается без `__global__` купонов."""

    view = build_coupons_root_view(
        global_count=0,
        venues=(_Venue(venue_code="susami", venue_name="Сами Сусами", coupons_count=1),),
    )

    assert view.is_empty is False
    assert len(view.scopes) == 1
    assert view.scopes[0].scope_key == "susami"
    assert view.scopes[0].label == "🍷 Сами Сусами (1)"
    assert "Общие" not in view.scopes[0].label


def test_coupons_root_view_uses_known_venue_emojis_and_house_fallback() -> None:
    """Проверяет emoji заведений в корневом меню купонов."""

    view = build_coupons_root_view(
        global_count=0,
        venues=(
            _Venue(venue_code="susami", venue_name="Сами Сусами", coupons_count=1),
            _Venue(venue_code="china", venue_name="Чина", coupons_count=1),
            _Venue(venue_code="uzbechka", venue_name="Узбечка", coupons_count=1),
            _Venue(venue_code="unknown", venue_name="Новое место", coupons_count=1),
        ),
    )

    assert [scope.label for scope in view.scopes] == [
        "🍷 Сами Сусами (1)",
        "🍜 Чина (1)",
        "☀️ Узбечка (1)",
        "🏠 Новое место (1)",
    ]


def test_coupons_root_view_returns_clear_empty_screen() -> None:
    """Проверяет понятный пустой экран, когда купонов нет вообще."""

    view = build_coupons_root_view(global_count=0, venues=())

    assert view.is_empty is True
    assert view.scopes == ()
    assert "активных купонов нет" in view.text
    assert "SAGUR" not in view.text


def test_coupons_list_view_uses_coupon_tail6_fallback_and_filters_inactive_statuses() -> None:
    """Проверяет fallback по последним 6 символам и скрытие неактивных купонов."""

    active_sent = _coupon("LONG-CODE-123456", status="sent")
    active_reserved = _coupon("R-55", status="reserved")
    used = _coupon("USED-0001", status="used")
    used_after_campaign = _coupon("USED-LATE-0006", status="used_after_campaign")
    expired = _coupon("EXP-0002", status="expired")
    canceled = _coupon("CAN-0003", status="canceled")
    error = _coupon("ERR-0004", status="error")
    hidden = _coupon("HIDDEN-0005", status="sent", is_visible=False)

    view = build_coupons_list_view(
        scope_title="Грузинка Нани",
        coupons=(
            active_sent,
            active_reserved,
            used,
            used_after_campaign,
            expired,
            canceled,
            error,
            hidden,
        ),
    )

    assert view.is_empty is False
    assert [item.label for item in view.items] == ["🎟️ Купон • 123456", "🎟️ Купон • R-55"]
    assert [item.coupon_tail4 for item in view.items] == ["3456", "R-55"]
    assert [item.coupon_tail6 for item in view.items] == ["123456", "R-55"]


def test_coupons_list_view_uses_coupon_title_when_present() -> None:
    """Проверяет, что SAGUR title становится названием купона в списке."""

    view = build_coupons_list_view(
        scope_title="Сами Сусами",
        coupons=(
            _coupon(
                "PROMO-2026-5P0B4C",
                coupon_title="  Купон на сет «Канпети»  ",
            ),
        ),
    )

    assert view.is_empty is False
    assert view.items[0].label == "Купон на сет «Канпети»"
    assert view.items[0].display_title == "Купон на сет «Канпети»"


def test_coupons_list_view_returns_empty_when_all_coupons_inactive() -> None:
    """Проверяет пустой экран раздела, если видимых активных купонов уже нет."""

    view = build_coupons_list_view(
        scope_title="Общие купоны",
        coupons=(
            _coupon("USED-0001", status="used", venue_code=GLOBAL_COUPON_VENUE_CODE, venue_name=None),
            _coupon(
                "USED-LATE-0002",
                status="used_after_campaign",
                venue_code=GLOBAL_COUPON_VENUE_CODE,
                venue_name=None,
            ),
            _coupon("HIDDEN-0002", status="sent", is_visible=False),
        ),
    )

    assert view.is_empty is True
    assert view.items == ()
    assert "нет активных купонов" in view.text


def test_coupon_card_view_contains_guest_facing_qr_payload_and_coupon_attributes() -> None:
    """Проверяет карточку конкретного купона перед отправкой QR."""

    coupon = _coupon("PROMO-2026-7777")

    view = build_coupon_card_view(coupon)

    assert view is not None
    assert view.qr_payload == "PROMO-2026-7777"
    assert view.coupon_code == "PROMO-2026-7777"
    assert view.coupon_tail4 == "7777"
    assert "Подарочный десерт" in view.text
    assert "Грузинка Нани" in view.text
    assert "PROMO-2026-7777" in view.text
    assert "SERIES-A" not in view.text
    assert "CMP-2026" not in view.text
    assert "Последние 4" not in view.text
    assert "Статус" not in view.text


def test_coupon_card_view_html_markup_uses_bold_labels_and_code_tag() -> None:
    """Проверяет HTML-разметку карточки для Telegram/MAX."""

    view = build_coupon_card_view_for_markup(
        _coupon(
            "PROMO-2026-7777",
            venue_name='Кафе "Нани"',
            promo_text="Десерт <в подарок>",
        ),
        markup="html",
    )

    assert view is not None
    assert "🎟️ <b>Купон открыт</b>" in view.text
    assert "🏷️ <b>Предложение:</b>" in view.text
    assert "Десерт &lt;в подарок&gt;" in view.text
    assert "Кафе &quot;Нани&quot;" in view.text
    assert "<code>PROMO-2026-7777</code>" in view.text


def test_coupon_card_view_shows_valid_until_from_machine_readable_field() -> None:
    """Проверяет, что срок действия берется из поля valid_until, а не из текста акции."""

    view = build_coupon_card_view_for_markup(
        _coupon(
            "PROMO-2026-7777",
            promo_text="Скидка без даты в тексте",
            valid_until=datetime(2026, 5, 18, 18, 59, 59, tzinfo=timezone.utc),
        ),
        markup="html",
    )

    assert view is not None
    assert "⏳ <b>Действует до:</b> 18.05.2026" in view.text


def test_coupon_card_view_uses_public_fallback_text_without_integration_name() -> None:
    """Проверяет, что fallback-текст купона не раскрывает гостю техническую интеграцию."""

    view = build_coupon_card_view(_coupon("PROMO-2026-7777", promo_text=None))

    assert view is not None
    assert "Персональное предложение" in view.text
    assert "SAGUR" not in view.text


def test_coupon_card_view_rejects_inactive_coupon() -> None:
    """Проверяет, что карточка не строится для неактивного купона."""

    assert build_coupon_card_view(_coupon("USED-0001", status="used")) is None
    assert build_coupon_card_view(_coupon("USED-LATE-0002", status="used_after_campaign")) is None
    assert build_coupon_card_view(_coupon("HIDDEN-0002", is_visible=False)) is None


def test_coupon_visibility_predicate_and_tail4_are_stable() -> None:
    """Проверяет маленькие, но важные правила отображения купона."""

    assert is_coupon_visible_for_guest(status="sent", is_visible=True) is True
    assert is_coupon_visible_for_guest(status="reserved", is_visible=True) is True
    assert is_coupon_visible_for_guest(status="used_after_campaign", is_visible=True) is False
    assert is_coupon_visible_for_guest(status="expired", is_visible=True) is False
    assert is_coupon_visible_for_guest(status="sent", is_visible=False) is False

    assert coupon_tail4("ABCDEF") == "CDEF"
    assert coupon_tail4("123") == "123"
    assert coupon_tail6("LONG-ABCDEF") == "ABCDEF"
    assert coupon_tail6("5P0B4C") == "5P0B4C"


def test_coupon_delivery_text_detector_is_conservative() -> None:
    """Проверяет распознавание купонной рассылки для кнопки перехода."""

    assert is_coupon_delivery_text("Код купона: E2E-OVT89GWN") is True
    assert is_coupon_delivery_text("Мы подготовили персональный купон на кофе.") is True
    assert is_coupon_delivery_text("Новое обращение от гостя\nТикет: #1234") is False
