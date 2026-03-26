"""Тесты MAX identity-адаптера."""

from __future__ import annotations

from types import TracebackType

from vtelemax.adapters.max import MaxIdentityAdapter
from vtelemax.core import (
    CreateSupportTicketTransactionalUseCase,
    GetLoyaltyBalanceUseCase,
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

    def register_customer(self, phone_e164: str) -> LoyaltyRegisterCustomerResult:
        return LoyaltyRegisterCustomerResult(customer_id="cust-1", message="registered")

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
    return MaxIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        moderator_reply_use_case=moderator_reply_use_case,
        ticket_details_use_case=ticket_details_use_case,
        list_open_tickets_use_case=list_open_tickets_use_case,
        list_person_tickets_use_case=list_person_tickets_use_case,
    )


def _build_adapter_with_support_context() -> tuple[
    MaxIdentityAdapter,
    RegisterOrAttachAccountTransactionalUseCase,
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
    adapter = MaxIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        moderator_reply_use_case=moderator_reply_use_case,
        ticket_details_use_case=ticket_details_use_case,
        list_open_tickets_use_case=list_open_tickets_use_case,
        list_person_tickets_use_case=list_person_tickets_use_case,
    )
    return adapter, registration_use_case


def _complete_max_registration(adapter: MaxIdentityAdapter, max_user_id: int = 1001) -> None:
    adapter.handle_start(max_user_id=max_user_id)
    adapter.handle_incoming(max_user_id=max_user_id, text="✅ Согласен", payload=None)
    adapter.handle_incoming(max_user_id=max_user_id, text="+79123456789", payload=None)


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


def test_max_dirty_input_on_rules_step_keeps_consent_pending() -> None:
    """Проверяет грязный сценарий: случайный текст вместо согласия."""

    adapter = _build_adapter()
    adapter.handle_start(max_user_id=1001)

    response = adapter.handle_incoming(max_user_id=1001, text="хочу бонусы", payload=None)

    assert "Чтобы продолжить регистрацию" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "start_rules"


def test_max_registration_by_phone_after_rules_consent() -> None:
    """Проверяет успешную регистрацию после согласия и ввода номера."""

    adapter = _build_adapter()
    adapter.handle_start(max_user_id=1001)
    adapter.handle_incoming(max_user_id=1001, text="✅ Согласен", payload=None)

    response = adapter.handle_incoming(max_user_id=1001, text="+7 (912) 345-67-89", payload=None)

    assert "Регистрация успешно подтверждена" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "main_menu"


def test_max_profile_available_after_registration() -> None:
    """Проверяет получение профиля после регистрации."""

    adapter = _build_adapter()
    _complete_max_registration(adapter)

    response = adapter.handle_incoming(max_user_id=1001, text="👤 Профиль", payload=None)

    assert "Ваш профиль" in response.text
    assert "+79123456789" in response.text


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

    response = adapter.handle_incoming(max_user_id=1001, text="🪪 Виртуальная карта", payload=None)

    assert "79123456789_20260325" in response.text


def test_max_invalid_phone_returns_validation_error() -> None:
    """Проверяет негативный сценарий при невалидном номере."""

    adapter = _build_adapter()
    adapter.handle_start(max_user_id=1001)
    adapter.handle_incoming(max_user_id=1001, text="✅ Согласен", payload=None)

    response = adapter.handle_incoming(max_user_id=1001, text="abc", payload=None)

    assert "Не удалось обработать номер телефона" in response.text


def test_max_support_question_flow_returns_to_main_menu() -> None:
    """Проверяет сценарий вопроса в поддержку с возвратом в меню."""

    adapter = _build_adapter()
    _complete_max_registration(adapter)

    first = adapter.handle_incoming(max_user_id=1001, text="❓ Мне только спросить", payload=None)
    second = adapter.handle_incoming(
        max_user_id=1001,
        text="Когда начисляются бонусы?",
        payload=None,
    )

    assert "Введите ваш вопрос" in first.text
    assert "Ваш вопрос принят" in second.text
    assert second.screen is not None
    assert second.screen.screen_id == "main_menu"


def test_max_my_tickets_shows_created_tickets() -> None:
    """Проверяет раздел «Мои обращения»: после создания тикета возвращается список."""

    adapter = _build_adapter(with_support=True)
    _complete_max_registration(adapter)

    adapter.handle_incoming(max_user_id=1001, text="❓ Мне только спросить", payload=None)
    adapter.handle_incoming(max_user_id=1001, text="Нужна помощь", payload=None)
    tickets_response = adapter.handle_incoming(max_user_id=1001, text="📋 Мои обращения", payload=None)

    assert "Ваши обращения" in tickets_response.text
    assert "Тикет #" in tickets_response.text


def test_max_legacy_start_requests_phone_confirmation() -> None:
    """Проверяет legacy-ветку с подтверждением телефона для зарегистрированного пользователя."""

    adapter = _build_adapter()
    _complete_max_registration(adapter)

    legacy_start = adapter.handle_legacy_start(max_user_id=1001)
    confirm = adapter.handle_incoming(max_user_id=1001, text="+79123456789", payload=None)

    assert "предыдущей версии бота" in legacy_start.text
    assert legacy_start.screen is not None
    assert legacy_start.screen.screen_id == "start_contact"
    assert "legacy успешно обновлен" in confirm.text


def test_max_moderator_reply_can_route_to_another_messenger() -> None:
    """Проверяет модерацию: ответ из MAX с доставкой в другой канал."""

    adapter, register_use_case = _build_adapter_with_support_context()
    _complete_max_registration(adapter, max_user_id=1001)

    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="vk-777",
            raw_phone="+79123456789",
        )
    )

    adapter.handle_incoming(max_user_id=1001, text="❓ Мне только спросить", payload=None)
    ticket_response = adapter.handle_incoming(max_user_id=1001, text="Нужна помощь", payload=None)
    ticket_id = ticket_response.text.split("#")[1].split("\n")[0].strip()

    reply = adapter.handle_incoming(
        max_user_id=9999,
        text=f"/modreply {ticket_id} --to=vk Ответ отправлен.",
        payload=None,
    )
    details = adapter.handle_incoming(max_user_id=9999, text=f"/modticket {ticket_id}", payload=None)

    assert "Маршрут доставки: vk" in reply.text
    assert "Канал создания: max" in details.text


def test_max_moderation_menu_fsm_supports_dirty_and_success_paths() -> None:
    """Проверяет `/mod`-меню: список тикетов, грязный UUID и успешный ответ."""

    adapter, _ = _build_adapter_with_support_context()
    _complete_max_registration(adapter, max_user_id=1001)

    adapter.handle_incoming(max_user_id=1001, text="❓ Мне только спросить", payload=None)
    ticket_response = adapter.handle_incoming(max_user_id=1001, text="Нужна помощь", payload=None)
    ticket_id = ticket_response.text.split("#")[1].split("\n")[0].strip()

    open_menu = adapter.handle_incoming(max_user_id=9999, text="/mod", payload=None)
    open_tickets = adapter.handle_incoming(max_user_id=9999, text="1", payload=None)
    wait_ticket = adapter.handle_incoming(max_user_id=9999, text="2", payload=None)
    dirty_ticket = adapter.handle_incoming(max_user_id=9999, text="не-uuid", payload=None)
    wait_reply = adapter.handle_incoming(max_user_id=9999, text=ticket_id, payload=None)
    routed = adapter.handle_incoming(max_user_id=9999, text="Ответ принят", payload=None)
    wait_details = adapter.handle_incoming(max_user_id=9999, text="3", payload=None)
    details = adapter.handle_incoming(max_user_id=9999, text=ticket_id, payload=None)

    assert "Меню модератора" in open_menu.text
    assert "Открытые тикеты:" in open_tickets.text
    assert "Введите UUID тикета" in wait_ticket.text
    assert "Некорректный ticket_id" in dirty_ticket.text
    assert "Введите текст ответа модератора" in wait_reply.text
    assert "Маршрут доставки: max" in routed.text
    assert "Введите UUID тикета, чтобы показать карточку обращения." in wait_details.text
    assert "Канал создания: max" in details.text
