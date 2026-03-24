"""Тесты use-case регистрации/привязки аккаунта."""

import pytest

from vtelemax.core import (
    IdentityConflictError,
    InMemoryIdentityRepository,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountUseCase,
)


def test_use_case_creates_new_person_for_first_registration() -> None:
    """Проверяет создание нового человека при первой регистрации."""

    repository = InMemoryIdentityRepository()
    use_case = RegisterOrAttachAccountUseCase(repository)

    person = use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="1001",
            raw_phone="+7 912 345 67 89",
        )
    )

    assert person.phone_e164 == "+79123456789"
    assert len(person.accounts) == 1


def test_use_case_merges_accounts_by_phone() -> None:
    """Проверяет объединение двух платформенных аккаунтов по одному телефону."""

    repository = InMemoryIdentityRepository()
    use_case = RegisterOrAttachAccountUseCase(repository)

    first_person = use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="1001",
            raw_phone="+79123456789",
        )
    )
    second_person = use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="2002",
            raw_phone="8 (912) 345-67-89",
        )
    )

    assert first_person.person_id == second_person.person_id
    assert len(second_person.accounts) == 2


def test_use_case_raises_conflict_for_cross_binding() -> None:
    """Проверяет конфликт, когда телефон и аккаунт уже заняты разными людьми."""

    repository = InMemoryIdentityRepository()
    use_case = RegisterOrAttachAccountUseCase(repository)

    use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="1001",
            raw_phone="+79123456789",
        )
    )
    use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="2002",
            raw_phone="+79991234567",
        )
    )

    with pytest.raises(IdentityConflictError):
        use_case.execute(
            RegisterOrAttachAccountCommand(
                platform="vk",
                external_id="2002",
                raw_phone="+79123456789",
            )
        )
