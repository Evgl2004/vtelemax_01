"""Тесты VK identity-адаптера."""

from __future__ import annotations

from types import TracebackType

from vtelemax.adapters.vk import VkIdentityAdapter
from vtelemax.core import (
    CreateSupportTicketTransactionalUseCase,
    GetPersonByAccountTransactionalUseCase,
    GetSupportTicketDetailsTransactionalUseCase,
    IdentityRepository,
    IdentityUnitOfWork,
    InMemoryIdentityRepository,
    InMemorySupportRepository,
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
    return VkIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        moderator_reply_use_case=moderator_reply_use_case,
        ticket_details_use_case=ticket_details_use_case,
    )


def _build_adapter_with_support_context() -> tuple[
    VkIdentityAdapter,
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
    adapter = VkIdentityAdapter(
        registration_use_case,
        lookup_use_case,
        create_support_ticket_use_case=create_ticket_use_case,
        moderator_reply_use_case=moderator_reply_use_case,
        ticket_details_use_case=ticket_details_use_case,
    )
    return adapter, registration_use_case


def _complete_vk_registration(adapter: VkIdentityAdapter, vk_user_id: int = 1001) -> None:
    adapter.handle_start(vk_user_id=vk_user_id)
    adapter.handle_incoming(vk_user_id=vk_user_id, text="✅ Согласен", payload=None)
    adapter.handle_incoming(vk_user_id=vk_user_id, text="+79123456789", payload=None)


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

    assert "Поделиться контактом" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "start_contact"


def test_vk_dirty_input_on_rules_step_keeps_consent_pending() -> None:
    """Проверяет грязный сценарий: случайный текст вместо согласия."""

    adapter = _build_adapter()
    adapter.handle_start(vk_user_id=1001)

    response = adapter.handle_incoming(vk_user_id=1001, text="хочу бонусы", payload=None)

    assert "Чтобы продолжить регистрацию" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "start_rules"


def test_vk_registration_by_phone_after_rules_consent() -> None:
    """Проверяет успешную регистрацию после согласия и ввода номера."""

    adapter = _build_adapter()
    adapter.handle_start(vk_user_id=1001)
    adapter.handle_incoming(vk_user_id=1001, text="✅ Согласен", payload=None)

    response = adapter.handle_incoming(vk_user_id=1001, text="+7 (912) 345-67-89", payload=None)

    assert "Регистрация успешно подтверждена" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "main_menu"


def test_vk_profile_available_after_registration() -> None:
    """Проверяет получение профиля после регистрации."""

    adapter = _build_adapter()
    _complete_vk_registration(adapter)

    response = adapter.handle_incoming(vk_user_id=1001, text="Мой профиль", payload=None)

    assert "Ваш профиль" in response.text
    assert "+79123456789" in response.text


def test_vk_invalid_phone_returns_validation_error() -> None:
    """Проверяет негативный сценарий при невалидном номере."""

    adapter = _build_adapter()
    adapter.handle_start(vk_user_id=1001)
    adapter.handle_incoming(vk_user_id=1001, text="✅ Согласен", payload=None)

    response = adapter.handle_incoming(vk_user_id=1001, text="abc", payload=None)

    assert "Не удалось обработать номер телефона" in response.text


def test_vk_support_question_flow_returns_to_main_menu() -> None:
    """Проверяет сценарий вопроса в поддержку с возвратом в меню."""

    adapter = _build_adapter()
    _complete_vk_registration(adapter)

    first = adapter.handle_incoming(vk_user_id=1001, text="❓ Мне только спросить", payload=None)
    second = adapter.handle_incoming(
        vk_user_id=1001,
        text="Когда начисляются бонусы?",
        payload=None,
    )

    assert "Введите ваш вопрос" in first.text
    assert "Ваш вопрос принят" in second.text
    assert second.screen is not None
    assert second.screen.screen_id == "main_menu"


def test_vk_legacy_start_requests_phone_confirmation() -> None:
    """Проверяет legacy-ветку с подтверждением телефона для зарегистрированного пользователя."""

    adapter = _build_adapter()
    _complete_vk_registration(adapter)

    legacy_start = adapter.handle_legacy_start(vk_user_id=1001)
    confirm = adapter.handle_incoming(vk_user_id=1001, text="+79123456789", payload=None)

    assert "предыдущей версии бота" in legacy_start.text
    assert legacy_start.screen is not None
    assert legacy_start.screen.screen_id == "start_contact"
    assert "legacy успешно обновлен" in confirm.text


def test_vk_moderator_reply_can_route_to_another_messenger() -> None:
    """Проверяет модерацию: ответ из VK с доставкой в другой канал."""

    adapter, register_use_case = _build_adapter_with_support_context()
    _complete_vk_registration(adapter, vk_user_id=1001)

    # Добавляем вторую привязку того же Person через Telegram в доменном use-case.
    register_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="tg-777",
            raw_phone="+79123456789",
        )
    )

    adapter.handle_incoming(vk_user_id=1001, text="❓ Мне только спросить", payload=None)
    ticket_response = adapter.handle_incoming(vk_user_id=1001, text="Нужна помощь", payload=None)
    ticket_id = ticket_response.text.split("#")[1].split("\n")[0].strip()

    reply = adapter.handle_incoming(
        vk_user_id=9999,
        text=f"/modreply {ticket_id} --to=telegram Ответ отправлен.",
        payload=None,
    )
    details = adapter.handle_incoming(vk_user_id=9999, text=f"/modticket {ticket_id}", payload=None)

    assert "Маршрут доставки: telegram" in reply.text
    assert "Канал создания: vk" in details.text
