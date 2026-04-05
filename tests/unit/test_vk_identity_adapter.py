"""РўРµСЃС‚С‹ VK identity-Р°РґР°РїС‚РµСЂР°."""

from __future__ import annotations

from datetime import date
from types import TracebackType

from vtelemax.adapters.vk import VkIdentityAdapter
from vtelemax.core import (
    CreateSupportTicketCommand,
    CreateSupportTicketTransactionalUseCase,
    GetLoyaltyBalanceUseCase,
    GetPersonByAccountCommand,
    GetPersonByAccountTransactionalUseCase,
    GetVirtualCardUseCase,
    ListOpenSupportTicketsTransactionalUseCase,
    ListPersonSupportTicketsTransactionalUseCase,
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
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
    RouteModeratorReplyTransactionalUseCase,
)


class InMemoryIdentityUnitOfWork(IdentityUnitOfWork):
    """РўРµСЃС‚РѕРІС‹Р№ UnitOfWork РїРѕРІРµСЂС… in-memory СЂРµРїРѕР·РёС‚РѕСЂРёСЏ."""

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
    """РўРµСЃС‚РѕРІС‹Р№ UoW СЃ РїРѕРґРґРµСЂР¶РєРѕР№ С‚РёРєРµС‚РѕРІ."""

    def __init__(self, repository: IdentityRepository, support_repository: InMemorySupportRepository) -> None:
        super().__init__(repository)
        self.support_repository = support_repository


class StubLoyaltyGateway(LoyaltyGateway):
    """РўРµСЃС‚РѕРІС‹Р№ С€Р»СЋР· Р»РѕСЏР»СЊРЅРѕСЃС‚Рё РґР»СЏ РїСЂРѕРІРµСЂРєРё РјРµРЅСЋ В«Р‘Р°Р»Р°РЅСЃ/Р’РёСЂС‚СѓР°Р»СЊРЅР°СЏ РєР°СЂС‚Р°В»."""

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
    """РўРµСЃС‚РѕРІС‹Р№ С€Р»СЋР·, РєРѕС‚РѕСЂС‹Р№ РІСЃРµРіРґР° РІРѕР·РІСЂР°С‰Р°РµС‚ РѕС€РёР±РєСѓ iiko."""

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
    """РўРµСЃС‚РѕРІС‹Р№ С€Р»СЋР·: РїРµСЂРІР°СЏ РїРѕРїС‹С‚РєР° РїР°РґР°РµС‚, РїРѕРІС‚РѕСЂРЅР°СЏ вЂ” СѓСЃРїРµС€РЅР°."""

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
    """РўРµСЃС‚РѕРІС‹Р№ С€Р»СЋР·, РєРѕС‚РѕСЂС‹Р№ РІРѕР·РІСЂР°С‰Р°РµС‚ РїСЂРѕС„РёР»СЊ iiko РґР»СЏ legacy-РґРѕР·Р°РїРѕР»РЅРµРЅРёСЏ."""

    def get_customer_info(self, phone_e164: str) -> LoyaltyCustomer | None:
        return LoyaltyCustomer(
            customer_id="legacy-cust",
            balance=0.0,
            cards=(),
            first_name="РђРЅРґСЂРµР№",
            last_name="РЎРѕР±РѕР»РµРІ",
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


def _build_adapter(with_support: bool = False) -> VkIdentityAdapter:
    repository = InMemoryIdentityRepository()
    support_repository = InMemorySupportRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    if not with_support:
        return VkIdentityAdapter(registration_use_case, lookup_use_case)

    support_uow_factory = lambda: InMemorySupportUnitOfWork(repository, support_repository)
    create_ticket_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=support_uow_factory)
    moderator_reply_use_case = RouteModeratorReplyTransactionalUseCase(unit_of_work_factory=support_uow_factory)
    ticket_details_use_case = GetSupportTicketDetailsTransactionalUseCase(unit_of_work_factory=support_uow_factory)
    list_open_tickets_use_case = ListOpenSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    list_person_tickets_use_case = ListPersonSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    return VkIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        moderator_reply_use_case=moderator_reply_use_case,
        ticket_details_use_case=ticket_details_use_case,
        list_open_tickets_use_case=list_open_tickets_use_case,
        list_person_tickets_use_case=list_person_tickets_use_case,
    )


def _build_adapter_with_support_context() -> tuple[
    VkIdentityAdapter,
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
    support_uow_factory = lambda: InMemorySupportUnitOfWork(repository, support_repository)
    create_ticket_use_case = CreateSupportTicketTransactionalUseCase(unit_of_work_factory=support_uow_factory)
    moderator_reply_use_case = RouteModeratorReplyTransactionalUseCase(unit_of_work_factory=support_uow_factory)
    ticket_details_use_case = GetSupportTicketDetailsTransactionalUseCase(unit_of_work_factory=support_uow_factory)
    list_open_tickets_use_case = ListOpenSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    list_person_tickets_use_case = ListPersonSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    adapter = VkIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        moderator_reply_use_case=moderator_reply_use_case,
        ticket_details_use_case=ticket_details_use_case,
        list_open_tickets_use_case=list_open_tickets_use_case,
        list_person_tickets_use_case=list_person_tickets_use_case,
    )
    return adapter, registration_use_case, create_ticket_use_case


def _complete_vk_registration(adapter: VkIdentityAdapter, vk_user_id: int = 1001) -> None:
    adapter.handle_start(vk_user_id=vk_user_id)
    adapter.handle_incoming(vk_user_id=vk_user_id, text="вњ… РЎРѕРіР»Р°СЃРµРЅ", payload=None)
    adapter.handle_incoming(vk_user_id=vk_user_id, text="+79123456789", payload=None)
    adapter.handle_incoming(vk_user_id=vk_user_id, text="РРІР°РЅ", payload=None)
    adapter.handle_incoming(vk_user_id=vk_user_id, text="Р”Р°", payload=None)


def test_vk_start_for_unregistered_user_requests_rules_consent() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚, С‡С‚Рѕ `/start` РґР»СЏ РЅРѕРІРѕРіРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ Р·Р°РїСЂР°С€РёРІР°РµС‚ СЃРѕРіР»Р°СЃРёРµ."""

    adapter = _build_adapter()

    response = adapter.handle_start(vk_user_id=1001)

    assert "РЎРѕРіР»Р°СЃРµРЅ" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "start_rules"


def test_vk_onboarding_moves_from_rules_to_phone() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚ РїРµСЂРµС…РѕРґ onboarding РёР· РїСЂР°РІРёР» Рє С€Р°РіСѓ С‚РµР»РµС„РѕРЅР°."""

    adapter = _build_adapter()
    adapter.handle_start(vk_user_id=1001)

    response = adapter.handle_incoming(vk_user_id=1001, text="вњ… РЎРѕРіР»Р°СЃРµРЅ", payload=None)

    assert "+79991234567" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "start_contact"


def test_vk_migrated_legacy_user_goes_to_legacy_phone_after_rules_consent() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚, С‡С‚Рѕ migrated legacy-РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РїРѕСЃР»Рµ РЅРѕРІС‹С… РїСЂР°РІРёР» РїРµСЂРµС…РѕРґРёС‚ РІ legacy-С€Р°Рі С‚РµР»РµС„РѕРЅР°."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = VkIdentityAdapter(registration_use_case, lookup_use_case)

    registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="3005",
            raw_phone="+79123456789",
            rules_accepted=False,
            is_legacy=True,
            is_registered=False,
        )
    )

    start_response = adapter.handle_start(vk_user_id=3005)
    response = adapter.handle_incoming(vk_user_id=3005, text="вњ… РЎРѕРіР»Р°СЃРµРЅ", payload=None)

    assert start_response.screen is not None
    assert start_response.screen.screen_id == "start_rules"
    assert "РїСЂРµРґС‹РґСѓС‰РµР№ РІРµСЂСЃРёРё Р±РѕС‚Р°" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "start_contact"


def test_vk_legacy_phone_step_prefills_profile_from_iiko() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚, С‡С‚Рѕ legacy-РІРµС‚РєР° РїРѕСЃР»Рµ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёСЏ С‚РµР»РµС„РѕРЅР° РїРѕРґС‚СЏРіРёРІР°РµС‚ РїСѓСЃС‚С‹Рµ РїРѕР»СЏ РёР· iiko."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = VkIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        loyalty_gateway=LegacyPrefillLoyaltyGateway(),
    )

    registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="3010",
            raw_phone="+79123456789",
            rules_accepted=False,
            is_legacy=True,
            is_registered=False,
        )
    )

    adapter.handle_start(vk_user_id=3010)
    adapter.handle_incoming(vk_user_id=3010, text="вњ… РЎРѕРіР»Р°СЃРµРЅ", payload=None)
    phone_result = adapter.handle_incoming(vk_user_id=3010, text="+79123456789", payload=None)

    resolved_person = lookup_use_case.execute(
        command=GetPersonByAccountCommand(platform="vk", external_id="3010")
    )

    assert phone_result.screen is not None
    assert phone_result.screen.screen_id == "notifications_consent"
    assert resolved_person is not None
    assert resolved_person.first_name_input == "РђРЅРґСЂРµР№"
    assert resolved_person.last_name_input == "РЎРѕР±РѕР»РµРІ"
    assert resolved_person.gender == "male"
    assert resolved_person.birth_date == date(1990, 5, 17)
    assert resolved_person.email == "legacy@example.com"


def test_vk_phone_match_with_telegram_legacy_switches_to_legacy_flow() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚ Р°РІС‚Рѕ-РїРµСЂРµС…РѕРґ РІ legacy-РІРµС‚РєСѓ РІ VK, РµСЃР»Рё С‚РµР»РµС„РѕРЅ РЅР°Р№РґРµРЅ Сѓ legacy-РїСЂРѕС„РёР»СЏ Telegram."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = VkIdentityAdapter(registration_use_case, lookup_use_case)

    registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="legacy-tg-1",
            raw_phone="+79121112233",
            first_name_input="РђРЅРґСЂРµР№",
            rules_accepted=False,
            is_legacy=True,
            is_registered=False,
        )
    )

    adapter.handle_start(vk_user_id=4501)
    adapter.handle_incoming(vk_user_id=4501, text="вњ… РЎРѕРіР»Р°СЃРµРЅ", payload=None)
    response = adapter.handle_incoming(vk_user_id=4501, text="+79121112233", payload=None)

    assert response.screen is not None
    assert response.screen.screen_id == "notifications_consent"


def test_vk_phone_match_with_registered_profile_opens_menu_without_reasking_name() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚, С‡С‚Рѕ РїСЂРё РїСЂРёРІСЏР·РєРµ Рє СѓР¶Рµ Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°РЅРЅРѕРјСѓ РїСЂРѕС„РёР»СЋ VK СЃСЂР°Р·Сѓ РѕС‚РєСЂС‹РІР°РµС‚ РјРµРЅСЋ."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = VkIdentityAdapter(registration_use_case, lookup_use_case)

    registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="ready-tg-1",
            raw_phone="+79124445566",
            first_name_input="РђРЅРґСЂРµР№",
            rules_accepted=True,
            notifications_allowed=True,
            is_legacy=False,
            is_registered=True,
        )
    )

    adapter.handle_start(vk_user_id=4601)
    adapter.handle_incoming(vk_user_id=4601, text="вњ… РЎРѕРіР»Р°СЃРµРЅ", payload=None)
    response = adapter.handle_incoming(vk_user_id=4601, text="+79124445566", payload=None)

    attached_person = lookup_use_case.execute(
        command=GetPersonByAccountCommand(platform="vk", external_id="4601")
    )

    assert response.screen is not None
    assert response.screen.screen_id == "notifications_consent"
    assert attached_person is not None
    assert attached_person.first_name_input == "РђРЅРґСЂРµР№"
    assert len(attached_person.accounts) == 2


def test_vk_start_for_registered_profile_without_vk_consents_continues_onboarding() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚, С‡С‚Рѕ `/start` РІ VK РЅРµ РїСЂРѕРїСѓСЃРєР°РµС‚ РѕР±СЏР·Р°С‚РµР»СЊРЅС‹Рµ РїР»Р°С‚С„РѕСЂРјРµРЅРЅС‹Рµ СЃРѕРіР»Р°СЃРёСЏ."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = VkIdentityAdapter(registration_use_case, lookup_use_case)

    registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="ready-tg-for-vk-start",
            raw_phone="+79129990011",
            first_name_input="РђРЅРґСЂРµР№",
            rules_accepted=True,
            notifications_allowed=True,
            is_registered=True,
        )
    )
    registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="4901",
            raw_phone="+79129990011",
        )
    )

    start_response = adapter.handle_start(vk_user_id=4901)

    assert start_response.screen is not None
    assert start_response.screen.screen_id == "start_rules"
    assert "РЎРѕРіР»Р°СЃРµРЅ" in start_response.text


def test_vk_dirty_input_on_rules_step_keeps_consent_pending() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚ РіСЂСЏР·РЅС‹Р№ СЃС†РµРЅР°СЂРёР№: СЃР»СѓС‡Р°Р№РЅС‹Р№ С‚РµРєСЃС‚ РІРјРµСЃС‚Рѕ СЃРѕРіР»Р°СЃРёСЏ."""

    adapter = _build_adapter()
    adapter.handle_start(vk_user_id=1001)

    response = adapter.handle_incoming(vk_user_id=1001, text="С…РѕС‡Сѓ Р±РѕРЅСѓСЃС‹", payload=None)

    assert "Р§С‚РѕР±С‹ РїСЂРѕРґРѕР»Р¶РёС‚СЊ СЂРµРіРёСЃС‚СЂР°С†РёСЋ" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "start_rules"


def test_vk_registration_by_phone_after_rules_consent() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚ РїРµСЂРµС…РѕРґ Рє С€Р°РіСѓ РІРІРѕРґР° РёРјРµРЅРё РїРѕСЃР»Рµ СЃРѕРіР»Р°СЃРёСЏ Рё РІРІРѕРґР° РЅРѕРјРµСЂР°."""

    adapter = _build_adapter()
    adapter.handle_start(vk_user_id=1001)
    adapter.handle_incoming(vk_user_id=1001, text="вњ… РЎРѕРіР»Р°СЃРµРЅ", payload=None)

    response = adapter.handle_incoming(vk_user_id=1001, text="+7 (912) 345-67-89", payload=None)

    assert "РёРјСЏ" in response.text.lower()
    assert response.screen is None


def test_vk_profile_available_after_registration() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚ РїРѕР»СѓС‡РµРЅРёРµ РїСЂРѕС„РёР»СЏ РїРѕСЃР»Рµ СЂРµРіРёСЃС‚СЂР°С†РёРё."""

    adapter = _build_adapter()
    _complete_vk_registration(adapter)

    response = adapter.handle_incoming(vk_user_id=1001, text="рџ‘¤ РџСЂРѕС„РёР»СЊ", payload=None)

    assert "РџСЂРѕС„РёР»СЊ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ" in response.text
    assert "+79123456789" in response.text


def test_vk_start_for_registered_user_uses_first_name_in_menu() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚, С‡С‚Рѕ РіР»Р°РІРЅРѕРµ РјРµРЅСЋ РґР»СЏ Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°РЅРЅРѕРіРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ РїРѕРєР°Р·С‹РІР°РµС‚ РёРјСЏ."""

    adapter = _build_adapter()
    _complete_vk_registration(adapter)

    response = adapter.handle_start(vk_user_id=1001)

    assert "РРІР°РЅ" in response.text
    assert "РіР»Р°РІРЅРѕРј РјРµРЅСЋ" in response.text


def test_vk_onboarding_iiko_failure_moves_to_retry_step() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚ РѕС‚РґРµР»СЊРЅС‹Р№ С€Р°Рі retry, РµСЃР»Рё СЃРёРЅС…СЂРѕРЅРёР·Р°С†РёСЏ СЃ iiko РЅРµ СѓРґР°Р»Р°СЃСЊ."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = VkIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        virtual_card_use_case=GetVirtualCardUseCase(AlwaysFailLoyaltyGateway()),
    )

    adapter.handle_start(vk_user_id=2001)
    adapter.handle_incoming(vk_user_id=2001, text="вњ… РЎРѕРіР»Р°СЃРµРЅ", payload=None)
    adapter.handle_incoming(vk_user_id=2001, text="+79123456789", payload=None)
    adapter.handle_incoming(vk_user_id=2001, text="РРІР°РЅ", payload=None)
    failure_result = adapter.handle_incoming(vk_user_id=2001, text="Р”Р°", payload=None)

    assert failure_result.screen is not None
    assert failure_result.screen.screen_id == "iiko_sync_retry"
    assert "СЃРёРЅС…СЂРѕРЅРёР·Р°С†" in failure_result.text.lower()

    pending_result = adapter.handle_incoming(vk_user_id=2001, text="/menu", payload=None)
    assert pending_result.screen is not None
    assert pending_result.screen.screen_id == "iiko_sync_retry"
    assert "РџРѕРІС‚РѕСЂРёС‚СЊ СЃРёРЅС…СЂРѕРЅРёР·Р°С†РёСЋ" in pending_result.text


def test_vk_onboarding_iiko_retry_eventually_returns_menu() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚ СѓСЃРїРµС€РЅС‹Р№ РІС‹С…РѕРґ РІ РјРµРЅСЋ РїРѕСЃР»Рµ РїРѕРІС‚РѕСЂРЅРѕР№ СЃРёРЅС…СЂРѕРЅРёР·Р°С†РёРё iiko."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = VkIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        virtual_card_use_case=GetVirtualCardUseCase(FlakyLoyaltyGateway()),
    )

    adapter.handle_start(vk_user_id=2002)
    adapter.handle_incoming(vk_user_id=2002, text="вњ… РЎРѕРіР»Р°СЃРµРЅ", payload=None)
    adapter.handle_incoming(vk_user_id=2002, text="+79123456789", payload=None)
    adapter.handle_incoming(vk_user_id=2002, text="РРІР°РЅ", payload=None)

    first_try = adapter.handle_incoming(vk_user_id=2002, text="Р”Р°", payload=None)
    second_try = adapter.handle_incoming(vk_user_id=2002, text="", payload={"cmd": "retry_iiko_sync"})

    assert first_try.screen is not None
    assert first_try.screen.screen_id == "iiko_sync_retry"
    assert second_try.screen is not None
    assert second_try.screen.screen_id == "main_menu"
    assert second_try.virtual_card_numbers == ("79123456789_20260325",)


def test_vk_balance_uses_loyalty_use_case() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚, С‡С‚Рѕ РїСѓРЅРєС‚ В«РњРѕР№ Р±Р°Р»Р°РЅСЃВ» РІРѕР·РІСЂР°С‰Р°РµС‚ РґР°РЅРЅС‹Рµ РёР· loyalty use-case."""

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
    adapter = VkIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        balance_use_case=GetLoyaltyBalanceUseCase(loyalty_gateway),
    )
    _complete_vk_registration(adapter)

    response = adapter.handle_incoming(vk_user_id=1001, text="рџ’° РњРѕР№ Р±Р°Р»Р°РЅСЃ", payload=None)

    assert "44.50" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "balance"


def test_vk_virtual_card_uses_loyalty_use_case() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚, С‡С‚Рѕ РїСѓРЅРєС‚ В«Р’РёСЂС‚СѓР°Р»СЊРЅР°СЏ РєР°СЂС‚Р°В» РІРѕР·РІСЂР°С‰Р°РµС‚ РЅРѕРјРµСЂ РєР°СЂС‚С‹ РёР· loyalty use-case."""

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
    adapter = VkIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        virtual_card_use_case=GetVirtualCardUseCase(loyalty_gateway),
    )
    _complete_vk_registration(adapter)

    response = adapter.handle_incoming(vk_user_id=1001, text="рџЄЄ Р’РёСЂС‚СѓР°Р»СЊРЅР°СЏ РєР°СЂС‚Р°", payload=None)

    assert "РќР°Р·Р°Рґ РІ РјРµРЅСЋ" in response.text
    assert response.virtual_card_numbers == ("79123456789_20260325",)
    assert response.screen is not None
    assert response.screen.screen_id == "virtual_card_result"


def test_vk_invalid_phone_returns_validation_error() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚ РЅРµРіР°С‚РёРІРЅС‹Р№ СЃС†РµРЅР°СЂРёР№ РїСЂРё РЅРµРІР°Р»РёРґРЅРѕРј РЅРѕРјРµСЂРµ."""

    adapter = _build_adapter()
    adapter.handle_start(vk_user_id=1001)
    adapter.handle_incoming(vk_user_id=1001, text="вњ… РЎРѕРіР»Р°СЃРµРЅ", payload=None)

    response = adapter.handle_incoming(vk_user_id=1001, text="abc", payload=None)

    assert "РќРµ СѓРґР°Р»РѕСЃСЊ РѕР±СЂР°Р±РѕС‚Р°С‚СЊ РЅРѕРјРµСЂ С‚РµР»РµС„РѕРЅР°" in response.text


def test_vk_support_question_flow_returns_to_main_menu() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚, С‡С‚Рѕ РїСѓРЅРєС‚ В«РњРЅРµ С‚РѕР»СЊРєРѕ СЃРїСЂРѕСЃРёС‚СЊВ» РїРѕРјРµС‡РµРЅ РєР°Рє РЅРµРіРѕС‚РѕРІС‹Р№ РґР»СЏ РіРѕСЃС‚РµР№."""

    adapter = _build_adapter()
    _complete_vk_registration(adapter)

    result = adapter.handle_incoming(
        vk_user_id=1001,
        text="вќ“ РњРЅРµ С‚РѕР»СЊРєРѕ СЃРїСЂРѕСЃРёС‚СЊ (Р’ СЂР°Р·СЂР°Р±РѕС‚РєРµ)",
        payload=None,
    )

    assert "РІ СЂР°Р·СЂР°Р±РѕС‚РєРµ" in result.text.lower()
    assert result.screen is not None
    assert result.screen.screen_id == "support_menu"


def test_vk_support_question_flow_allows_back_to_support_by_callback() -> None:
    """РџРѕСЃР»Рµ РѕС‚РєСЂС‹С‚РёСЏ РЅРµРіРѕС‚РѕРІРѕРіРѕ РїСѓРЅРєС‚Р° callback В«РќР°Р·Р°Рґ РІ РѕС‚РґРµР» Р·Р°Р±РѕС‚С‹В» РѕСЃС‚Р°РІР»СЏРµС‚ РІ РјРµРЅСЋ Р·Р°Р±РѕС‚С‹."""

    adapter = _build_adapter(with_support=True)
    _complete_vk_registration(adapter)

    first = adapter.handle_incoming(
        vk_user_id=1001,
        text="вќ“ РњРЅРµ С‚РѕР»СЊРєРѕ СЃРїСЂРѕСЃРёС‚СЊ (Р’ СЂР°Р·СЂР°Р±РѕС‚РєРµ)",
        payload=None,
    )
    back = adapter.handle_incoming(vk_user_id=1001, text="", payload={"cmd": "back_to_support"})

    assert first.screen is not None
    assert first.screen.screen_id == "support_menu"
    assert back.screen is not None
    assert back.screen.screen_id == "support_menu"
    assert "РћС‚РґРµР» Р·Р°Р±РѕС‚С‹" in back.text


def test_vk_my_tickets_shows_created_tickets() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚ СЂР°Р·РґРµР» В«РњРѕРё РѕР±СЂР°С‰РµРЅРёСЏВ»: РїРѕСЃР»Рµ СЃРѕР·РґР°РЅРёСЏ С‚РёРєРµС‚Р° РІРѕР·РІСЂР°С‰Р°РµС‚СЃСЏ СЃРїРёСЃРѕРє."""

    adapter, _, create_ticket_use_case = _build_adapter_with_support_context()
    _complete_vk_registration(adapter)

    create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="vk",
            external_id="1001",
            question_text="РќСѓР¶РЅР° РїРѕРјРѕС‰СЊ",
        )
    )
    tickets_response = adapter.handle_incoming(vk_user_id=1001, text="рџ“‹ РњРѕРё РѕР±СЂР°С‰РµРЅРёСЏ", payload=None)

    assert "Р’Р°С€Рё РѕР±СЂР°С‰РµРЅРёСЏ" in tickets_response.text
    assert "РўРёРєРµС‚ #" in tickets_response.text


def test_vk_legacy_start_requests_phone_confirmation() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚ legacy-РІРµС‚РєСѓ СЃ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµРј С‚РµР»РµС„РѕРЅР° РґР»СЏ Р·Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°РЅРЅРѕРіРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ."""

    adapter = _build_adapter()
    _complete_vk_registration(adapter)

    legacy_start = adapter.handle_legacy_start(vk_user_id=1001)
    confirm = adapter.handle_incoming(vk_user_id=1001, text="+79123456789", payload=None)
    finish = adapter.handle_incoming(vk_user_id=1001, text="Р”Р°", payload=None)

    assert "РїСЂРµРґС‹РґСѓС‰РµР№ РІРµСЂСЃРёРё Р±РѕС‚Р°" in legacy_start.text
    assert legacy_start.screen is not None
    assert legacy_start.screen.screen_id == "start_contact"
    assert confirm.screen is not None
    assert confirm.screen.screen_id == "notifications_consent"
    assert "Р РµРіРёСЃС‚СЂР°С†РёСЏ СѓСЃРїРµС€РЅРѕ Р·Р°РІРµСЂС€РµРЅР°." in finish.text


def test_vk_moderator_reply_can_route_to_another_messenger() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚ РјРѕРґРµСЂР°С†РёСЋ: РѕС‚РІРµС‚ РёР· VK СЃ РґРѕСЃС‚Р°РІРєРѕР№ РІ РґСЂСѓРіРѕР№ РєР°РЅР°Р»."""

    adapter, register_use_case, create_ticket_use_case = _build_adapter_with_support_context()
    _complete_vk_registration(adapter, vk_user_id=1001)

    # Р”РѕР±Р°РІР»СЏРµРј РІС‚РѕСЂСѓСЋ РїСЂРёРІСЏР·РєСѓ С‚РѕРіРѕ Р¶Рµ Person С‡РµСЂРµР· Telegram РІ РґРѕРјРµРЅРЅРѕРј use-case.
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="tg-777",
            raw_phone="+79123456789",
        )
    )

    created_ticket = create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="vk",
            external_id="1001",
            question_text="РќСѓР¶РЅР° РїРѕРјРѕС‰СЊ",
        )
    )
    ticket_id = str(created_ticket.ticket_id)

    reply = adapter.handle_incoming(
        vk_user_id=9999,
        text=f"/modreply {ticket_id} --to=telegram РћС‚РІРµС‚ РѕС‚РїСЂР°РІР»РµРЅ.",
        payload=None,
    )
    details = adapter.handle_incoming(vk_user_id=9999, text=f"/modticket {ticket_id}", payload=None)

    assert "РњР°СЂС€СЂСѓС‚ РґРѕСЃС‚Р°РІРєРё: telegram" in reply.text
    assert "РљР°РЅР°Р» СЃРѕР·РґР°РЅРёСЏ: vk" in details.text


def test_vk_moderation_menu_fsm_supports_dirty_and_success_paths() -> None:
    """РџСЂРѕРІРµСЂСЏРµС‚ `/mod`-РјРµРЅСЋ: СЃРїРёСЃРѕРє С‚РёРєРµС‚РѕРІ, РіСЂСЏР·РЅС‹Р№ UUID Рё СѓСЃРїРµС€РЅС‹Р№ РѕС‚РІРµС‚."""

    adapter, _, create_ticket_use_case = _build_adapter_with_support_context()
    _complete_vk_registration(adapter, vk_user_id=1001)

    created_ticket = create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="vk",
            external_id="1001",
            question_text="РќСѓР¶РЅР° РїРѕРјРѕС‰СЊ",
        )
    )
    ticket_id = str(created_ticket.ticket_id)

    open_menu = adapter.handle_incoming(vk_user_id=9999, text="/mod", payload=None)
    open_tickets = adapter.handle_incoming(vk_user_id=9999, text="1", payload=None)
    wait_ticket = adapter.handle_incoming(vk_user_id=9999, text="2", payload=None)
    dirty_ticket = adapter.handle_incoming(vk_user_id=9999, text="РЅРµ-uuid", payload=None)
    wait_reply = adapter.handle_incoming(vk_user_id=9999, text=ticket_id, payload=None)
    routed = adapter.handle_incoming(vk_user_id=9999, text="РћС‚РІРµС‚ РїСЂРёРЅСЏС‚", payload=None)
    wait_details = adapter.handle_incoming(vk_user_id=9999, text="3", payload=None)
    details = adapter.handle_incoming(vk_user_id=9999, text=ticket_id, payload=None)

    assert "РњРµРЅСЋ РјРѕРґРµСЂР°С‚РѕСЂР°" in open_menu.text
    assert "РћС‚РєСЂС‹С‚С‹Рµ С‚РёРєРµС‚С‹:" in open_tickets.text
    assert "Р’РІРµРґРёС‚Рµ UUID С‚РёРєРµС‚Р°" in wait_ticket.text
    assert "РќРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ ticket_id" in dirty_ticket.text
    assert "Р’РІРµРґРёС‚Рµ С‚РµРєСЃС‚ РѕС‚РІРµС‚Р° РјРѕРґРµСЂР°С‚РѕСЂР°" in wait_reply.text
    assert "РњР°СЂС€СЂСѓС‚ РґРѕСЃС‚Р°РІРєРё: vk" in routed.text
    assert "Р’РІРµРґРёС‚Рµ UUID С‚РёРєРµС‚Р°, С‡С‚РѕР±С‹ РїРѕРєР°Р·Р°С‚СЊ РєР°СЂС‚РѕС‡РєСѓ РѕР±СЂР°С‰РµРЅРёСЏ." in wait_details.text
    assert "РљР°РЅР°Р» СЃРѕР·РґР°РЅРёСЏ: vk" in details.text

