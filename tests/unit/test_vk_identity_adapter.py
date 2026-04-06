"""Тесты VK identity-адаптера."""

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
    adapter.handle_incoming(vk_user_id=vk_user_id, text="✅ Согласен", payload=None)
    adapter.handle_incoming(vk_user_id=vk_user_id, text="+79123456789", payload=None)
    adapter.handle_incoming(vk_user_id=vk_user_id, text="Иван", payload=None)
    adapter.handle_incoming(vk_user_id=vk_user_id, text="Да", payload=None)


def test_vk_start_for_unregistered_user_requests_rules_consent() -> None:
    """Проверяет, что `/start` для нового пользователя запрашивает согласие."""

    adapter = _build_adapter()

    response = adapter.handle_start(vk_user_id=1001)

    assert "Согласен" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "start_rules"


def test_vk_onboarding_moves_from_rules_to_phone() -> None:
    """Проверяет переход onboarding из правил к шагу телефона."""

    adapter = _build_adapter()
    adapter.handle_start(vk_user_id=1001)

    response = adapter.handle_incoming(vk_user_id=1001, text="✅ Согласен", payload=None)

    assert "+79991234567" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "start_contact"


def test_vk_migrated_legacy_user_goes_to_legacy_phone_after_rules_consent() -> None:
    """Проверяет, что migrated legacy-пользователь после новых правил переходит в legacy-шаг телефона."""

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
    response = adapter.handle_incoming(vk_user_id=3005, text="✅ Согласен", payload=None)

    assert start_response.screen is not None
    assert start_response.screen.screen_id == "start_rules"
    assert "предыдущей версии бота" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "start_contact"


def test_vk_legacy_phone_step_prefills_profile_from_iiko() -> None:
    """Проверяет, что legacy-ветка после подтверждения телефона подтягивает пустые поля из iiko."""

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
    adapter.handle_incoming(vk_user_id=3010, text="✅ Согласен", payload=None)
    phone_result = adapter.handle_incoming(vk_user_id=3010, text="+79123456789", payload=None)

    resolved_person = lookup_use_case.execute(
        command=GetPersonByAccountCommand(platform="vk", external_id="3010")
    )

    assert phone_result.screen is not None
    assert phone_result.screen.screen_id == "notifications_consent"
    assert resolved_person is not None
    assert resolved_person.first_name_input == "Андрей"
    assert resolved_person.last_name_input == "Соболев"
    assert resolved_person.gender == "male"
    assert resolved_person.birth_date == date(1990, 5, 17)
    assert resolved_person.email == "legacy@example.com"


def test_vk_phone_match_with_telegram_legacy_switches_to_legacy_flow() -> None:
    """Проверяет авто-переход в legacy-ветку в VK, если телефон найден у legacy-профиля Telegram."""

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
            first_name_input="Андрей",
            rules_accepted=False,
            is_legacy=True,
            is_registered=False,
        )
    )

    adapter.handle_start(vk_user_id=4501)
    adapter.handle_incoming(vk_user_id=4501, text="✅ Согласен", payload=None)
    response = adapter.handle_incoming(vk_user_id=4501, text="+79121112233", payload=None)

    assert response.screen is not None
    assert response.screen.screen_id == "notifications_consent"


def test_vk_phone_match_with_registered_profile_opens_menu_without_reasking_name() -> None:
    """Проверяет, что при привязке к уже зарегистрированному профилю VK запрашивает согласие на рассылку."""

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
            first_name_input="Андрей",
            rules_accepted=True,
            notifications_allowed=True,
            is_legacy=False,
            is_registered=True,
        )
    )

    adapter.handle_start(vk_user_id=4601)
    adapter.handle_incoming(vk_user_id=4601, text="✅ Согласен", payload=None)
    response = adapter.handle_incoming(vk_user_id=4601, text="+79124445566", payload=None)

    attached_person = lookup_use_case.execute(
        command=GetPersonByAccountCommand(platform="vk", external_id="4601")
    )

    assert response.screen is not None
    assert response.screen.screen_id == "notifications_consent"
    assert attached_person is not None
    assert attached_person.first_name_input == "Андрей"
    assert len(attached_person.accounts) == 2


def test_vk_start_for_registered_profile_without_vk_consents_continues_onboarding() -> None:
    """Проверяет, что `/start` в VK не пропускает обязательные платформенные согласия."""

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
            first_name_input="Андрей",
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
    assert "Согласен" in start_response.text


def test_vk_dirty_input_on_rules_step_keeps_consent_pending() -> None:
    """Проверяет грязный сценарий: случайный текст вместо согласия."""

    adapter = _build_adapter()
    adapter.handle_start(vk_user_id=1001)

    response = adapter.handle_incoming(vk_user_id=1001, text="хочу бонусы", payload=None)

    assert "Чтобы продолжить регистрацию" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "start_rules"


def test_vk_registration_by_phone_after_rules_consent() -> None:
    """Проверяет переход к шагу ввода имени после согласия и ввода номера."""

    adapter = _build_adapter()
    adapter.handle_start(vk_user_id=1001)
    adapter.handle_incoming(vk_user_id=1001, text="✅ Согласен", payload=None)

    response = adapter.handle_incoming(vk_user_id=1001, text="+7 (912) 345-67-89", payload=None)

    assert "имя" in response.text.lower()
    assert response.screen is None


def test_vk_profile_available_after_registration() -> None:
    """Проверяет получение профиля после регистрации."""

    adapter = _build_adapter()
    _complete_vk_registration(adapter)

    response = adapter.handle_incoming(vk_user_id=1001, text="👤 Профиль", payload=None)

    assert "Профиль пользователя" in response.text
    assert "+79123456789" in response.text


def test_vk_start_for_registered_user_uses_first_name_in_menu() -> None:
    """Проверяет, что главное меню для зарегистрированного пользователя показывает имя."""

    adapter = _build_adapter()
    _complete_vk_registration(adapter)

    response = adapter.handle_start(vk_user_id=1001)

    assert "Иван" in response.text
    assert "главном меню" in response.text


def test_vk_onboarding_iiko_failure_moves_to_retry_step() -> None:
    """Проверяет отдельный шаг retry, если синхронизация с iiko не удалась."""

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
    adapter.handle_incoming(vk_user_id=2001, text="✅ Согласен", payload=None)
    adapter.handle_incoming(vk_user_id=2001, text="+79123456789", payload=None)
    adapter.handle_incoming(vk_user_id=2001, text="Иван", payload=None)
    failure_result = adapter.handle_incoming(vk_user_id=2001, text="Да", payload=None)

    assert failure_result.screen is not None
    assert failure_result.screen.screen_id == "iiko_sync_retry"
    assert "синхронизац" in failure_result.text.lower()

    pending_result = adapter.handle_incoming(vk_user_id=2001, text="/menu", payload=None)
    assert pending_result.screen is not None
    assert pending_result.screen.screen_id == "iiko_sync_retry"
    assert "Повторить синхронизацию" in pending_result.text


def test_vk_onboarding_iiko_retry_eventually_returns_menu() -> None:
    """Проверяет успешный выход в меню после повторной синхронизации iiko."""

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
    adapter.handle_incoming(vk_user_id=2002, text="✅ Согласен", payload=None)
    adapter.handle_incoming(vk_user_id=2002, text="+79123456789", payload=None)
    adapter.handle_incoming(vk_user_id=2002, text="Иван", payload=None)

    first_try = adapter.handle_incoming(vk_user_id=2002, text="Да", payload=None)
    second_try = adapter.handle_incoming(vk_user_id=2002, text="", payload={"cmd": "retry_iiko_sync"})

    assert first_try.screen is not None
    assert first_try.screen.screen_id == "iiko_sync_retry"
    assert second_try.screen is not None
    assert second_try.screen.screen_id == "main_menu"
    assert second_try.virtual_card_numbers == ("79123456789_20260325",)


def test_vk_balance_uses_loyalty_use_case() -> None:
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
    adapter = VkIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        balance_use_case=GetLoyaltyBalanceUseCase(loyalty_gateway),
    )
    _complete_vk_registration(adapter)

    response = adapter.handle_incoming(vk_user_id=1001, text="💰 Мой баланс", payload=None)

    assert "44.50" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "balance"


def test_vk_virtual_card_uses_loyalty_use_case() -> None:
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
    adapter = VkIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        virtual_card_use_case=GetVirtualCardUseCase(loyalty_gateway),
    )
    _complete_vk_registration(adapter)

    response = adapter.handle_incoming(vk_user_id=1001, text="🪪 Виртуальная карта", payload=None)

    assert "Назад в меню" in response.text
    assert response.virtual_card_numbers == ("79123456789_20260325",)
    assert response.screen is not None
    assert response.screen.screen_id == "virtual_card_result"


def test_vk_invalid_phone_returns_validation_error() -> None:
    """Проверяет негативный сценарий при невалидном номере."""

    adapter = _build_adapter()
    adapter.handle_start(vk_user_id=1001)
    adapter.handle_incoming(vk_user_id=1001, text="✅ Согласен", payload=None)

    response = adapter.handle_incoming(vk_user_id=1001, text="abc", payload=None)

    assert "Не удалось обработать номер телефона" in response.text


def test_vk_support_question_activates_question_input_when_no_tickets() -> None:
    """Проверяет, что пункт «Мне только спросить» активирует ввод вопроса, если нет тикетов."""

    adapter = _build_adapter()
    _complete_vk_registration(adapter)

    result = adapter.handle_incoming(
        vk_user_id=1001,
        text="❓ Мне только спросить",
        payload=None,
    )

    assert "введите ваш вопрос" in result.text.lower()
    assert result.screen is not None
    assert result.screen.screen_id == "support_question"


def test_vk_my_tickets_shows_created_tickets() -> None:
    """Проверяет раздел «Мои обращения»: после создания тикета возвращается список."""

    adapter, _, create_ticket_use_case = _build_adapter_with_support_context()
    _complete_vk_registration(adapter)

    create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="vk",
            external_id="1001",
            question_text="Нужна помощь",
        )
    )
    tickets_response = adapter.handle_incoming(vk_user_id=1001, text="📋 Мои обращения", payload=None)

    assert "Ваши обращения" in tickets_response.text
    assert "#" in tickets_response.text  # Короткий идентификатор тикета


def test_vk_legacy_start_requests_phone_confirmation() -> None:
    """Проверяет legacy-ветку с подтверждением телефона для зарегистрированного пользователя."""

    adapter = _build_adapter()
    _complete_vk_registration(adapter)

    legacy_start = adapter.handle_legacy_start(vk_user_id=1001)
    confirm = adapter.handle_incoming(vk_user_id=1001, text="+79123456789", payload=None)
    finish = adapter.handle_incoming(vk_user_id=1001, text="Да", payload=None)

    assert "предыдущей версии бота" in legacy_start.text
    assert legacy_start.screen is not None
    assert legacy_start.screen.screen_id == "start_contact"
    assert confirm.screen is not None
    assert confirm.screen.screen_id == "notifications_consent"
    assert "Регистрация успешно завершена." in finish.text


def test_vk_moderator_reply_can_route_to_another_messenger() -> None:
    """Проверяет модерацию: ответ из VK с доставкой в другой канал."""

    adapter, register_use_case, create_ticket_use_case = _build_adapter_with_support_context()
    _complete_vk_registration(adapter, vk_user_id=1001)

    # Добавляем вторую привязку того же Person через Telegram в доменном use-case.
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
            question_text="Нужна помощь",
        )
    )
    ticket_id = str(created_ticket.ticket_id)

    reply = adapter.handle_incoming(
        vk_user_id=9999,
        text=f"/modreply {ticket_id} --to=telegram Ответ отправлен.",
        payload=None,
    )
    details = adapter.handle_incoming(vk_user_id=9999, text=f"/modticket {ticket_id}", payload=None)

    assert "Маршрут доставки: telegram" in reply.text
    assert "Канал создания: vk" in details.text


def test_vk_moderation_menu_fsm_supports_dirty_and_success_paths() -> None:
    """Проверяет `/mod`-меню: список тикетов, грязный UUID и успешный ответ."""

    adapter, _, create_ticket_use_case = _build_adapter_with_support_context()
    _complete_vk_registration(adapter, vk_user_id=1001)

    created_ticket = create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="vk",
            external_id="1001",
            question_text="Нужна помощь",
        )
    )
    ticket_id = str(created_ticket.ticket_id)

    open_menu = adapter.handle_incoming(vk_user_id=9999, text="/mod", payload=None)
    open_tickets = adapter.handle_incoming(vk_user_id=9999, text="1", payload=None)
    wait_ticket = adapter.handle_incoming(vk_user_id=9999, text="2", payload=None)
    dirty_ticket = adapter.handle_incoming(vk_user_id=9999, text="не-uuid", payload=None)
    wait_reply = adapter.handle_incoming(vk_user_id=9999, text=ticket_id, payload=None)
    routed = adapter.handle_incoming(vk_user_id=9999, text="Ответ принят", payload=None)
    wait_details = adapter.handle_incoming(vk_user_id=9999, text="3", payload=None)
    details = adapter.handle_incoming(vk_user_id=9999, text=ticket_id, payload=None)

    assert "Меню модератора" in open_menu.text
    assert "Открытые тикеты:" in open_tickets.text
    assert "Введите UUID тикета" in wait_ticket.text
    assert "Некорректный ticket_id" in dirty_ticket.text
    assert "Введите текст ответа модератора" in wait_reply.text
    assert "Маршрут доставки: vk" in routed.text
    assert "Введите UUID тикета, чтобы показать карточку обращения." in wait_details.text
    assert "Канал создания: vk" in details.text

