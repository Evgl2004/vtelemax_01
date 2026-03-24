"""Тесты strict identity сервиса."""

import pytest

from vtelemax.core.identity import IdentityConflictError, StrictIdentityService


def test_register_or_attach_account_merges_accounts_by_phone() -> None:
    """Проверяет, что разные платформы объединяются в одного человека по телефону."""

    service = StrictIdentityService()

    person_from_tg = service.register_or_attach_account(
        platform="telegram",
        external_id="1001",
        raw_phone="+7 (912) 345-67-89",
    )
    person_from_vk = service.register_or_attach_account(
        platform="vk",
        external_id="2002",
        raw_phone="8 (912) 345-67-89",
    )

    assert person_from_tg.person_id == person_from_vk.person_id
    assert len(person_from_tg.accounts) == 2


def test_register_or_attach_account_is_idempotent_for_same_account() -> None:
    """Проверяет повторную безопасную регистрацию одного и того же аккаунта."""

    service = StrictIdentityService()
    first = service.register_or_attach_account("telegram", "1001", "+79123456789")
    second = service.register_or_attach_account("telegram", "1001", "8 (912) 345-67-89")

    assert first.person_id == second.person_id
    assert len(second.accounts) == 1


def test_register_or_attach_account_raises_on_account_phone_conflict() -> None:
    """Проверяет запрет перепривязки существующего аккаунта на другой телефон."""

    service = StrictIdentityService()
    service.register_or_attach_account("telegram", "1001", "+79123456789")

    with pytest.raises(IdentityConflictError):
        service.register_or_attach_account("telegram", "1001", "+79991234567")


def test_register_or_attach_account_raises_on_cross_entity_conflict() -> None:
    """Проверяет конфликт, когда телефон и аккаунт уже заняты разными людьми."""

    service = StrictIdentityService()
    service.register_or_attach_account("telegram", "1001", "+79123456789")
    service.register_or_attach_account("vk", "2002", "+79991234567")

    with pytest.raises(IdentityConflictError):
        service.register_or_attach_account("vk", "2002", "+79123456789")

