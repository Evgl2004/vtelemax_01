"""VK-адаптер сценариев гостя на едином контракте core."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from vtelemax.core import (
    BUTTON_ACCEPT_RULES,
    CreateSupportTicketCommand,
    CreateSupportTicketTransactionalUseCase,
    GetPersonByAccountCommand,
    GetPersonByAccountTransactionalUseCase,
    GetSupportTicketDetailsTransactionalUseCase,
    GuestMenuAction,
    IdentityConflictError,
    ModeratorReplyCommand,
    OnboardingFlowService,
    OnboardingState,
    RegisterOrAttachAccountCommand,
    RegisterOrAttachAccountTransactionalUseCase,
    RouteModeratorReplyTransactionalUseCase,
    SUPPORTED_PLATFORMS,
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
        create_support_ticket_use_case: CreateSupportTicketTransactionalUseCase | None = None,
        moderator_reply_use_case: RouteModeratorReplyTransactionalUseCase | None = None,
        ticket_details_use_case: GetSupportTicketDetailsTransactionalUseCase | None = None,
    ) -> None:
        self._registration_use_case = registration_use_case
        self._person_lookup_use_case = person_lookup_use_case
        self._menu_adapter = menu_adapter or VkGuestMenuAdapter()
        self._state_by_user_id: dict[int, str] = {}
        self._onboarding_flow = OnboardingFlowService()
        self._create_support_ticket_use_case = create_support_ticket_use_case
        self._moderator_reply_use_case = moderator_reply_use_case
        self._ticket_details_use_case = ticket_details_use_case

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

        moderator_response = self._try_handle_moderator_command(text)
        if moderator_response is not None:
            return moderator_response

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
        if self._create_support_ticket_use_case is None:
            ticket_message = (
                "📨 Ваш вопрос принят!\n"
                "Модератор рассмотрит обращение в ближайшее время."
            )
        else:
            try:
                created = self._create_support_ticket_use_case.execute(
                    CreateSupportTicketCommand(
                        platform="vk",
                        external_id=str(vk_user_id),
                        question_text=question,
                    )
                )
            except ValueError as error:
                return VkAdapterResponse(
                    text=(
                        "Не удалось зарегистрировать обращение в системе модерации.\n"
                        f"Причина: {error}"
                    )
                )
            ticket_message = (
                "📨 Ваш вопрос принят!\n"
                f"🎫 Создан тикет #{created.ticket_id}\n"
                "Канал обращения: vk\n"
                "Модератор рассмотрит обращение в ближайшее время."
            )

        return VkAdapterResponse(
            text=(
                f"{ticket_message}\n\n"
                f"{main_screen.text}"
            ),
            screen=main_screen,
        )

    def _try_handle_moderator_command(self, text: str) -> VkAdapterResponse | None:
        """Пытается обработать команду модератора."""

        raw = (text or "").strip()
        lowered = raw.lower()
        if lowered.startswith("/modreply"):
            return self._handle_modreply_command(raw)
        if lowered.startswith("/modticket"):
            return self._handle_modticket_command(raw)
        return None

    def _handle_modreply_command(self, raw: str) -> VkAdapterResponse:
        """Обрабатывает команду модератора `/modreply`."""

        if self._moderator_reply_use_case is None:
            return VkAdapterResponse(
                text=(
                    "Команда модерации пока недоступна: сценарий маршрутизации не подключен.\n"
                    "Обратитесь к администратору проекта."
                )
            )

        parts = raw.split()
        if len(parts) < 3:
            return VkAdapterResponse(
                text=(
                    "Формат: /modreply <ticket_id> [--to=telegram|vk|max] <текст ответа>"
                )
            )

        ticket_id = self._parse_ticket_id(parts[1])
        if ticket_id is None:
            return VkAdapterResponse(text="Некорректный ticket_id. Ожидается UUID.")

        preferred_target: str | None = None
        message_start_index = 2
        if len(parts) >= 4 and parts[2].lower().startswith("--to="):
            preferred_target = parts[2].split("=", maxsplit=1)[1].strip().lower()
            message_start_index = 3

        message_text = " ".join(parts[message_start_index:]).strip()
        if not message_text:
            return VkAdapterResponse(text="Текст ответа модератора не может быть пустым.")

        if preferred_target is not None and preferred_target not in SUPPORTED_PLATFORMS:
            return VkAdapterResponse(text="Недопустимая целевая платформа в --to.")

        try:
            route = self._moderator_reply_use_case.execute(
                ModeratorReplyCommand(
                    ticket_id=ticket_id,
                    moderator_platform="vk",
                    reply_text=message_text,
                    preferred_target_platform=preferred_target,  # type: ignore[arg-type]
                )
            )
        except ValueError as error:
            return VkAdapterResponse(text=f"Не удалось маршрутизировать ответ: {error}")

        return VkAdapterResponse(
            text=(
                "Ответ модератора зарегистрирован.\n"
                f"Тикет: {route.ticket_id}\n"
                f"Канал исходного обращения: {route.guest_source_platform}\n"
                f"Маршрут доставки: {route.target_platform} ({route.target_external_id})\n"
                f"ID сообщения: {route.message_id}"
            )
        )

    def _handle_modticket_command(self, raw: str) -> VkAdapterResponse:
        """Обрабатывает команду модератора `/modticket`."""

        if self._ticket_details_use_case is None:
            return VkAdapterResponse(
                text=(
                    "Команда карточки тикета пока недоступна: details-use-case не подключен."
                )
            )

        parts = raw.split()
        if len(parts) != 2:
            return VkAdapterResponse(text="Формат: /modticket <ticket_id>")

        ticket_id = self._parse_ticket_id(parts[1])
        if ticket_id is None:
            return VkAdapterResponse(text="Некорректный ticket_id. Ожидается UUID.")

        try:
            details = self._ticket_details_use_case.execute(ticket_id)
        except ValueError as error:
            return VkAdapterResponse(text=f"Не удалось загрузить тикет: {error}")

        linked = ", ".join(details.linked_platforms)
        return VkAdapterResponse(
            text=(
                f"Тикет: {details.ticket_id}\n"
                f"Статус: {details.status}\n"
                f"Канал создания: {details.source_platform}\n"
                f"Последний канал гостя: {details.last_guest_platform or '-'}\n"
                f"Каналы гостя: {linked}"
            )
        )

    @staticmethod
    def _parse_ticket_id(raw_ticket_id: str) -> UUID | None:
        try:
            return UUID(raw_ticket_id)
        except ValueError:
            return None

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
