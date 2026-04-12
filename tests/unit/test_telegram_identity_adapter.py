"""Тесты Telegram-адаптера строгой идентификации."""

from __future__ import annotations

from datetime import date
from types import TracebackType

from vtelemax.adapters.telegram import TelegramIdentityAdapter
from vtelemax.adapters.telegram.identity_adapter import TelegramRegistrationResult
from vtelemax.core import (
    CreateSupportTicketCommand,
    CreateSupportTicketTransactionalUseCase,
    GuestMenuAction,
    GetLoyaltyBalanceUseCase,
    GetPersonByAccountCommand,
    GetPersonByAccountTransactionalUseCase,
    GetPersonTicketsPageTransactionalUseCase,
    GetSupportTicketConversationTransactionalUseCase,
    GetSupportTicketDetailsTransactionalUseCase,
    GetVirtualCardUseCase,
    IdentityRepository,
    IdentityUnitOfWork,
    InMemoryIdentityRepository,
    InMemorySupportRepository,
    ListOpenSupportTicketsTransactionalUseCase,
    ListPersonSupportTicketsTransactionalUseCase,
    LoyaltyCard,
    LoyaltyCustomer,
    LoyaltyGateway,
    LoyaltyGatewayError,
    LoyaltyIssueCardResult,
    LoyaltyRegisterCustomerResult,
    PersonTicketsPageResult,
    PersonProfilePatch,
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


def test_telegram_adapter_registers_contact_successfully() -> None:
    """Проверяет успешную регистрацию Telegram-контакта."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    result = adapter.register_contact(telegram_user_id=1001, raw_phone="+7 (912) 345-67-89")

    assert result.is_success is True
    assert result.status == "success"
    assert result.person_id is not None


def test_telegram_registration_result_is_router_compatible() -> None:
    """Проверяет наличие полей, которые ожидает Telegram-роутер."""

    result = TelegramRegistrationResult(
        is_success=False,
        status="first_name_required",
        message="Введите имя",
    )

    assert result.parse_mode is None
    assert result.virtual_card_numbers == ()


def test_telegram_adapter_is_idempotent_for_repeated_registration() -> None:
    """Проверяет, что повторная регистрация того же аккаунта не создает дубликатов."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    first = adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    second = adapter.register_contact(telegram_user_id=1001, raw_phone="8 (912) 345-67-89")

    assert first.is_success is True
    assert second.is_success is True
    assert first.person_id == second.person_id


def test_telegram_adapter_returns_validation_error_for_bad_phone() -> None:
    """Проверяет ответ адаптера при невалидном формате телефона."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    result = adapter.register_contact(telegram_user_id=1001, raw_phone="abc")

    assert result.is_success is False
    assert result.status == "validation_error"


def test_telegram_adapter_returns_conflict_when_rebind_attempted() -> None:
    """Проверяет конфликт при попытке перепривязать тот же аккаунт к другому номеру."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    result = adapter.register_contact(telegram_user_id=1001, raw_phone="+79991234567")

    assert result.is_success is False
    assert result.status == "conflict"


def test_telegram_adapter_returns_profile_for_registered_user() -> None:
    """Проверяет меню-пункт профиля для зарегистрированного пользователя."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    result = adapter.handle_menu_action(telegram_user_id=1001, action_text="👤 Профиль")

    assert result.status == "profile"
    assert "+79123456789" in result.message


def test_telegram_adapter_returns_not_registered_for_missing_profile() -> None:
    """Проверяет меню-пункт профиля для незарегистрированного пользователя."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    result = adapter.handle_menu_action(telegram_user_id=2002, action_text="👤 Профиль")

    assert result.status == "not_registered"
    assert result.requires_contact_keyboard is True


def test_telegram_adapter_returns_help_for_help_action() -> None:
    """Проверяет ответ меню по кнопке помощи."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    result = adapter.handle_menu_action(telegram_user_id=1001, action_text="Помощь")

    assert result.status == "help"


def test_telegram_adapter_returns_balance_from_loyalty_use_case() -> None:
    """Проверяет, что пункт «Мой баланс» использует подключённый loyalty use-case."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    loyalty_gateway = StubLoyaltyGateway(
        customer=LoyaltyCustomer(customer_id="cust-1", balance=77.25, cards=())
    )
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        balance_use_case=GetLoyaltyBalanceUseCase(loyalty_gateway),
    )

    adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    result = adapter.handle_menu_action(telegram_user_id=1001, action_text="💰 Мой баланс")

    assert result.status == "balance"
    assert "77.25" in result.message
    assert result.parse_mode == "Markdown"


def test_telegram_adapter_returns_virtual_card_from_loyalty_use_case() -> None:
    """Проверяет, что пункт «Виртуальная карта» использует подключённый loyalty use-case."""

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
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        virtual_card_use_case=GetVirtualCardUseCase(loyalty_gateway),
    )

    adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    result = adapter.handle_menu_action(telegram_user_id=1001, action_text="🪪 Карта")

    assert result.status == "virtual_card"
    assert "Назад в меню" in result.message
    assert result.parse_mode is None
    assert result.virtual_card_numbers == ("79123456789_20260325",)


def test_telegram_adapter_returns_unknown_for_unexpected_action() -> None:
    """Проверяет корректный ответ на неизвестную команду."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    result = adapter.handle_menu_action(telegram_user_id=1001, action_text="какая-то команда")

    assert result.status == "unknown_action"


def test_telegram_adapter_returns_support_screen_for_support_action() -> None:
    """Проверяет переход в экран поддержки по кнопке меню."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    result = adapter.handle_menu_action(telegram_user_id=1001, action_text="🆘 Отдел заботы")

    assert result.status == "support"
    assert "Отдел заботы" in result.message
    assert result.has_support_tickets is False


def test_telegram_support_screen_marks_has_tickets_when_user_has_ticket() -> None:
    """Проверяет, что флаг has_support_tickets=true, если у пользователя уже есть тикет."""

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
    list_person_tickets_use_case = ListPersonSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        list_person_tickets_use_case=list_person_tickets_use_case,
    )

    adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="telegram",
            external_id="1001",
            question_text="Проверка тикета для меню поддержки",
        )
    )

    result = adapter.handle_menu_action(telegram_user_id=1001, action_text="🆘 Отдел заботы")

    assert result.status == "support"
    assert result.has_support_tickets is True


def test_telegram_adapter_returns_vacancies_screen_for_vacancies_action() -> None:
    """Проверяет экран вакансий по кнопке главного меню."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    result = adapter.handle_menu_action(telegram_user_id=1001, action_text="💼 Вакансии")

    assert result.status == "vacancies"
    assert "team.sobolevalliance.su/vacancy" in result.message


def test_telegram_expects_contact_input_only_on_phone_steps() -> None:
    """Проверяет, что контакт ожидается только на шагах WAITING_PHONE/WAITING_LEGACY_PHONE."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    assert adapter.expects_contact_input(telegram_user_id=1001) is False

    start_result = adapter.start_interaction(telegram_user_id=1001)
    assert start_result.status == "rules_consent_required"
    assert adapter.expects_contact_input(telegram_user_id=1001) is False

    phone_step_result = adapter.handle_menu_action(
        telegram_user_id=1001,
        action_text="✅ Согласен",
    )
    assert phone_step_result.status == "phone_required"
    assert adapter.expects_contact_input(telegram_user_id=1001) is True


def test_telegram_start_interaction_for_new_user_requires_rules_consent() -> None:
    """Проверяет старт onboarding для нового пользователя через шаг согласия."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    result = adapter.start_interaction(telegram_user_id=3003)

    assert result.status == "rules_consent_required"
    assert "Согласен" in result.message


def test_telegram_onboarding_moves_from_rules_to_phone() -> None:
    """Проверяет переход onboarding из шага правил в шаг отправки телефона."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    adapter.start_interaction(telegram_user_id=3003)
    result = adapter.handle_menu_action(telegram_user_id=3003, action_text="✅ Согласен")

    assert result.status == "phone_required"
    assert result.requires_contact_keyboard is True


def test_telegram_migrated_legacy_user_goes_to_legacy_phone_after_rules_consent() -> None:
    """Проверяет, что migrated legacy-пользователь после новых правил идет в legacy-подтверждение телефона."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="3005",
            raw_phone="+79123456789",
            rules_accepted=False,
            is_legacy=True,
            is_registered=False,
        )
    )

    start_result = adapter.start_interaction(telegram_user_id=3005)
    accept_result = adapter.handle_menu_action(telegram_user_id=3005, action_text="✅ Согласен")

    assert start_result.status == "rules_consent_required"
    assert accept_result.status == "legacy_phone_confirmation_required"
    assert accept_result.requires_contact_keyboard is True
    assert "предыдущей версии бота" in accept_result.message


def test_telegram_onboarding_phone_waiting_returns_reminder_for_dirty_input() -> None:
    """Проверяет грязный сценарий: текст вместо отправки контакта на шаге телефона."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    adapter.start_interaction(telegram_user_id=3003)
    adapter.handle_menu_action(telegram_user_id=3003, action_text="✅ Согласен")
    result = adapter.handle_menu_action(telegram_user_id=3003, action_text="хочу меню")

    assert result.status == "phone_required"
    assert result.requires_contact_keyboard is True


def test_telegram_start_interaction_for_registered_user_returns_menu() -> None:
    """Проверяет `/start` для уже зарегистрированного пользователя."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    adapter.start_interaction(telegram_user_id=1001)
    adapter.handle_menu_action(telegram_user_id=1001, action_text="✅ Согласен")
    contact_result = adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    assert contact_result.status == "first_name_required"

    name_result = adapter.handle_menu_action(telegram_user_id=1001, action_text="Иван")
    assert name_result.status == "notifications_consent_required"
    finish_result = adapter.handle_menu_action(telegram_user_id=1001, action_text="Да")
    assert finish_result.status == "menu"

    result = adapter.start_interaction(telegram_user_id=1001)

    assert result.status == "menu"
    assert "главном меню" in result.message
    assert "Иван" in result.message


def test_telegram_attach_to_registered_profile_skips_reentering_name() -> None:
    """Проверяет, что при привязке к зарегистрированному профилю Telegram не спрашивает имя повторно.

    Для новой платформы обязателен сбор платформенных согласий, поэтому после контакта
    ожидаем переход на шаг согласия уведомлений, а не мгновенное открытие меню.
    """

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="ready-vk-1",
            raw_phone="+79126667788",
            first_name_input="Пётр",
            rules_accepted=True,
            notifications_allowed=True,
            is_legacy=False,
            is_registered=True,
        )
    )

    adapter.start_interaction(telegram_user_id=4701)
    adapter.handle_menu_action(telegram_user_id=4701, action_text="✅ Согласен")
    result = adapter.register_contact(telegram_user_id=4701, raw_phone="+79126667788")

    attached_person = lookup_use_case.execute(
        command=GetPersonByAccountCommand(platform="telegram", external_id="4701")
    )

    assert result.is_success is False
    assert result.status == "notifications_consent_required"
    assert attached_person is not None
    assert attached_person.first_name_input == "Пётр"
    assert len(attached_person.accounts) == 2


def test_telegram_onboarding_iiko_failure_moves_to_retry_step() -> None:
    """Проверяет отдельный шаг retry, если синхронизация с iiko не удалась."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        virtual_card_use_case=GetVirtualCardUseCase(AlwaysFailLoyaltyGateway()),
    )

    adapter.start_interaction(telegram_user_id=3003)
    adapter.handle_menu_action(telegram_user_id=3003, action_text="✅ Согласен")
    adapter.register_contact(telegram_user_id=3003, raw_phone="+79123456789")
    adapter.handle_menu_action(telegram_user_id=3003, action_text="Иван")
    failure_result = adapter.handle_menu_action(telegram_user_id=3003, action_text="Да")

    assert failure_result.status == "iiko_sync_retry"
    assert "синхронизац" in failure_result.message.lower()

    pending_result = adapter.handle_menu_action(telegram_user_id=3003, action_text="Главное меню")
    assert pending_result.status == "iiko_sync_retry_pending"
    assert "Повторить синхронизацию" in pending_result.message


def test_telegram_onboarding_iiko_retry_eventually_returns_menu() -> None:
    """Проверяет успешный выход в меню после повторной синхронизации iiko."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        virtual_card_use_case=GetVirtualCardUseCase(FlakyLoyaltyGateway()),
    )

    adapter.start_interaction(telegram_user_id=3004)
    adapter.handle_menu_action(telegram_user_id=3004, action_text="✅ Согласен")
    adapter.register_contact(telegram_user_id=3004, raw_phone="+79123456789")
    adapter.handle_menu_action(telegram_user_id=3004, action_text="Иван")

    first_try = adapter.handle_menu_action(telegram_user_id=3004, action_text="Да")
    second_try = adapter.handle_menu_action(
        telegram_user_id=3004,
        action_text="🔄 Повторить синхронизацию",
    )

    assert first_try.status == "iiko_sync_retry"
    assert second_try.status == "menu"
    assert second_try.virtual_card_numbers == ("79123456789_20260325",)


def test_telegram_legacy_upgrade_flow_reuses_phone_confirmation() -> None:
    """Проверяет legacy-ветку с подтверждением телефона через общий onboarding-flow."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    adapter.start_interaction(telegram_user_id=1001)
    adapter.handle_menu_action(telegram_user_id=1001, action_text="✅ Согласен")
    adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    adapter.handle_menu_action(telegram_user_id=1001, action_text="Иван")
    adapter.handle_menu_action(telegram_user_id=1001, action_text="Да")

    legacy_start = adapter.start_interaction(telegram_user_id=1001, force_legacy_upgrade=True)
    confirm = adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    finish = adapter.handle_menu_action(telegram_user_id=1001, action_text="Да")

    assert legacy_start.status == "legacy_phone_confirmation_required"
    assert legacy_start.requires_contact_keyboard is True
    assert confirm.is_success is False
    assert confirm.status == "notifications_consent_required"
    assert finish.status == "menu"
    assert "Регистрация успешно завершена." in finish.message


def test_telegram_legacy_phone_step_prefills_profile_from_iiko() -> None:
    """Проверяет, что legacy-ветка после подтверждения телефона подтягивает пустые поля из iiko."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        loyalty_gateway=LegacyPrefillLoyaltyGateway(),
    )

    registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="3010",
            raw_phone="+79123456789",
            rules_accepted=False,
            is_legacy=True,
            is_registered=False,
        )
    )

    adapter.start_interaction(telegram_user_id=3010)
    adapter.handle_menu_action(telegram_user_id=3010, action_text="✅ Согласен")
    contact_result = adapter.register_contact(telegram_user_id=3010, raw_phone="+79123456789")
    resolved_person = lookup_use_case.execute(
        command=GetPersonByAccountCommand(platform="telegram", external_id="3010")
    )

    assert contact_result.status == "notifications_consent_required"
    assert resolved_person is not None
    assert resolved_person.first_name_input == "Андрей"
    assert resolved_person.last_name_input == "Соболев"
    assert resolved_person.gender == "male"
    assert resolved_person.birth_date == date(1990, 5, 17)
    assert resolved_person.email == "legacy@example.com"


def test_telegram_support_question_activates_question_input_when_no_tickets() -> None:
    """Проверяет, что пункт «Мне только спросить» активирует ввод вопроса, если тикетов нет."""

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
    get_person_tickets_page_use_case = GetPersonTicketsPageTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        get_person_tickets_page_use_case=get_person_tickets_page_use_case,
    )

    adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    result = adapter.handle_menu_action(
        telegram_user_id=1001,
        action_text="❓ Мне только спросить (В разработке)",
    )

    assert result.status == "support_question_input"
    assert "в разработке" not in result.message.lower()
    assert "введите ваш вопрос" in result.message.lower() or "задайте вопрос" in result.message.lower()


def test_telegram_support_back_does_not_create_ticket_while_waiting_question() -> None:
    """Проверяет, что callback `back_to_support` не превращается в текст тикета."""

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
    list_person_tickets_use_case = ListPersonSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    get_person_tickets_page_use_case = GetPersonTicketsPageTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        list_person_tickets_use_case=list_person_tickets_use_case,
        get_person_tickets_page_use_case=get_person_tickets_page_use_case,
    )

    adapter.register_contact(telegram_user_id=1002, raw_phone="+79125550102")
    adapter.handle_menu_action(
        telegram_user_id=1002,
        action_text="❓ Мне только спросить (В разработке)",
    )
    back_result = adapter.handle_menu_action(
        telegram_user_id=1002,
        action_text="back_to_support",
    )
    tickets = list_person_tickets_use_case.execute(platform="telegram", external_id="1002", limit=10)

    assert back_result.status == "support"
    assert "Отдел заботы" in back_result.message
    assert tickets == ()


def test_telegram_my_tickets_does_not_create_ticket_while_waiting_question() -> None:
    """Проверяет, что callback `my_tickets` в шаге ввода вопроса не создает новый тикет."""

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
    list_person_tickets_use_case = ListPersonSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    get_person_tickets_page_use_case = GetPersonTicketsPageTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        list_person_tickets_use_case=list_person_tickets_use_case,
        get_person_tickets_page_use_case=get_person_tickets_page_use_case,
    )

    adapter.register_contact(telegram_user_id=1003, raw_phone="+79125550103")
    adapter.handle_menu_action(
        telegram_user_id=1003,
        action_text="❓ Мне только спросить (В разработке)",
    )
    my_tickets_result = adapter.handle_menu_action(
        telegram_user_id=1003,
        action_text=GuestMenuAction.MY_TICKETS.value,
    )
    tickets = list_person_tickets_use_case.execute(platform="telegram", external_id="1003", limit=10)

    assert my_tickets_result.status == "tickets_empty"
    assert tickets == ()


def test_telegram_support_question_from_list_marks_has_tickets_true() -> None:
    """Проверяет, что создание нового тикета из списка сохраняет контекст возврата к списку."""

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
    list_person_tickets_use_case = ListPersonSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    get_person_tickets_page_use_case = GetPersonTicketsPageTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        list_person_tickets_use_case=list_person_tickets_use_case,
        get_person_tickets_page_use_case=get_person_tickets_page_use_case,
    )

    adapter.register_contact(telegram_user_id=1200, raw_phone="+79125550120")
    adapter.handle_menu_action(telegram_user_id=1200, action_text="❓ Мне только спросить")
    adapter.handle_menu_action(telegram_user_id=1200, action_text="Тестовый вопрос для создания тикета")

    result = adapter.handle_menu_action(
        telegram_user_id=1200,
        action_text=GuestMenuAction.SUPPORT_QUESTION_FROM_LIST.value,
    )

    assert result.status == "support_question_input"
    assert result.has_support_tickets is True


def test_telegram_my_tickets_shows_created_tickets() -> None:
    """Проверяет раздел «Мои обращения» после создания обращения пользователем."""

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
    list_person_tickets_use_case = ListPersonSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    get_person_tickets_page_use_case = GetPersonTicketsPageTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        list_person_tickets_use_case=list_person_tickets_use_case,
        get_person_tickets_page_use_case=get_person_tickets_page_use_case,
    )

    adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="telegram",
            external_id="1001",
            question_text="Нужна помощь",
        )
    )
    result = adapter.handle_menu_action(telegram_user_id=1001, action_text="📋 Мои обращения")

    assert result.status == "tickets_list"
    assert "Ваши обращения" in result.message
    assert "#" in result.message  # идентификатор тикета
    assert "тикет" in result.message.lower()  # упоминание в пояснении


def test_telegram_mod_requires_moderator_flag_and_routes_reply_via_fsm() -> None:
    """Проверяет доступ к `/mod` только для модератора и маршрутизацию ответа через FSM."""

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
    ticket_details_use_case = GetSupportTicketDetailsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    list_open_tickets_use_case = ListOpenSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        moderator_reply_use_case=moderator_reply_use_case,
        ticket_details_use_case=ticket_details_use_case,
        list_open_tickets_use_case=list_open_tickets_use_case,
    )

    adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="vk-777",
            raw_phone="+79123456789",
        )
    )

    created_ticket = create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="telegram",
            external_id="1001",
            question_text="Нужна помощь",
        )
    )
    ticket_id = str(created_ticket.ticket_id)

    forbidden = adapter.handle_menu_action(telegram_user_id=9999, action_text="/mod")
    assert forbidden.status == "moderation_forbidden"

    adapter.register_contact(telegram_user_id=9999, raw_phone="+79990009999")
    moderator_person = lookup_use_case.execute(
        GetPersonByAccountCommand(platform="telegram", external_id="9999")
    )
    assert moderator_person is not None

    with InMemoryIdentityUnitOfWork(repository) as unit_of_work:
        unit_of_work.identity_repository.update_person_profile(
            moderator_person.person_id,
            PersonProfilePatch(is_moderator=True),
        )
        unit_of_work.commit()

    open_menu = adapter.handle_menu_action(telegram_user_id=9999, action_text="/mod")
    wait_ticket = adapter.handle_menu_action(telegram_user_id=9999, action_text="2")
    wait_reply = adapter.handle_menu_action(telegram_user_id=9999, action_text=ticket_id)
    routed = adapter.handle_menu_action(telegram_user_id=9999, action_text="--to=vk Ответ отправлен.")
    details_step = adapter.handle_menu_action(telegram_user_id=9999, action_text="3")
    details = adapter.handle_menu_action(telegram_user_id=9999, action_text=ticket_id)
    unsupported = adapter.handle_menu_action(
        telegram_user_id=9999,
        action_text=f"/modreply {ticket_id} --to=vk Тест",
    )

    assert open_menu.status == "moderation_menu"
    assert wait_ticket.status == "moderation_wait_ticket_for_reply"
    assert wait_reply.status == "moderation_wait_reply_text"
    assert routed.status in {"moderation_routed", "moderation_ticket_details"}
    assert "Маршрут доставки: vk" in routed.message
    assert details_step.status == "moderation_wait_ticket_for_details"
    assert details.status == "moderation_details"
    assert unsupported.status == "moderation_menu_unknown"


def test_telegram_moderation_menu_fsm_supports_dirty_and_success_paths() -> None:
    """Проверяет `/mod`-меню: грязный UUID, успешный ответ и карточку тикета."""

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
    ticket_details_use_case = GetSupportTicketDetailsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    list_open_tickets_use_case = ListOpenSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        moderator_reply_use_case=moderator_reply_use_case,
        ticket_details_use_case=ticket_details_use_case,
        list_open_tickets_use_case=list_open_tickets_use_case,
    )

    adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    created_ticket = create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="telegram",
            external_id="1001",
            question_text="Нужна помощь с приложением",
        )
    )

    adapter.register_contact(telegram_user_id=9999, raw_phone="+79990009999")
    moderator_person = lookup_use_case.execute(
        GetPersonByAccountCommand(platform="telegram", external_id="9999")
    )
    assert moderator_person is not None
    with InMemoryIdentityUnitOfWork(repository) as unit_of_work:
        unit_of_work.identity_repository.update_person_profile(
            moderator_person.person_id,
            PersonProfilePatch(is_moderator=True),
        )
        unit_of_work.commit()

    open_menu = adapter.handle_menu_action(telegram_user_id=9999, action_text="/mod")
    wait_ticket = adapter.handle_menu_action(telegram_user_id=9999, action_text="2")
    dirty_ticket = adapter.handle_menu_action(telegram_user_id=9999, action_text="не-uuid")
    wait_reply = adapter.handle_menu_action(
        telegram_user_id=9999,
        action_text=str(created_ticket.ticket_id),
    )
    routed = adapter.handle_menu_action(telegram_user_id=9999, action_text="Ответ принят")

    wait_details = adapter.handle_menu_action(telegram_user_id=9999, action_text="3")
    details = adapter.handle_menu_action(
        telegram_user_id=9999,
        action_text=str(created_ticket.ticket_id),
    )

    assert open_menu.status == "moderation_menu"
    assert "Меню модератора" in open_menu.message
    assert wait_ticket.status == "moderation_wait_ticket_for_reply"
    assert dirty_ticket.status == "moderation_bad_ticket"
    assert wait_reply.status == "moderation_wait_reply_text"
    assert routed.status in {"moderation_routed", "moderation_ticket_details"}
    assert "Маршрут доставки: telegram" in routed.message
    assert wait_details.status == "moderation_wait_ticket_for_details"
    assert details.status == "moderation_details"
    assert "Канал создания:" in details.message
    assert "telegram" in details.message


def test_telegram_moderation_callback_menu_supports_pagination_and_ticket_actions() -> None:
    """Проверяет callback-меню модератора: фильтр, пагинацию, карточку и ответ."""

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
    ticket_details_use_case = GetSupportTicketDetailsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    list_open_tickets_use_case = ListOpenSupportTicketsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        moderator_reply_use_case=moderator_reply_use_case,
        ticket_details_use_case=ticket_details_use_case,
        list_open_tickets_use_case=list_open_tickets_use_case,
    )

    adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    created_tickets = [
        create_ticket_use_case.execute(
            CreateSupportTicketCommand(
                platform="telegram",
                external_id="1001",
                question_text=f"Нужна помощь #{index}",
            )
        )
        for index in range(6)
    ]
    first_ticket_id = created_tickets[0].ticket_id

    adapter.register_contact(telegram_user_id=9999, raw_phone="+79990009999")
    moderator_person = lookup_use_case.execute(
        GetPersonByAccountCommand(platform="telegram", external_id="9999")
    )
    assert moderator_person is not None
    with InMemoryIdentityUnitOfWork(repository) as unit_of_work:
        unit_of_work.identity_repository.update_person_profile(
            moderator_person.person_id,
            PersonProfilePatch(is_moderator=True),
        )
        unit_of_work.commit()

    open_menu = adapter.handle_menu_action(telegram_user_id=9999, action_text="/mod")
    list_page = adapter.handle_menu_action(telegram_user_id=9999, action_text="mod_list_new")
    details = adapter.handle_menu_action(
        telegram_user_id=9999,
        action_text=f"mod_ticket_{first_ticket_id}_new_1",
    )
    start_reply = adapter.handle_menu_action(
        telegram_user_id=9999,
        action_text=f"mod_reply_{first_ticket_id}_new_1",
    )
    routed = adapter.handle_menu_action(telegram_user_id=9999, action_text="Тестовый ответ")

    assert open_menu.status == "moderation_menu"
    assert list_page.status == "moderation_tickets_page"
    assert list_page.moderation_total_pages is not None
    assert list_page.moderation_total_pages >= 2
    assert details.status == "moderation_ticket_details"
    assert start_reply.status == "moderation_wait_reply_text"
    assert routed.status in {"moderation_ticket_details", "moderation_routed"}
    assert "Ответ модератора зарегистрирован" in routed.message


def test_telegram_ticket_details_screen_includes_ticket_history() -> None:
    """Проверяет, что карточка тикета в Telegram содержит историю сообщений, а не заглушку."""

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
    ticket_details_use_case = GetSupportTicketDetailsTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    ticket_conversation_use_case = GetSupportTicketConversationTransactionalUseCase(
        unit_of_work_factory=support_uow_factory
    )
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        ticket_details_use_case=ticket_details_use_case,
        ticket_conversation_use_case=ticket_conversation_use_case,
    )

    adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    adapter.handle_menu_action(telegram_user_id=1001, action_text="✅ Согласен")
    created_ticket = create_ticket_use_case.execute(
        CreateSupportTicketCommand(
            platform="telegram",
            external_id="1001",
            question_text="Нужна помощь с бонусами по карте",
        )
    )

    response = adapter.handle_menu_action(
        telegram_user_id=1001,
        action_text=f"user_ticket_{created_ticket.ticket_id}",
    )

    assert response.status == "ticket_details"
    assert response.parse_mode == "HTML"
    assert "История переписки" in response.message
    assert "Нужна помощь с бонусами по карте" in response.message
    assert "<blockquote>" in response.message
    assert "Гость" in response.message
    assert "недоступн" not in response.message.lower()
