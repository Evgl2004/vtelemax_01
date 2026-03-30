"""Тесты Telegram-адаптера строгой идентификации."""

from __future__ import annotations

from types import TracebackType

from vtelemax.adapters.telegram import TelegramIdentityAdapter
from vtelemax.core import (
    CreateSupportTicketCommand,
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

    def register_customer(self, phone_e164: str) -> LoyaltyRegisterCustomerResult:
        return LoyaltyRegisterCustomerResult(customer_id="cust-1", message="registered")

    def issue_card_for_customer(self, phone_e164: str, customer_id: str) -> LoyaltyIssueCardResult:
        return LoyaltyIssueCardResult(card_number="79123456789_20260325", message="issued")


class AlwaysFailLoyaltyGateway(LoyaltyGateway):
    """Тестовый шлюз, который всегда возвращает ошибку iiko."""

    def get_customer_info(self, phone_e164: str) -> LoyaltyCustomer | None:
        raise LoyaltyGatewayError("temporary unavailable")

    def register_customer(self, phone_e164: str) -> LoyaltyRegisterCustomerResult:
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

    def register_customer(self, phone_e164: str) -> LoyaltyRegisterCustomerResult:
        return LoyaltyRegisterCustomerResult(customer_id="cust-1", message="registered")

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
    result = adapter.handle_menu_action(telegram_user_id=1001, action_text="🪪 Виртуальная карта")

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

    pending_result = adapter.handle_menu_action(telegram_user_id=3003, action_text="/menu")
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


def test_telegram_support_question_reports_feature_in_development() -> None:
    """Проверяет, что пункт «Мне только спросить» помечен как неготовый для пользователей."""

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
    adapter = TelegramIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
    )

    adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    result = adapter.handle_menu_action(
        telegram_user_id=1001,
        action_text="❓ Мне только спросить (В разработке)",
    )

    assert result.status == "support_question_unavailable"
    assert "в разработке" in result.message.lower()


def test_telegram_support_question_flow_allows_back_to_support_menu() -> None:
    """После открытия неготового пункта возврат в меню заботы должен работать штатно."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(registration_use_case, lookup_use_case)

    adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    first = adapter.handle_menu_action(
        telegram_user_id=1001,
        action_text="❓ Мне только спросить (В разработке)",
    )
    back = adapter.handle_menu_action(telegram_user_id=1001, action_text="🔙 Назад в отдел заботы")

    assert first.status == "support_question_unavailable"
    assert back.status == "support"
    assert "Отдел заботы" in back.message


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
            question_text="Нужна помощь",
        )
    )
    result = adapter.handle_menu_action(telegram_user_id=1001, action_text="📋 Мои обращения")

    assert result.status == "tickets_list"
    assert "Ваши обращения" in result.message
    assert "Тикет #" in result.message


def test_telegram_moderation_commands_route_reply_and_show_ticket_details() -> None:
    """Проверяет `/modreply` и `/modticket` в Telegram-адаптере."""

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

    reply = adapter.handle_menu_action(
        telegram_user_id=9999,
        action_text=f"/modreply {ticket_id} --to=vk Ответ отправлен.",
    )
    details = adapter.handle_menu_action(telegram_user_id=9999, action_text=f"/modticket {ticket_id}")

    assert "Маршрут доставки: vk" in reply.message
    assert "Канал создания: telegram" in details.message


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
    assert routed.status == "moderation_routed"
    assert "Маршрут доставки: telegram" in routed.message
    assert wait_details.status == "moderation_wait_ticket_for_details"
    assert details.status == "moderation_details"
    assert "Канал создания: telegram" in details.message

