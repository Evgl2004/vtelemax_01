"""Единый onboarding-flow для регистрации и legacy-обновления.

Модуль фиксирует общий каркас сценария:

1. Новый пользователь: согласие с правилами -> отправка телефона.
2. Legacy-пользователь: подтверждение телефона для обновления профиля.

Адаптеры платформ (Telegram/VK/MAX) могут использовать одинаковые переходы,
меняя только транспортный слой (кнопки, callback и т.д.).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .guest_content import (
    BUTTON_ACCEPT_RULES,
    build_legacy_upgrade_screen,
    build_start_contact_screen,
    build_start_rules_screen,
    normalize_menu_text,
)


class OnboardingState(StrEnum):
    """Состояния общего onboarding-сценария."""

    IDLE = "idle"
    WAITING_RULES_CONSENT = "waiting_rules_consent"
    WAITING_PHONE = "waiting_phone"
    WAITING_LEGACY_PHONE = "waiting_legacy_phone"


@dataclass(frozen=True, slots=True)
class OnboardingTransition:
    """Результат перехода onboarding-сценария."""

    state: OnboardingState
    status: str
    message: str
    requires_contact_keyboard: bool = False


class OnboardingFlowService:
    """Общий сервис переходов onboarding для всех адаптеров."""

    def __init__(self, platform: str = "telegram") -> None:
        """Инициализирует сервис для указанной платформы.

        Поддерживаемые платформы: 'telegram', 'vk', 'max'.
        """
        self._platform = platform

    def begin_new_user(self) -> OnboardingTransition:
        """Запускает onboarding нового пользователя с шага согласия."""

        screen = build_start_rules_screen()
        return OnboardingTransition(
            state=OnboardingState.WAITING_RULES_CONSENT,
            status="rules_consent_required",
            message=(
                f"{screen.text}\n\n"
                "После ознакомления отправьте сообщение «✅ Согласен»."
            ),
        )

    def begin_legacy_upgrade(self) -> OnboardingTransition:
        """Запускает onboarding для legacy-пользователя."""

        screen = build_legacy_upgrade_screen()
        return OnboardingTransition(
            state=OnboardingState.WAITING_LEGACY_PHONE,
            status="legacy_phone_confirmation_required",
            message=screen.text,
            requires_contact_keyboard=True,
        )

    def handle_rules_input(self, raw_text: str) -> OnboardingTransition:
        """Обрабатывает пользовательский ответ на шаге согласия."""

        if self._is_rules_consent(raw_text):
            contact_screen = build_start_contact_screen(platform=self._platform)
            return OnboardingTransition(
                state=OnboardingState.WAITING_PHONE,
                status="phone_required",
                message=contact_screen.text,
                requires_contact_keyboard=True,
            )

        return OnboardingTransition(
            state=OnboardingState.WAITING_RULES_CONSENT,
            status="rules_consent_pending",
            message=(
                "Чтобы продолжить регистрацию, отправьте сообщение «✅ Согласен» "
                "после ознакомления с условиями."
            ),
        )

    @staticmethod
    def _is_rules_consent(raw_text: str) -> bool:
        """Проверяет, что пользователь подтвердил согласие с правилами."""

        normalized = normalize_menu_text(raw_text)
        accepted_variants = {
            normalize_menu_text(BUTTON_ACCEPT_RULES),
            "согласен",
            "согласна",
            "принимаю",
            "ok",
            "okay",
        }
        return normalized in accepted_variants
