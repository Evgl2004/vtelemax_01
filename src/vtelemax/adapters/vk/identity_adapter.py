"""VK-адаптер сценариев гостя на едином контракте core."""

from __future__ import annotations

from dataclasses import dataclass

from vtelemax.core import (
    BUTTON_ACCEPT_RULES,
    GetPersonByAccountCommand,
    GetPersonByAccountTransactionalUseCase,
    GuestMenuAction,
    IdentityConflictError,
    OnboardingFlowService,
    OnboardingState,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
    resolve_guest_menu_action,
)

from .menu_adapter import VkGuestMenuAdapter, VkScreen
from .payloads import resolve_action_from_vk_payload

_STATE_WAITING_PHONE = OnboardingState.WAITING_PHONE.value
_STATE_WAITING_RULES_CONSENT = OnboardingState.WAITING_RULES_CONSENT.value
_STATE_WAITING_LEGACY_PHONE = OnboardingState.WAITING_LEGACY_PHONE.value
_STATE_WAITING_SUPPORT_QUESTION = "waiting_support_question"


@dataclass(frozen=True, slots=True)
class VkAdapterResponse:
    """Ответ VK-адаптера для отправки пользователю."""

    text: str
    screen: VkScreen | None = None


class VkIdentityAdapter:
    """Сервисный VK-адаптер для guest-сценариев."""

    def __init__(
        self,
        registration_use_case: RegisterOrAttachAccountTransactionalUseCase,
        person_lookup_use_case: GetPersonByAccountTransactionalUseCase,
        menu_adapter: VkGuestMenuAdapter | None = None,
    ) -> None:
        self._registration_use_case = registration_use_case
        self._person_lookup_use_case = person_lookup_use_case
        self._menu_adapter = menu_adapter or VkGuestMenuAdapter()
        self._state_by_user_id: dict[int, str] = {}
        self._onboarding_flow = OnboardingFlowService()

    def handle_start(self, vk_user_id: int) -> VkAdapterResponse:
        """Обрабатывает стартовый вход пользователя в VK-бот."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        if person is None:
            transition = self._onboarding_flow.begin_new_user()
            self._state_by_user_id[vk_user_id] = transition.state.value
            rules_screen = self._menu_adapter.build_start_rules_screen()
            return VkAdapterResponse(text=transition.message, screen=rules_screen)

        self._state_by_user_id.pop(vk_user_id, None)
        main_screen = self._menu_adapter.build_main_menu_screen(user_name="Гость")
        return VkAdapterResponse(text=main_screen.text, screen=main_screen)

    def handle_legacy_start(self, vk_user_id: int) -> VkAdapterResponse:
        """Явно запускает legacy-ветку для зарегистрированного пользователя."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        if person is None:
            return self.handle_start(vk_user_id=vk_user_id)

        transition = self._onboarding_flow.begin_legacy_upgrade()
        self._state_by_user_id[vk_user_id] = transition.state.value
        contact_screen = self._menu_adapter.build_start_contact_screen()
        return VkAdapterResponse(text=transition.message, screen=contact_screen)

    def handle_incoming(self, vk_user_id: int, text: str, payload: dict[str, str] | None) -> VkAdapterResponse:
        """Обрабатывает входящее сообщение VK (text + payload)."""

        state = self._state_by_user_id.get(vk_user_id)
        if state == _STATE_WAITING_RULES_CONSENT:
            return self._handle_rules_consent(vk_user_id=vk_user_id, text=text, payload=payload)
        if state == _STATE_WAITING_PHONE:
            return self._handle_phone_input(vk_user_id=vk_user_id, text=text, is_legacy=False)
        if state == _STATE_WAITING_LEGACY_PHONE:
            return self._handle_phone_input(vk_user_id=vk_user_id, text=text, is_legacy=True)
        if state == _STATE_WAITING_SUPPORT_QUESTION:
            return self._handle_support_question(vk_user_id=vk_user_id, text=text)

        action = resolve_action_from_vk_payload(payload)
        if action is None:
            action = resolve_guest_menu_action(text)

        if action is None:
            person = self._person_lookup_use_case.execute(
                GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
            )
            if person is None:
                self._state_by_user_id[vk_user_id] = _STATE_WAITING_RULES_CONSENT
                rules_screen = self._menu_adapter.build_start_rules_screen()
                return VkAdapterResponse(
                    text=(
                        "Чтобы продолжить, сначала подтвердите согласие с правилами.\n\n"
                        f"{rules_screen.text}"
                    ),
                    screen=rules_screen,
                )
            main_screen = self._menu_adapter.build_main_menu_screen(user_name="Гость")
            return VkAdapterResponse(
                text=(
                    "Команда не распознана. Используйте кнопки меню.\n\n"
                    f"{main_screen.text}"
                ),
                screen=main_screen,
            )

        return self._handle_action(vk_user_id=vk_user_id, action=action)

    def _handle_rules_consent(
        self,
        vk_user_id: int,
        text: str,
        payload: dict[str, str] | None,
    ) -> VkAdapterResponse:
        """Обрабатывает шаг подтверждения согласия с правилами."""

        action = resolve_action_from_vk_payload(payload)
        consent_input = text
        if action == GuestMenuAction.SHARE_CONTACT:
            consent_input = BUTTON_ACCEPT_RULES

        transition = self._onboarding_flow.handle_rules_input(consent_input)
        self._state_by_user_id[vk_user_id] = transition.state.value
        if transition.state == OnboardingState.WAITING_PHONE:
            screen = self._menu_adapter.build_start_contact_screen()
        else:
            screen = self._menu_adapter.build_start_rules_screen()
        return VkAdapterResponse(text=transition.message, screen=screen)

    def _handle_phone_input(self, vk_user_id: int, text: str, *, is_legacy: bool) -> VkAdapterResponse:
        """Обрабатывает ввод телефона для регистрации/legacy-обновления."""

        phone_text = (text or "").strip()
        if not phone_text:
            return VkAdapterResponse(
                text="Пожалуйста, введите номер телефона текстом в формате +79991234567.",
                screen=self._menu_adapter.build_start_contact_screen(),
            )

        try:
            person = self._registration_use_case.execute(
                RegisterOrAttachAccountCommand(
                    platform="vk",
                    external_id=str(vk_user_id),
                    raw_phone=phone_text,
                )
            )
        except IdentityConflictError:
            return VkAdapterResponse(
                text=(
                    "Обнаружен конфликт идентификации: этот VK-аккаунт уже привязан к другому "
                    "телефону или телефон связан с другим аккаунтом."
                )
            )
        except ValueError:
            return VkAdapterResponse(
                text=(
                    "Не удалось обработать номер телефона. Введите номер в формате +79991234567 "
                    "и попробуйте снова."
                ),
                screen=self._menu_adapter.build_start_contact_screen(),
            )

        self._state_by_user_id.pop(vk_user_id, None)
        main_screen = self._menu_adapter.build_main_menu_screen(user_name="Гость")
        if is_legacy:
            success_title = "Профиль legacy успешно обновлен. Номер подтвержден в единой базе."
        else:
            success_title = "Регистрация успешно подтверждена. Ваш номер сохранен в единой базе."
        return VkAdapterResponse(
            text=(
                f"{success_title}\n\n"
                f"{main_screen.text}\n\n"
                f"Ваш телефон: {person.phone_e164}"
            ),
            screen=main_screen,
        )

    def _handle_support_question(self, vk_user_id: int, text: str) -> VkAdapterResponse:
        """Обрабатывает шаг 'Мне только спросить' (ввод вопроса)."""

        question = (text or "").strip()
        if not question:
            return VkAdapterResponse(
                text="Пожалуйста, отправьте вопрос текстом. Мы передадим его модератору."
            )

        self._state_by_user_id.pop(vk_user_id, None)
        main_screen = self._menu_adapter.build_main_menu_screen(user_name="Гость")
        return VkAdapterResponse(
            text=(
                "📨 Ваш вопрос принят!\n"
                "Модератор рассмотрит обращение в ближайшее время.\n\n"
                f"{main_screen.text}"
            ),
            screen=main_screen,
        )

    def _handle_action(self, vk_user_id: int, action: GuestMenuAction) -> VkAdapterResponse:
        """Обрабатывает пункт меню для зарегистрированного пользователя."""

        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )

        if person is None and action not in {GuestMenuAction.MAIN_MENU, GuestMenuAction.SHARE_CONTACT}:
            self._state_by_user_id[vk_user_id] = _STATE_WAITING_RULES_CONSENT
            rules_screen = self._menu_adapter.build_start_rules_screen()
            return VkAdapterResponse(
                text=(
                    "Раздел доступен после регистрации. Сначала подтвердите согласие с правилами.\n\n"
                    f"{rules_screen.text}"
                ),
                screen=rules_screen,
            )

        if action == GuestMenuAction.SHARE_CONTACT:
            if person is None:
                self._state_by_user_id[vk_user_id] = _STATE_WAITING_PHONE
            else:
                self._state_by_user_id[vk_user_id] = _STATE_WAITING_LEGACY_PHONE
            contact_screen = self._menu_adapter.build_start_contact_screen()
            return VkAdapterResponse(text=contact_screen.text, screen=contact_screen)

        if action == GuestMenuAction.PROFILE:
            if person is None:
                screen = self._menu_adapter.build_profile_not_found_screen()
                return VkAdapterResponse(text=screen.text, screen=screen)
            screen = self._menu_adapter.build_profile_screen(
                phone_e164=person.phone_e164,
                accounts_count=len(person.accounts),
            )
            return VkAdapterResponse(text=screen.text, screen=screen)

        if action == GuestMenuAction.BALANCE:
            return VkAdapterResponse(
                text=(
                    "❌ Информация о бонусах временно недоступна.\n"
                    "Пожалуйста, попробуйте позже или обратитесь к администратору."
                )
            )

        if action == GuestMenuAction.VIRTUAL_CARD:
            return VkAdapterResponse(
                text=(
                    "🪪 Раздел виртуальной карты пока недоступен в этом адаптере.\n"
                    "Скоро подключим полный сценарий выпуска и показа QR."
                )
            )

        if action == GuestMenuAction.MY_TICKETS:
            return VkAdapterResponse(
                text=(
                    "📋 Раздел 'Мои обращения' пока в разработке для VK-адаптера.\n"
                    "Мы подключим его следующим этапом."
                )
            )

        if action == GuestMenuAction.SUPPORT_QUESTION:
            self._state_by_user_id[vk_user_id] = _STATE_WAITING_SUPPORT_QUESTION
            screen = self._menu_adapter.resolve_action_screen(action)
            return VkAdapterResponse(text=screen.text, screen=screen)

        if action == GuestMenuAction.MAIN_MENU:
            screen = self._menu_adapter.build_main_menu_screen(user_name="Гость")
            return VkAdapterResponse(text=screen.text, screen=screen)

        screen = self._menu_adapter.resolve_action_screen(action, user_name="Гость", has_tickets=False)
        return VkAdapterResponse(text=screen.text, screen=screen)
