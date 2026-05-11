"""Тесты use-case регистрации/привязки аккаунта."""

from datetime import datetime, timezone

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


def test_use_case_is_idempotent_for_same_account() -> None:
    """Проверяет, что повторный вызов с тем же аккаунтом не создает конфликт."""

    repository = InMemoryIdentityRepository()
    use_case = RegisterOrAttachAccountUseCase(repository)

    first = use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="1001",
            raw_phone="+79123456789",
        )
    )
    second = use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="1001",
            raw_phone="8 (912) 345-67-89",
        )
    )

    assert first.person_id == second.person_id
    assert len(second.accounts) == 1


def test_use_case_rejects_empty_external_id() -> None:
    """Проверяет отклонение пустого или пробельного external_id."""

    repository = InMemoryIdentityRepository()
    use_case = RegisterOrAttachAccountUseCase(repository)

    with pytest.raises(ValueError):
        use_case.execute(
            RegisterOrAttachAccountCommand(
                platform="telegram",
                external_id="   ",
                raw_phone="+79123456789",
            )
        )


def test_use_case_rejects_unknown_platform() -> None:
    """Проверяет отклонение неподдерживаемого значения платформы."""

    repository = InMemoryIdentityRepository()
    use_case = RegisterOrAttachAccountUseCase(repository)

    with pytest.raises(ValueError):
        use_case.execute(
            RegisterOrAttachAccountCommand(
                platform="discord",  # type: ignore[arg-type]
                external_id="1001",
                raw_phone="+79123456789",
            )
        )


def test_use_case_keeps_once_true_flags_for_platform_state() -> None:
    """Проверяет инвариант: `rules_accepted/is_registered` не откатываются в false."""

    repository = InMemoryIdentityRepository()
    use_case = RegisterOrAttachAccountUseCase(repository)

    first_registered_at = datetime(2026, 5, 11, 10, 0, tzinfo=timezone.utc)
    use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="tg-1001",
            raw_phone="+79123456789",
            rules_accepted=True,
            rules_accepted_at=first_registered_at,
            notifications_allowed=True,
            notifications_allowed_at=first_registered_at,
            is_registered=True,
        )
    )

    person = use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="telegram",
            external_id="tg-1001",
            raw_phone="+79123456789",
            rules_accepted=False,
            notifications_allowed=False,
            is_registered=False,
        )
    )

    state = person.get_platform_state("telegram")
    assert state.rules_accepted is True
    assert state.is_registered is True
    assert person.rules_accepted is True
    assert person.is_registered is True


def test_use_case_does_not_overwrite_registered_at_after_reconsent() -> None:
    """Проверяет, что `registered_at` фиксируется один раз и не перезаписывается."""

    repository = InMemoryIdentityRepository()
    use_case = RegisterOrAttachAccountUseCase(repository)

    first_registered_at = datetime(2026, 5, 11, 10, 0, tzinfo=timezone.utc)
    second_notifications_at = datetime(2026, 5, 11, 12, 30, tzinfo=timezone.utc)

    use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="max",
            external_id="max-1001",
            raw_phone="+79990001122",
            rules_accepted=True,
            rules_accepted_at=first_registered_at,
            notifications_allowed=True,
            notifications_allowed_at=first_registered_at,
            is_registered=True,
        )
    )
    person = use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="max",
            external_id="max-1001",
            raw_phone="+79990001122",
            notifications_allowed=False,
            notifications_allowed_at=second_notifications_at,
            is_registered=True,
        )
    )

    state = person.get_platform_state("max")
    assert state.registered_at == first_registered_at
    assert state.notifications_allowed_at == second_notifications_at


def test_use_case_sets_vk_account_pending_verification_by_default() -> None:
    """Проверяет, что новые VK-аккаунты стартуют со статусом pending_verification."""

    repository = InMemoryIdentityRepository()
    use_case = RegisterOrAttachAccountUseCase(repository)

    person = use_case.execute(
        RegisterOrAttachAccountCommand(
            platform="vk",
            external_id="vk-1001",
            raw_phone="+79001234567",
        )
    )

    vk_accounts = [account for account in person.accounts if account.platform == "vk"]
    assert len(vk_accounts) == 1
    assert vk_accounts[0].lifecycle_status == "pending_verification"
