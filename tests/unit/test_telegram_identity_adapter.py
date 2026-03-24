"""Тесты Telegram-адаптера строгой идентификации."""

from __future__ import annotations

from types import TracebackType

from vtelemax.adapters.telegram import TelegramIdentityAdapter
from vtelemax.core import (
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


def test_telegram_adapter_registers_contact_successfully() -> None:
    """Проверяет успешную регистрацию Telegram-контакта."""

    repository = InMemoryIdentityRepository()
    use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(use_case)

    result = adapter.register_contact(telegram_user_id=1001, raw_phone="+7 (912) 345-67-89")

    assert result.is_success is True
    assert result.status == "success"
    assert result.person_id is not None


def test_telegram_adapter_is_idempotent_for_repeated_registration() -> None:
    """Проверяет, что повторная регистрация того же аккаунта не создает дубликатов."""

    repository = InMemoryIdentityRepository()
    use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(use_case)

    first = adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    second = adapter.register_contact(telegram_user_id=1001, raw_phone="8 (912) 345-67-89")

    assert first.is_success is True
    assert second.is_success is True
    assert first.person_id == second.person_id


def test_telegram_adapter_returns_validation_error_for_bad_phone() -> None:
    """Проверяет ответ адаптера при невалидном формате телефона."""

    repository = InMemoryIdentityRepository()
    use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(use_case)

    result = adapter.register_contact(telegram_user_id=1001, raw_phone="abc")

    assert result.is_success is False
    assert result.status == "validation_error"


def test_telegram_adapter_returns_conflict_when_rebind_attempted() -> None:
    """Проверяет конфликт при попытке перепривязать тот же аккаунт к другому номеру."""

    repository = InMemoryIdentityRepository()
    use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    adapter = TelegramIdentityAdapter(use_case)

    adapter.register_contact(telegram_user_id=1001, raw_phone="+79123456789")
    result = adapter.register_contact(telegram_user_id=1001, raw_phone="+79991234567")

    assert result.is_success is False
    assert result.status == "conflict"
