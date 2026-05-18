"""Тесты MAX identity-адаптера."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import TracebackType
from uuid import UUID

from vtelemax.adapters.max import MaxIdentityAdapter
from vtelemax.adapters.max import identity_adapter as max_identity_module
from vtelemax.core import (
    CreateSupportTicketCommand,
    CreateSupportTicketTransactionalUseCase,
    GetLoyaltyBalanceUseCase,
    GetPersonByAccountCommand,
    GetPersonByAccountTransactionalUseCase,
    GetVirtualCardUseCase,
    ListOpenSupportTicketsTransactionalUseCase,
    ListPersonSupportTicketsTransactionalUseCase,
    GetSupportTicketConversationTransactionalUseCase,
    GetSupportTicketDetailsTransactionalUseCase,
    IdentityRepository,
    IdentityUnitOfWork,
    InMemoryIdentityRepository,
    InMemorySupportRepository,
    LoyaltyCard,
    LoyaltyCustomer,
    LoyaltyGateway,
    LoyaltyGatewayError,
    LoyaltyIssueCardResult,
    LoyaltyRegisterCustomerResult,
    PersonProfilePatch,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
    RouteModeratorReplyTransactionalUseCase,
)


@dataclass(frozen=True, slots=True)
class _CouponVenue:
    venue_code: str
    venue_name: str
    coupons_count: int


@dataclass(frozen=True, slots=True)
class _CouponItem:
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


class _FakeCouponSession:
    """Минимальная context manager-сессия для проверки session_factory."""

    def __enter__(self) -> "_FakeCouponSession":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return


class _FakeCouponSessionFactory:
    """Тестовая фабрика сессий, совместимая с MAX-адаптером."""

    def __call__(self) -> _FakeCouponSession:
        return _FakeCouponSession()


def test_identity_adapter_masks_contact_phone_for_logs() -> None:
    """Проверяет общий формат маски телефона в логах MAX identity adapter."""

    assert max_identity_module._mask_phone_for_log("+7 (912) 345-67-89") == "***6789"
    assert max_identity_module._mask_phone_for_log("abc") is None


class InMemoryIdentityUnitOfWork(IdentityUnitOfWork):
    """Тестовый UnitOfWork поверх in-memory репозитория."""

    def __init__(self, repository: IdentityRepository) -> None:
        self.identity_repository = repository

    def __enter__(self) -> "InMemoryIdentityUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return

    def commit(self) -> None:
        return

    def rollback(self) -> None:
        return


class InMemorySupportUnitOfWork(InMemoryIdentityUnitOfWork):
    """Тестовый UoW с поддержкой тикетов."""

    def __init__(self, repository: IdentityRepository, support_repository: InMemorySupportRepository) -> None:
        super().__init__(repository)
        self.support_repository = support_repository


class StubLoyaltyGateway(LoyaltyGateway):
    """Тестовый шлюз лояльности для проверки меню «Баланс/Виртуальная карта»."""

    def __init__(self, *, customer: LoyaltyCustomer | None) -> None:
        self._customer = customer

    def get_customer_info(self, phone_e164: str) -> LoyaltyCustomer | None:
        return self._customer

    def register_customer(
        self,
        phone_e164: str,
        *,
        profile=None,
        customer_id: str | None = None,
    ) -> LoyaltyRegisterCustomerResult:
        return LoyaltyRegisterCustomerResult(customer_id="cust-1", message="registered")

    def issue_card_for_customer(self, phone_e164: str, customer_id: str) -> LoyaltyIssueCardResult:
        return LoyaltyIssueCardResult(card_number="79123456789_20260325", message="issued")


class AlwaysFailLoyaltyGateway(LoyaltyGateway):
    """Тестовый шлюз, который всегда возвращает ошибку iiko."""

    def get_customer_info(self, phone_e164: str) -> LoyaltyCustomer | None:
        raise LoyaltyGatewayError("temporary unavailable")

    def register_customer(
        self,
        phone_e164: str,
        *,
        profile=None,
        customer_id: str | None = None,
    ) -> LoyaltyRegisterCustomerResult:
        raise LoyaltyGatewayError("temporary unavailable")

    def issue_card_for_customer(self, phone_e164: str, customer_id: str) -> LoyaltyIssueCardResult:
        raise LoyaltyGatewayError("temporary unavailable")


class FlakyLoyaltyGateway(LoyaltyGateway):
    """Тестовый шлюз: первая попытка падает, повторная — успешна."""

    def __init__(self) -> None:
        self._calls = 0

    def get_customer_info(self, phone_e164: str) -> LoyaltyCustomer | None:
        self._calls += 1
        if self._calls == 1:
            raise LoyaltyGatewayError("temporary unavailable")
        return LoyaltyCustomer(
            customer_id="cust-1",
            balance=0.0,
            cards=(LoyaltyCard(number="79123456789_20260325"),),
        )

    def register_customer(
        self,
        phone_e164: str,
        *,
        profile=None,
        customer_id: str | None = None,
    ) -> LoyaltyRegisterCustomerResult:
        return LoyaltyRegisterCustomerResult(customer_id="cust-1", message="registered")

    def issue_card_for_customer(self, phone_e164: str, customer_id: str) -> LoyaltyIssueCardResult:
        return LoyaltyIssueCardResult(card_number="79123456789_20260325", message="issued")


class LegacyPrefillLoyaltyGateway(LoyaltyGateway):
    """Тестовый шлюз, который возвращает профиль iiko для legacy-дозаполнения."""

    def get_customer_info(self, phone_e164: str) -> LoyaltyCustomer | None:
        return LoyaltyCustomer(
            customer_id="legacy-cust",
            balance=0.0,
            cards=(),
            first_name="Андрей",
            last_name="Соболев",
            gender="male",
            birth_date=date(1990, 5, 17),
            email="legacy@example.com",
        )

    def register_customer(
        self,
        phone_e164: str,
        *,
        profile=None,
        customer_id: str | None = None,
    ) -> LoyaltyRegisterCustomerResult:
        return LoyaltyRegisterCustomerResult(customer_id="legacy-cust", message="registered")

    def issue_card_for_customer(self, phone_e164: str, customer_id: str) -> LoyaltyIssueCardResult:
        return LoyaltyIssueCardResult(card_number="79123456789_20260325", message="issued")


def _build_adapter(with_support: bool = False) -> MaxIdentityAdapter:
    repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    if not with_support:
        return MaxIdentityAdapter(registration_use_case, lookup_use_case)

    def support_uow_factory() -> InMemorySupportUnitOfWork:
        return InMemorySupportUnitOfWork(repository, support_repository)

    create_ticket_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=support_uow_factory)
    moderator_reply_use_case = RouteModeratorReplyTransactionalUseCase(unit_of_work_factory=support_uow_factory, vk_pending_verification_delivery_enabled=True)
    ticket_details_use_case = GetSupportTicketDetailsTransactionalUseCase(unit_of_work_factory=support_uow_factory)
    ticket_conversation_use_case = GetSupportTicketConversationTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    list_open_tickets_use_case = ListOpenSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    list_person_tickets_use_case = ListPersonSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    return MaxIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        moderator_reply_use_case=moderator_reply_use_case,
        ticket_details_use_case=ticket_details_use_case,
        ticket_conversation_use_case=ticket_conversation_use_case,
        list_open_tickets_use_case=list_open_tickets_use_case,
        list_person_tickets_use_case=list_person_tickets_use_case,
    )


def _build_adapter_with_support_context() -> tuple[
    MaxIdentityAdapter,
    RegisterOrAttachAccountTransactionalUseCase,
    CreateSupportTicketTransactionalUseCase,
]:
    repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    def support_uow_factory() -> InMemorySupportUnitOfWork:
        return InMemorySupportUnitOfWork(repository, support_repository)

    create_ticket_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=support_uow_factory)
    moderator_reply_use_case = RouteModeratorReplyTransactionalUseCase(unit_of_work_factory=support_uow_factory, vk_pending_verification_delivery_enabled=True)
    ticket_details_use_case = GetSupportTicketDetailsTransactionalUseCase(unit_of_work_factory=support_uow_factory)
    ticket_conversation_use_case = GetSupportTicketConversationTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    list_open_tickets_use_case = ListOpenSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    list_person_tickets_use_case = ListPersonSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    adapter = MaxIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        moderator_reply_use_case=moderator_reply_use_case,
        ticket_details_use_case=ticket_details_use_case,
        ticket_conversation_use_case=ticket_conversation_use_case,
        list_open_tickets_use_case=list_open_tickets_use_case,
        list_person_tickets_use_case=list_person_tickets_use_case,
    )
    return adapter, registration_use_case, create_ticket_use_case


def _complete_max_registration(adapter: MaxIdentityAdapter, max_user_id: int = 1001) -> None:
    adapter.handle_start(max_user_id=max_user_id)
    adapter.handle_incoming(max_user_id=max_user_id, text="✅ Согласен", payload=None)
    adapter.handle_incoming(
        max_user_id=max_user_id,
        text="",
        payload=None,
        contact_phone="+79123456789",
    )
    adapter.handle_incoming(max_user_id=max_user_id, text="Иван", payload=None)
    adapter.handle_incoming(max_user_id=max_user_id, text="Да", payload=None)


def test_max_start_for_unregistered_user_requests_rules_consent() -> None:
    """Проверяет, что `/start` для нового пользователя запрашивает согласие."""

    adapter = _build_adapter()

    response = adapter.handle_start(max_user_id=1001)

    assert "Согласен" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "start_rules"


def test_max_onboarding_moves_from_rules_to_phone() -> None:
    """Проверяет переход onboarding из правил к шагу телефона."""

    adapter = _build_adapter()
    adapter.handle_start(max_user_id=1001)

    response = adapter.handle_incoming(max_user_id=1001, text="✅ Согласен", payload=None)

    assert "Поделиться контактом" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "start_contact"


def test_max_migrated_legacy_user_goes_to_legacy_phone_after_rules_consent() -> None:
    """Проверяет, что migrated legacy-пользователь после новых правил переходит в legacy-шаг телефона."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = MaxIdentityAdapter(registration_use_case, lookup_use_case)

    registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="max",
            external_id="3005",
            raw_phone="+79123456789",
            rules_accepted=False,
            is_legacy=True,
            is_registered=False,
        )
    )

    start_response = adapter.handle_start(max_user_id=3005)
    response = adapter.handle_incoming(max_user_id=3005, text="✅ Согласен", payload=None)

    assert start_response.screen is not None
    assert start_response.screen.screen_id == "start_rules"
    assert "предыдущей версии бота" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "start_contact"


def test_max_legacy_phone_step_prefills_profile_from_iiko() -> None:
    """Проверяет, что legacy-ветка после подтверждения телефона подтягивает пустые поля из iiko."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = MaxIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        loyalty_gateway=LegacyPrefillLoyaltyGateway(),
    )

    registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="max",
            external_id="3010",
            raw_phone="+79123456789",
            rules_accepted=False,
            is_legacy=True,
            is_registered=False,
        )
    )

    adapter.handle_start(max_user_id=3010)
    adapter.handle_incoming(max_user_id=3010, text="✅ Согласен", payload=None)
    phone_result = adapter.handle_incoming(
        max_user_id=3010,
        text="",
        payload=None,
        contact_phone="+79123456789",
    )

    resolved_person = lookup_use_case.execute(
        command=GetPersonByAccountCommand(platform="max", external_id="3010")
    )

    assert phone_result.screen is not None
    assert phone_result.screen.screen_id == "notifications_consent"
    assert resolved_person is not None
    assert resolved_person.first_name_input == "Андрей"
    assert resolved_person.last_name_input == "Соболев"
    assert resolved_person.gender == "male"
    assert resolved_person.birth_date == date(1990, 5, 17)
    assert resolved_person.email == "legacy@example.com"


def test_max_phone_match_with_telegram_legacy_switches_to_legacy_flow() -> None:
    """Проверяет авто-переход в legacy-ветку в MAX, если телефон найден у legacy-профиля Telegram."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = MaxIdentityAdapter(registration_use_case, lookup_use_case)

    registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="legacy-tg-2",
            raw_phone="+79123334455",
            first_name_input="Андрей",
            rules_accepted=False,
            is_legacy=True,
            is_registered=False,
        )
    )

    adapter.handle_start(max_user_id=4502)
    adapter.handle_incoming(max_user_id=4502, text="✅ Согласен", payload=None)
    response = adapter.handle_incoming(
        max_user_id=4502,
        text="",
        payload=None,
        contact_phone="+79123334455",
    )

    assert response.screen is not None
    assert response.screen.screen_id == "notifications_consent"


def test_max_phone_match_with_registered_profile_opens_menu_without_reasking_name() -> None:
    """Проверяет, что при привязке к уже зарегистрированному профилю MAX запрашивает согласие на рассылку."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = MaxIdentityAdapter(registration_use_case, lookup_use_case)

    registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="ready-tg-2",
            raw_phone="+79125556677",
            first_name_input="Андрей",
            rules_accepted=True,
            notifications_allowed=True,
            is_legacy=False,
            is_registered=True,
        )
    )

    adapter.handle_start(max_user_id=4602)
    adapter.handle_incoming(max_user_id=4602, text="✅ Согласен", payload=None)
    response = adapter.handle_incoming(
        max_user_id=4602,
        text="",
        payload=None,
        contact_phone="+79125556677",
    )

    attached_person = lookup_use_case.execute(
        command=GetPersonByAccountCommand(platform="max", external_id="4602")
    )

    assert response.screen is not None
    assert response.screen.screen_id == "notifications_consent"
    assert attached_person is not None
    assert attached_person.first_name_input == "Андрей"
    assert len(attached_person.accounts) == 2


def test_max_dirty_input_on_rules_step_keeps_consent_pending() -> None:
    """Проверяет грязный сценарий: случайный текст вместо согласия."""

    adapter = _build_adapter()
    adapter.handle_start(max_user_id=1001)

    response = adapter.handle_incoming(max_user_id=1001, text="хочу бонусы", payload=None)

    assert "Чтобы продолжить регистрацию" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "start_rules"


def test_max_registration_by_phone_after_rules_consent() -> None:
    """Проверяет переход к шагу ввода имени после согласия и ввода номера."""

    adapter = _build_adapter()
    adapter.handle_start(max_user_id=1001)
    adapter.handle_incoming(max_user_id=1001, text="✅ Согласен", payload=None)

    response = adapter.handle_incoming(
        max_user_id=1001,
        text="",
        payload=None,
        contact_phone="+7 (912) 345-67-89",
    )

    assert "имя" in response.text.lower()
    assert response.screen is None


def test_max_ignores_contact_outside_phone_step() -> None:
    """Проверяет, что контакт вне шага ввода телефона не запускает частичную привязку аккаунта."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = MaxIdentityAdapter(registration_use_case, lookup_use_case)

    response = adapter.handle_incoming(
        max_user_id=9090,
        text="",
        payload=None,
        contact_phone="+79125550123",
    )
    person = lookup_use_case.execute(
        GetPersonByAccountCommand(platform="max", external_id="9090")
    )

    assert response.screen is not None
    assert response.screen.screen_id == "start_rules"
    assert person is None


def test_max_profile_available_after_registration() -> None:
    """Проверяет получение профиля после регистрации."""

    adapter = _build_adapter()
    _complete_max_registration(adapter)

    response = adapter.handle_incoming(max_user_id=1001, text="👤 Профиль", payload=None)

    assert "Профиль пользователя" in response.text
    assert "+79123456789" in response.text


def test_max_adapter_builds_coupon_root_scope_and_card(monkeypatch) -> None:
    """Проверяет MAX-flow купонов: корень, список и карточка с QR payload."""

    coupon_id = UUID("22222222-2222-4222-8222-222222222222")
    coupon = _CouponItem(
        coupon_id=coupon_id,
        person_id=UUID("33333333-3333-4333-8333-333333333333"),
        coupon_series="SER-A",
        coupon_code="PROMO-2026-7777",
        campaign_id="CMP-1",
        venue_code="nani",
        venue_name="Грузинка Нани",
        promo_text="Подарочный десерт",
        status="sent",
        is_visible=True,
        updated_at=datetime(2026, 5, 15, 8, 30, tzinfo=timezone.utc),
    )

    class _FakeCouponsRepository:
        def __init__(self, session: object) -> None:
            self._session = session

        def count_visible_global_coupons(self, *, person_id: UUID) -> int:
            return 1

        def list_visible_venues(self, *, person_id: UUID) -> tuple[_CouponVenue, ...]:
            return (_CouponVenue(venue_code="nani", venue_name="Грузинка Нани", coupons_count=1),)

        def list_visible_coupons(self, *, person_id: UUID, venue_code: str) -> tuple[_CouponItem, ...]:
            assert venue_code == "nani"
            return (coupon,)

        def get_coupon(self, *, person_id: UUID, coupon_id: UUID) -> _CouponItem | None:
            return coupon

    monkeypatch.setattr(max_identity_module, "SQLAlchemySagurCouponsRepository", _FakeCouponsRepository)

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = MaxIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        coupon_session_factory=_FakeCouponSessionFactory(),
    )
    _complete_max_registration(adapter)

    root = adapter.handle_incoming(max_user_id=1001, text="", payload="coupons")
    assert root.screen is not None
    assert root.screen.screen_id == "coupons_root"
    assert root.screen.rows[0][0].label == "🎟️ Общие (1)"
    assert root.screen.rows[1][0].label == "🏠 Грузинка Нани (1)"

    venue_payload = root.screen.rows[1][0].payload
    coupon_list = adapter.handle_incoming(max_user_id=1001, text="", payload=venue_payload)
    assert coupon_list.screen is not None
    assert coupon_list.screen.screen_id == "coupon_list"
    assert coupon_list.screen.rows[0][0].label == "🎟️ Купон • 7777"

    card_payload = coupon_list.screen.rows[0][0].payload
    card = adapter.handle_incoming(max_user_id=1001, text="", payload=card_payload)
    assert card.screen is not None
    assert card.screen.screen_id == "coupon_card"
    assert card.coupon_qr_payload == "PROMO-2026-7777"
    assert card.coupon_qr_caption == "🎟️ Купон • 7777"
    assert "Подарочный десерт" in card.text


def test_max_adapter_returns_empty_coupon_screen(monkeypatch) -> None:
    """Проверяет пустой экран купонов в MAX."""

    class _FakeCouponsRepository:
        def __init__(self, session: object) -> None:
            self._session = session

        def count_visible_global_coupons(self, *, person_id: UUID) -> int:
            return 0

        def list_visible_venues(self, *, person_id: UUID) -> tuple[_CouponVenue, ...]:
            return ()

    monkeypatch.setattr(max_identity_module, "SQLAlchemySagurCouponsRepository", _FakeCouponsRepository)

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = MaxIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        coupon_session_factory=_FakeCouponSessionFactory(),
    )
    _complete_max_registration(adapter)

    response = adapter.handle_incoming(max_user_id=1001, text="", payload="coupons")

    assert response.screen is not None
    assert response.screen.screen_id == "coupons_root"
    assert len(response.screen.rows) == 1
    assert response.screen.rows[0][0].label == "🔙 Назад в профиль"
    assert "активных купонов нет" in response.text


def test_max_start_for_registered_user_uses_first_name_in_menu() -> None:
    """Проверяет, что главное меню для зарегистрированного пользователя показывает имя."""

    adapter = _build_adapter()
    _complete_max_registration(adapter)

    response = adapter.handle_start(max_user_id=1001)

    assert "Иван" in response.text
    assert "главном меню" in response.text


def test_max_onboarding_iiko_failure_moves_to_retry_step() -> None:
    """Проверяет отдельный шаг retry, если синхронизация с iiko не удалась."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = MaxIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        virtual_card_use_case=GetVirtualCardUseCase(AlwaysFailLoyaltyGateway()),
    )

    adapter.handle_start(max_user_id=2001)
    adapter.handle_incoming(max_user_id=2001, text="✅ Согласен", payload=None)
    adapter.handle_incoming(max_user_id=2001, text="", payload=None, contact_phone="+79123456789")
    adapter.handle_incoming(max_user_id=2001, text="Иван", payload=None)
    failure_result = adapter.handle_incoming(max_user_id=2001, text="Да", payload=None)

    assert failure_result.screen is not None
    assert failure_result.screen.screen_id == "iiko_sync_retry"
    assert "синхронизац" in failure_result.text.lower()

    pending_result = adapter.handle_incoming(max_user_id=2001, text="Главное меню", payload=None)
    assert pending_result.screen is not None
    assert pending_result.screen.screen_id == "iiko_sync_retry"
    assert "Повторить синхронизацию" in pending_result.text


def test_max_onboarding_iiko_retry_eventually_returns_menu() -> None:
    """Проверяет успешный выход в меню после повторной синхронизации iiko."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = MaxIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        virtual_card_use_case=GetVirtualCardUseCase(FlakyLoyaltyGateway()),
    )

    adapter.handle_start(max_user_id=2002)
    adapter.handle_incoming(max_user_id=2002, text="✅ Согласен", payload=None)
    adapter.handle_incoming(max_user_id=2002, text="", payload=None, contact_phone="+79123456789")
    adapter.handle_incoming(max_user_id=2002, text="Иван", payload=None)

    first_try = adapter.handle_incoming(max_user_id=2002, text="Да", payload=None)
    second_try = adapter.handle_incoming(max_user_id=2002, text="", payload="retry_iiko_sync")

    assert first_try.screen is not None
    assert first_try.screen.screen_id == "iiko_sync_retry"
    assert second_try.screen is not None
    assert second_try.screen.screen_id == "main_menu"
    assert second_try.virtual_card_numbers == ("79123456789_20260325",)


def test_max_balance_uses_loyalty_use_case() -> None:
    """Проверяет, что пункт «Мой баланс» возвращает данные из loyalty use-case."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    loyalty_gateway = StubLoyaltyGateway(
        customer=LoyaltyCustomer(customer_id="cust-1", balance=44.5, cards=())
    )
    adapter = MaxIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        balance_use_case=GetLoyaltyBalanceUseCase(loyalty_gateway),
    )
    _complete_max_registration(adapter)

    response = adapter.handle_incoming(max_user_id=1001, text="💰 Мой баланс", payload=None)

    assert "44.50" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "balance"


def test_max_virtual_card_error_has_back_button_and_creates_auto_ticket() -> None:
    """Проверяет, что при критической ошибке iiko по карте есть возврат в меню и создается автотикет."""

    repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    def support_uow_factory() -> InMemorySupportUnitOfWork:
        return InMemorySupportUnitOfWork(repository, support_repository)

    create_ticket_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=support_uow_factory)
    list_person_tickets_use_case = ListPersonSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    adapter = MaxIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        list_person_tickets_use_case=list_person_tickets_use_case,
        virtual_card_use_case=GetVirtualCardUseCase(AlwaysFailLoyaltyGateway()),
    )
    registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="max",
            external_id="1001",
            raw_phone="+79123456789",
            first_name_input="Иван",
            rules_accepted=True,
            notifications_allowed=True,
            is_registered=True,
        )
    )

    response = adapter.handle_incoming(max_user_id=1001, text="🪪 Карта", payload=None)
    tickets = list_person_tickets_use_case.execute(
        platform="max",
        external_id="1001",
        limit=10,
    )

    assert "IIKO-CARD-001" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "balance"
    assert len(tickets) == 1
    assert tickets[0].status.value == "open"


def test_max_virtual_card_uses_loyalty_use_case() -> None:
    """Проверяет, что пункт «Виртуальная карта» возвращает номер карты из loyalty use-case."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    loyalty_gateway = StubLoyaltyGateway(
        customer=LoyaltyCustomer(
            customer_id="cust-1",
            balance=0.0,
            cards=(LoyaltyCard(number="79123456789_20260325"),),
        )
    )
    adapter = MaxIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        virtual_card_use_case=GetVirtualCardUseCase(loyalty_gateway),
    )
    _complete_max_registration(adapter)

    response = adapter.handle_incoming(max_user_id=1001, text="🪪 Карта", payload=None)

    assert "Назад в меню" in response.text
    assert response.virtual_card_numbers == ("79123456789_20260325",)
    assert response.screen is not None
    assert response.screen.screen_id == "virtual_card_result"


def test_max_invalid_phone_returns_validation_error() -> None:
    """Проверяет негативный сценарий при невалидном номере."""

    adapter = _build_adapter()
    adapter.handle_start(max_user_id=1001)
    adapter.handle_incoming(max_user_id=1001, text="✅ Согласен", payload=None)

    response = adapter.handle_incoming(max_user_id=1001, text="abc", payload=None)

    assert "только через кнопку" in response.text


def test_max_support_question_activates_question_input_when_no_tickets() -> None:
    """Проверяет, что пункт «Мне только спросить» активирует ввод вопроса, если нет тикетов."""

    adapter = _build_adapter()
    _complete_max_registration(adapter)

    result = adapter.handle_incoming(
        max_user_id=1001,
        text="❓ Мне только спросить",
        payload=None,
    )

    assert "введите ваш вопрос" in result.text.lower()
    assert result.screen is not None
    assert result.screen.screen_id == "support_question"


def test_max_support_back_does_not_create_ticket_while_waiting_question() -> None:
    """Проверяет, что callback `back_to_support` не создает тикет в MAX."""

    adapter, _, _ = _build_adapter_with_support_context()
    _complete_max_registration(adapter, max_user_id=1002)

    adapter.handle_incoming(
        max_user_id=1002,
        text="❓ Мне только спросить",
        payload=None,
    )
    back_result = adapter.handle_incoming(
        max_user_id=1002,
        text="",
        payload="back_to_support",
    )

    assert back_result.screen is not None
    assert back_result.screen.screen_id == "support_menu"
    assert "Ваш вопрос принят" not in back_result.text


def test_max_my_tickets_shows_created_tickets() -> None:
    """Проверяет раздел «Мои обращения»: после создания тикета возвращается список."""

    adapter, _, create_ticket_use_case = _build_adapter_with_support_context()
    _complete_max_registration(adapter)

    create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="max",
            external_id="1001",
            question_text="Нужна помощь",
        )
    )
    tickets_response = adapter.handle_incoming(max_user_id=1001, text="📋 Мои обращения", payload=None)

    assert "Ваши обращения" in tickets_response.text
    assert "#" in tickets_response.text  # Короткий идентификатор тикета


def test_max_legacy_start_requests_phone_confirmation() -> None:
    """Проверяет legacy-ветку с подтверждением телефона для зарегистрированного пользователя."""

    adapter = _build_adapter()
    _complete_max_registration(adapter)

    legacy_start = adapter.handle_legacy_start(max_user_id=1001)
    confirm = adapter.handle_incoming(
        max_user_id=1001,
        text="",
        payload=None,
        contact_phone="+79123456789",
    )
    finish = adapter.handle_incoming(max_user_id=1001, text="Да", payload=None)

    assert "предыдущей версии бота" in legacy_start.text
    assert legacy_start.screen is not None
    assert legacy_start.screen.screen_id == "start_contact"
    assert confirm.screen is not None
    assert confirm.screen.screen_id == "notifications_consent"
    assert "Регистрация успешно завершена." in finish.text


def test_max_moderator_reply_can_route_to_another_messenger() -> None:
    """Проверяет модерацию: ответ из MAX с доставкой в другой канал."""

    adapter, register_use_case, create_ticket_use_case = _build_adapter_with_support_context()
    _complete_max_registration(adapter, max_user_id=1001)

    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="vk-777",
            raw_phone="+79123456789",
        )
    )

    created_ticket = create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="max",
            external_id="1001",
            question_text="Нужна помощь",
        )
    )
    ticket_id = str(created_ticket.ticket_id)

    forbidden = adapter.handle_incoming(max_user_id=9999, text="/mod", payload=None)
    assert "Команда /mod доступна только модераторам." in forbidden.text

    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="max",
            external_id="9999",
            raw_phone="+79990009999",
        )
    )
    moderator_person = adapter._person_lookup_use_case.execute(  # noqa: SLF001
        GetPersonByAccountCommand(platform="max", external_id="9999")
    )
    assert moderator_person is not None
    with register_use_case._unit_of_work_factory() as unit_of_work:  # noqa: SLF001
        unit_of_work.identity_repository.update_person_profile(
            moderator_person.person_id,
            PersonProfilePatch(is_moderator=True),
        )
        unit_of_work.commit()

    open_menu = adapter.handle_incoming(max_user_id=9999, text="/mod", payload=None)
    wait_ticket = adapter.handle_incoming(max_user_id=9999, text="2", payload=None)
    wait_reply = adapter.handle_incoming(max_user_id=9999, text=ticket_id, payload=None)
    routed = adapter.handle_incoming(max_user_id=9999, text="--to=vk Ответ отправлен.", payload=None)
    wait_details = adapter.handle_incoming(max_user_id=9999, text="3", payload=None)
    details = adapter.handle_incoming(max_user_id=9999, text=ticket_id, payload=None)
    unsupported = adapter.handle_incoming(
        max_user_id=9999,
        text=f"/modreply {ticket_id} --to=vk Тест",
        payload=None,
    )

    assert "Меню модератора" in open_menu.text
    assert "Введите UUID тикета" in wait_ticket.text
    assert "Введите текст ответа модератора" in wait_reply.text
    assert "Маршрут доставки: vk" in routed.text
    assert "Введите UUID тикета, чтобы показать карточку обращения." in wait_details.text
    assert "Гость" in details.text
    assert "Канал создания:" not in details.text
    assert "max" in details.text
    assert "Не удалось распознать пункт меню модератора." in unsupported.text


def test_max_moderation_menu_fsm_supports_dirty_and_success_paths() -> None:
    """Проверяет `/mod`-меню: список тикетов, грязный UUID и успешный ответ."""

    adapter, register_use_case, create_ticket_use_case = _build_adapter_with_support_context()
    _complete_max_registration(adapter, max_user_id=1001)

    created_ticket = create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="max",
            external_id="1001",
            question_text="Нужна помощь",
        )
    )
    ticket_id = str(created_ticket.ticket_id)

    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="max",
            external_id="9999",
            raw_phone="+79990009999",
        )
    )
    moderator_person = adapter._person_lookup_use_case.execute(  # noqa: SLF001
        GetPersonByAccountCommand(platform="max", external_id="9999")
    )
    assert moderator_person is not None
    with register_use_case._unit_of_work_factory() as unit_of_work:  # noqa: SLF001
        unit_of_work.identity_repository.update_person_profile(
            moderator_person.person_id,
            PersonProfilePatch(is_moderator=True),
        )
        unit_of_work.commit()

    open_menu = adapter.handle_incoming(max_user_id=9999, text="/mod", payload=None)
    open_tickets = adapter.handle_incoming(max_user_id=9999, text="1", payload=None)
    wait_ticket = adapter.handle_incoming(max_user_id=9999, text="2", payload=None)
    dirty_ticket = adapter.handle_incoming(max_user_id=9999, text="не-uuid", payload=None)
    wait_reply = adapter.handle_incoming(max_user_id=9999, text=ticket_id, payload=None)
    routed = adapter.handle_incoming(max_user_id=9999, text="Ответ принят", payload=None)
    wait_details = adapter.handle_incoming(max_user_id=9999, text="3", payload=None)
    details = adapter.handle_incoming(max_user_id=9999, text=ticket_id, payload=None)

    assert "Меню модератора" in open_menu.text
    assert "Новые обращения:" in open_tickets.text
    assert "Введите UUID тикета" in wait_ticket.text
    assert "Некорректный ticket_id" in dirty_ticket.text
    assert "Введите текст ответа модератора" in wait_reply.text
    assert "Маршрут доставки: max" in routed.text
    assert "Введите UUID тикета, чтобы показать карточку обращения." in wait_details.text
    assert "Гость" in details.text
    assert "Канал создания:" not in details.text
    assert "max" in details.text


def test_max_moderation_callback_menu_supports_pagination_and_ticket_actions() -> None:
    """Проверяет callback-меню модератора MAX: фильтр, пагинацию, карточку и ответ."""

    adapter, register_use_case, create_ticket_use_case = _build_adapter_with_support_context()
    _complete_max_registration(adapter, max_user_id=1001)

    created_tickets = [
        create_ticket_use_case.execute(
            CreateSupportTicketCommand(
                platform="max",
                external_id="1001",
                question_text=f"Нужна помощь #{index}",
            )
        )
        for index in range(6)
    ]
    first_ticket_id = created_tickets[0].ticket_id

    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="max",
            external_id="9999",
            raw_phone="+79990009999",
        )
    )
    moderator_person = adapter._person_lookup_use_case.execute(  # noqa: SLF001
        GetPersonByAccountCommand(platform="max", external_id="9999")
    )
    assert moderator_person is not None
    with register_use_case._unit_of_work_factory() as unit_of_work:  # noqa: SLF001
        unit_of_work.identity_repository.update_person_profile(
            moderator_person.person_id,
            PersonProfilePatch(is_moderator=True),
        )
        unit_of_work.commit()

    open_menu = adapter.handle_incoming(max_user_id=9999, text="/mod", payload=None)
    list_page = adapter.handle_incoming(max_user_id=9999, text="", payload="mod_list_new")
    details = adapter.handle_incoming(
        max_user_id=9999,
        text="",
        payload=f"mod_ticket_{first_ticket_id}_new_1",
    )
    start_reply = adapter.handle_incoming(
        max_user_id=9999,
        text="",
        payload=f"mod_reply_{first_ticket_id}_new_1",
    )
    routed = adapter.handle_incoming(max_user_id=9999, text="Тестовый ответ", payload=None)

    assert open_menu.screen is not None
    assert open_menu.screen.screen_id == "moderation_main"
    assert list_page.screen is not None
    assert list_page.screen.screen_id == "moderation_tickets"
    assert "Страница 1/" in list_page.text
    assert details.screen is not None
    assert details.screen.screen_id == "moderation_ticket_details"
    assert "👤" in details.text
    assert "Канал создания:" not in details.text
    assert "Введите текст ответа модератора" in start_reply.text
    assert start_reply.screen is not None
    assert start_reply.screen.screen_id == "moderation_reply_cancel"
    assert any(
        button.label == "❌ Отмена"
        for row in start_reply.screen.rows
        for button in row
    )
    assert "Ответ модератора зарегистрирован" in routed.text


def test_max_ticket_details_screen_includes_ticket_history() -> None:
    """Проверяет, что карточка тикета в MAX содержит историю сообщений, а не заглушку."""

    adapter, _register_use_case, create_ticket_use_case = _build_adapter_with_support_context()
    _complete_max_registration(adapter, max_user_id=1001)

    created_ticket = create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="max",
            external_id="1001",
            question_text="Нужна помощь с бонусами по карте",
        )
    )

    response = adapter.handle_incoming(
        max_user_id=1001,
        text="",
        payload={"cmd": f"user_ticket_{created_ticket.ticket_id}"},
    )

    assert response.parse_mode == "html"
    assert "История переписки" in response.text
    assert "Нужна помощь с бонусами по карте" in response.text
    assert "<blockquote>" in response.text
    assert "Гость" in response.text
    assert "недоступн" not in response.text.lower()

