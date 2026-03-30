"""Тесты единого onboarding-flow (регистрация + legacy)."""

from __future__ import annotations

from vtelemax.core import OnboardingFlowService, OnboardingState


def test_onboarding_begin_new_user_starts_with_rules_consent() -> None:
    """Проверяет старт нового пользователя с шага согласия."""

    service = OnboardingFlowService()

    transition = service.begin_new_user()

    assert transition.state == OnboardingState.WAITING_RULES_CONSENT
    assert transition.status == "rules_consent_required"
    assert "Согласен" in transition.message
    assert transition.requires_contact_keyboard is False


def test_onboarding_rules_accept_moves_to_phone_step() -> None:
    """Проверяет переход к шагу телефона после подтверждения правил."""

    service = OnboardingFlowService()

    transition = service.handle_rules_input("✅ Согласен")

    assert transition.state == OnboardingState.WAITING_PHONE
    assert transition.status == "phone_required"
    assert transition.requires_contact_keyboard is True
    assert "+79991234567" in transition.message


def test_onboarding_rules_reject_keeps_waiting_state() -> None:
    """Проверяет грязный сценарий: пользователь не подтверждает согласие."""

    service = OnboardingFlowService()

    transition = service.handle_rules_input("не согласен")

    assert transition.state == OnboardingState.WAITING_RULES_CONSENT
    assert transition.status == "rules_consent_pending"
    assert "отправьте сообщение" in transition.message.lower()


def test_onboarding_begin_legacy_requests_phone_confirmation() -> None:
    """Проверяет старт legacy-ветки с подтверждением телефона."""

    service = OnboardingFlowService()

    transition = service.begin_legacy_upgrade()

    assert transition.state == OnboardingState.WAITING_LEGACY_PHONE
    assert transition.status == "legacy_phone_confirmation_required"
    assert transition.requires_contact_keyboard is True
    assert "предыдущей версии" in transition.message
