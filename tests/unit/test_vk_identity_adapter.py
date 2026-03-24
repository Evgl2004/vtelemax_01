"""Тесты VK identity-адаптера."""

from __future__ import annotations

from types import TracebackType

from vtelemax.adapters.vk import VkIdentityAdapter
from vtelemax.core import (
    GetPersonByAccountTransactionalUseCase,
    IdentityRepository,
    IdentityUnitOfWork,
    InMemoryIdentityRepository,
    RegisterOrAttachAccountTransactionalUseCase,
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


def _build_adapter() -> VkIdentityAdapter:
    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    return VkIdentityAdapter(registration_use_case, lookup_use_case)


def test_vk_start_for_unregistered_user_requests_phone() -> None:
    """Проверяет, что `/start` для нового пользователя запрашивает телефон."""

    adapter = _build_adapter()

    response = adapter.handle_start(vk_user_id=1001)

    assert "Поделиться контактом" in response.text
    assert response.screen is not None


def test_vk_registration_by_phone_from_waiting_state() -> None:
    """Проверяет успешную регистрацию после ввода номера телефона."""

    adapter = _build_adapter()
    adapter.handle_start(vk_user_id=1001)

    response = adapter.handle_incoming(vk_user_id=1001, text="+7 (912) 345-67-89", payload=None)

    assert "Регистрация успешно подтверждена" in response.text
    assert response.screen is not None
    assert response.screen.screen_id == "main_menu"


def test_vk_profile_available_after_registration() -> None:
    """Проверяет получение профиля после регистрации."""

    adapter = _build_adapter()
    adapter.handle_start(vk_user_id=1001)
    adapter.handle_incoming(vk_user_id=1001, text="+79123456789", payload=None)

    response = adapter.handle_incoming(vk_user_id=1001, text="Мой профиль", payload=None)

    assert "Ваш профиль" in response.text
    assert "+79123456789" in response.text


def test_vk_invalid_phone_returns_validation_error() -> None:
    """Проверяет негативный сценарий при невалидном номере."""

    adapter = _build_adapter()
    adapter.handle_start(vk_user_id=1001)

    response = adapter.handle_incoming(vk_user_id=1001, text="abc", payload=None)

    assert "Не удалось обработать номер телефона" in response.text


def test_vk_support_question_flow_returns_to_main_menu() -> None:
    """Проверяет сценарий вопроса в поддержку с возвратом в меню."""

    adapter = _build_adapter()
    adapter.handle_start(vk_user_id=1001)
    adapter.handle_incoming(vk_user_id=1001, text="+79123456789", payload=None)

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
