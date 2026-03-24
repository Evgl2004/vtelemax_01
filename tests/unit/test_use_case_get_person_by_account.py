"""Тесты use-case получения пользователя по аккаунту платформы."""

from __future__ import annotations

import pytest

from vtelemax.core import (
    GetPersonByAccountCommand,
    GetPersonByAccountUseCase,
    InMemoryIdentityRepository,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountUseCase,
)


def test_get_person_by_account_returns_person_for_existing_binding() -> None:
    """Проверяет поиск зарегистрированного пользователя по аккаунту."""

    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountUseCase(repository)
    lookup_use_case = GetPersonByAccountUseCase(repository)

    created_person = registration_use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="1001",
            raw_phone="+79123456789",
        )
    )
    found_person = lookup_use_case.execute(
        GetPersonByAccountCommand(
            platform="telegram",
            external_id="1001",
        )
    )

    assert found_person is not None
    assert found_person.person_id == created_person.person_id


def test_get_person_by_account_returns_none_for_missing_binding() -> None:
    """Проверяет, что для отсутствующей привязки возвращается `None`."""

    repository = InMemoryIdentityRepository()
    lookup_use_case = GetPersonByAccountUseCase(repository)

    person = lookup_use_case.execute(
        GetPersonByAccountCommand(
            platform="telegram",
            external_id="2002",
        )
    )

    assert person is None


def test_get_person_by_account_rejects_unknown_platform() -> None:
    """Проверяет отклонение неподдерживаемой платформы."""

    repository = InMemoryIdentityRepository()
    lookup_use_case = GetPersonByAccountUseCase(repository)

    with pytest.raises(ValueError):
        lookup_use_case.execute(
            GetPersonByAccountCommand(
                platform="discord",  # type: ignore[arg-type]
                external_id="1001",
            )
        )


def test_get_person_by_account_rejects_empty_external_id() -> None:
    """Проверяет отклонение пустого `external_id`."""

    repository = InMemoryIdentityRepository()
    lookup_use_case = GetPersonByAccountUseCase(repository)

    with pytest.raises(ValueError):
        lookup_use_case.execute(
            GetPersonByAccountCommand(
                platform="telegram",
                external_id="   ",
            )
        )
