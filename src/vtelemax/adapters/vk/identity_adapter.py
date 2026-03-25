"""VK-адаптер сценариев гостя на едином контракте core."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from loguru import logger

from vtelemax.core import (
    BUTTON_ACCEPT_RULES,
    CreateSupportTicketCommand,
    CreateSupportTicketTransactionalUseCase,
    GetLoyaltyBalanceUseCase,
    GetPersonByAccountCommand,
    GetPersonByAccountTransactionalUseCase,
    ListOpenSupportTicketsTransactionalUseCase,
    ListPersonSupportTicketsTransactionalUseCase,
    GetSupportTicketDetailsTransactionalUseCase,
    GetVirtualCardUseCase,
    GuestMenuAction,
    IdentityConflictError,
    ModeratorReplyCommand,
    OnboardingFlowService,
    OnboardingState,
    PersonSupportTicketSummary,
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
_STATE_MOD_MENU = "moderation_menu"
_STATE_MOD_WAIT_TICKET_FOR_REPLY = "moderation_wait_ticket_for_reply"
_STATE_MOD_WAIT_REPLY_TEXT = "moderation_wait_reply_text"
_STATE_MOD_WAIT_TICKET_FOR_DETAILS = "moderation_wait_ticket_for_details"


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
        list_open_tickets_use_case: ListOpenSupportTicketsTransactionalUseCase | None = None,
        list_person_tickets_use_case: ListPersonSupportTicketsTransactionalUseCase | None = None,
        balance_use_case: GetLoyaltyBalanceUseCase | None = None,
        virtual_card_use_case: GetVirtualCardUseCase | None = None,
    ) -> None:
        self._logger = logger.bind(platform="vk", component="identity_adapter")
        self._registration_use_case = registration_use_case
        self._person_lookup_use_case = person_lookup_use_case
        self._menu_adapter = menu_adapter or VkGuestMenuAdapter()
        self._state_by_user_id: dict[int, str] = {}
        self._moderator_state_by_user_id: dict[int, str] = {}
        self._moderator_context_by_user_id: dict[int, dict[str, str]] = {}
        self._onboarding_flow = OnboardingFlowService()
        self._create_support_ticket_use_case = create_support_ticket_use_case
        self._moderator_reply_use_case = moderator_reply_use_case
        self._ticket_details_use_case = ticket_details_use_case
        self._list_open_tickets_use_case = list_open_tickets_use_case
        self._list_person_tickets_use_case = list_person_tickets_use_case
        self._balance_use_case = balance_use_case
        self._virtual_card_use_case = virtual_card_use_case

    def handle_start(self, vk_user_id: int) -> VkAdapterResponse:
        """Обрабатывает стартовый вход пользователя в VK-бот."""

        method_logger = self._logger.bind(stage="handle_start", user_id=str(vk_user_id))
        method_logger.debug("Обработка стартового входа пользователя.")
        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        if person is None:
            method_logger.info("Пользователь не найден, запускаем onboarding.")
            transition = self._onboarding_flow.begin_new_user()
            self._state_by_user_id[vk_user_id] = transition.state.value
            self._clear_moderator_state(vk_user_id)
            rules_screen = self._menu_adapter.build_start_rules_screen()
            return VkAdapterResponse(text=transition.message, screen=rules_screen)

        self._state_by_user_id.pop(vk_user_id, None)
        self._clear_moderator_state(vk_user_id)
        method_logger.info("Пользователь найден, открываем главное меню.")
        main_screen = self._menu_adapter.build_main_menu_screen(user_name="Гость")
        return VkAdapterResponse(text=main_screen.text, screen=main_screen)

    def handle_legacy_start(self, vk_user_id: int) -> VkAdapterResponse:
        """Явно запускает legacy-ветку для зарегистрированного пользователя."""

        method_logger = self._logger.bind(stage="handle_legacy_start", user_id=str(vk_user_id))
        method_logger.debug("Обработка команды legacy.")
        person = self._person_lookup_use_case.execute(
            GetPersonByAccountCommand(platform="vk", external_id=str(vk_user_id))
        )
        if person is None:
            method_logger.info("Пользователь не найден, fallback на стартовый onboarding.")
            return self.handle_start(vk_user_id=vk_user_id)

        transition = self._onboarding_flow.begin_legacy_upgrade()
        method_logger.info("Legacy-flow запущен.")
        self._state_by_user_id[vk_user_id] = transition.state.value
        self._clear_moderator_state(vk_user_id)
        contact_screen = self._menu_adapter.build_start_contact_screen()
        return VkAdapterResponse(text=transition.message, screen=contact_screen)

    def handle_incoming(self, vk_user_id: int, text: str, payload: dict[str, str] | None) -> VkAdapterResponse:
        """Обрабатывает входящее сообщение VK (text + payload)."""

        method_logger = self._logger.bind(stage="handle_incoming", user_id=str(vk_user_id))
        method_logger.debug("Входящее сообщение. text={text}.", text=text)
        state = self._state_by_user_id.get(vk_user_id)
        if state == _STATE_WAITING_RULES_CONSENT:
            return self._handle_rules_consent(vk_user_id=vk_user_id, text=text, payload=payload)
        if state == _STATE_WAITING_PHONE:
            return self._handle_phone_input(vk_user_id=vk_user_id, text=text, is_legacy=False)
        if state == _STATE_WAITING_LEGACY_PHONE:
            return self._handle_phone_input(vk_user_id=vk_user_id, text=text, is_legacy=True)
        if state == _STATE_WAITING_SUPPORT_QUESTION:
            return self._handle_support_question(vk_user_id=vk_user_id, text=text)

        moderator_response = self._try_handle_moderator_command(text=text, vk_user_id=vk_user_id)
        if moderator_response is not None:
            return moderator_response

        moderator_state = self._moderator_state_by_user_id.get(vk_user_id)
        if moderator_state is not None:
            return self._handle_moderator_state_input(vk_user_id=vk_user_id, text=text)

        action = resolve_action_from_vk_payload(payload)
        if action is None:
            action = resolve_guest_menu_action(text)
        method_logger.debug("Распознанное действие: {action}.", action=action)

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

        method_logger = self._logger.bind(stage="phone_input", user_id=str(vk_user_id))
        phone_text = (text or "").strip()
        if not phone_text:
            method_logger.warning("Пустой ввод телефона.")
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
            method_logger.warning("Конфликт strict identity при регистрации телефона.")
            return VkAdapterResponse(
                text=(
                    "Обнаружен конфликт идентификации: этот VK-аккаунт уже привязан к другому "
                    "телефону или телефон связан с другим аккаунтом."
                )
            )
        except ValueError:
            method_logger.warning("Ошибка валидации телефона.")
            return VkAdapterResponse(
                text=(
                    "Не удалось обработать номер телефона. Введите номер в формате +79991234567 "
                    "и попробуйте снова."
                ),
                screen=self._menu_adapter.build_start_contact_screen(),
            )

        self._state_by_user_id.pop(vk_user_id, None)
        self._clear_moderator_state(vk_user_id)
        method_logger.info("Телефон успешно зарегистрирован. person_id={person_id}.", person_id=person.person_id)
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

    def _try_handle_moderator_command(
        self,
        *,
        text: str,
        vk_user_id: int,
    ) -> VkAdapterResponse | None:
        """Пытается обработать команду модератора."""

        raw = (text or "").strip()
        lowered = raw.lower()
        if lowered.startswith("/modreply"):
            return self._handle_modreply_command(raw)
        if lowered.startswith("/modticket"):
            return self._handle_modticket_command(raw)
        if lowered in {"/mod", "модератор", "moderator"}:
            return self._open_moderator_menu(vk_user_id=vk_user_id)
        return None

    def _open_moderator_menu(self, *, vk_user_id: int) -> VkAdapterResponse:
        """Открывает единое меню модератора."""

        if self._moderator_reply_use_case is None or self._ticket_details_use_case is None:
            return VkAdapterResponse(
                text="Меню модератора недоступно: не подключены сценарии modreply/modticket."
            )

        self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id.pop(vk_user_id, None)
        return VkAdapterResponse(text=self._build_moderation_menu_text())

    def _handle_moderator_state_input(self, *, vk_user_id: int, text: str) -> VkAdapterResponse:
        """Обрабатывает ввод модератора внутри FSM-режима."""

        state = self._moderator_state_by_user_id.get(vk_user_id)
        if state is None:
            return VkAdapterResponse(text=self._build_moderation_menu_text())

        raw = (text or "").strip()
        lowered = raw.lower()

        if lowered in {"отмена", "/cancel", "/mod", "меню"}:
            self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_MENU
            self._moderator_context_by_user_id.pop(vk_user_id, None)
            return VkAdapterResponse(text=self._build_moderation_menu_text())

        if lowered in {"выход", "0"}:
            self._clear_moderator_state(vk_user_id)
            return VkAdapterResponse(
                text="Режим модератора завершен. Для повторного входа используйте /mod."
            )

        if state == _STATE_MOD_MENU:
            return self._handle_moderator_menu_choice(vk_user_id=vk_user_id, lowered_text=lowered)

        if state == _STATE_MOD_WAIT_TICKET_FOR_REPLY:
            return self._handle_moderator_wait_ticket_for_reply(
                vk_user_id=vk_user_id,
                raw_ticket_id=raw,
            )

        if state == _STATE_MOD_WAIT_REPLY_TEXT:
            return self._handle_moderator_wait_reply_text(vk_user_id=vk_user_id, raw_message=raw)

        if state == _STATE_MOD_WAIT_TICKET_FOR_DETAILS:
            return self._handle_moderator_wait_ticket_for_details(
                vk_user_id=vk_user_id,
                raw_ticket_id=raw,
            )

        self._clear_moderator_state(vk_user_id)
        return VkAdapterResponse(
            text="Состояние модератора сброшено. Откройте меню заново через /mod."
        )

    def _handle_moderator_menu_choice(self, *, vk_user_id: int, lowered_text: str) -> VkAdapterResponse:
        """Обрабатывает выбор пункта главного меню модератора."""

        if lowered_text in {"1", "тикеты", "список"}:
            tickets_text = self._build_open_tickets_text(limit=10)
            return VkAdapterResponse(text=f"{tickets_text}\n\n{self._build_moderation_menu_text()}")

        if lowered_text in {"2", "ответ", "ответить"}:
            self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_WAIT_TICKET_FOR_REPLY
            self._moderator_context_by_user_id.pop(vk_user_id, None)
            return VkAdapterResponse(
                text=(
                    "Введите UUID тикета, для которого нужно отправить ответ.\n"
                    "Для отмены отправьте «Отмена»."
                )
            )

        if lowered_text in {"3", "карточка", "детали"}:
            self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_WAIT_TICKET_FOR_DETAILS
            self._moderator_context_by_user_id.pop(vk_user_id, None)
            return VkAdapterResponse(
                text=(
                    "Введите UUID тикета, чтобы показать карточку обращения.\n"
                    "Для отмены отправьте «Отмена»."
                )
            )

        return VkAdapterResponse(
            text=(
                "Не удалось распознать пункт меню модератора.\n"
                f"{self._build_moderation_menu_text()}"
            )
        )

    def _handle_moderator_wait_ticket_for_reply(
        self,
        *,
        vk_user_id: int,
        raw_ticket_id: str,
    ) -> VkAdapterResponse:
        """Обрабатывает ввод ticket_id перед отправкой модераторского ответа."""

        ticket_id = self._parse_ticket_id(raw_ticket_id)
        if ticket_id is None:
            return VkAdapterResponse(text="Некорректный ticket_id. Ожидается UUID.")

        if self._ticket_details_use_case is None:
            return VkAdapterResponse(
                text="Меню модератора недоступно: details-use-case не подключен."
            )

        try:
            self._ticket_details_use_case.execute(ticket_id)
        except ValueError as error:
            return VkAdapterResponse(text=f"Не удалось найти тикет: {error}")

        self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_WAIT_REPLY_TEXT
        self._moderator_context_by_user_id[vk_user_id] = {"ticket_id": str(ticket_id)}
        return VkAdapterResponse(
            text=(
                "Введите текст ответа модератора.\n"
                "Можно указать целевой канал префиксом: --to=telegram|vk|max.\n"
                "Пример: --to=telegram Добрый день, ответ готов."
            )
        )

    def _handle_moderator_wait_reply_text(self, *, vk_user_id: int, raw_message: str) -> VkAdapterResponse:
        """Обрабатывает ввод текста ответа модератора в FSM-режиме."""

        context = self._moderator_context_by_user_id.get(vk_user_id, {})
        raw_ticket_id = context.get("ticket_id")
        if raw_ticket_id is None:
            self._clear_moderator_state(vk_user_id)
            return VkAdapterResponse(
                text="Потерян ticket_id в состоянии модератора. Откройте /mod заново."
            )

        parsed = self._parse_target_and_reply_text(raw_message)
        if parsed is None:
            return VkAdapterResponse(text="Текст ответа модератора не может быть пустым.")
        preferred_target, message_text = parsed
        if preferred_target is not None and preferred_target not in SUPPORTED_PLATFORMS:
            return VkAdapterResponse(text="Недопустимая целевая платформа в --to.")

        if self._moderator_reply_use_case is None:
            return VkAdapterResponse(text="Маршрутизация ответа модератора пока недоступна.")

        try:
            route = self._moderator_reply_use_case.execute(
                ModeratorReplyCommand(
                    ticket_id=UUID(raw_ticket_id),
                    moderator_platform="vk",
                    reply_text=message_text,
                    preferred_target_platform=preferred_target,  # type: ignore[arg-type]
                )
            )
        except ValueError as error:
            return VkAdapterResponse(text=f"Не удалось маршрутизировать ответ: {error}")

        self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id.pop(vk_user_id, None)
        return VkAdapterResponse(
            text=(
                "Ответ модератора зарегистрирован.\n"
                f"Тикет: {route.ticket_id}\n"
                f"Канал исходного обращения: {route.guest_source_platform}\n"
                f"Маршрут доставки: {route.target_platform} ({route.target_external_id})\n"
                f"ID сообщения: {route.message_id}\n\n"
                f"{self._build_moderation_menu_text()}"
            )
        )

    def _handle_moderator_wait_ticket_for_details(
        self,
        *,
        vk_user_id: int,
        raw_ticket_id: str,
    ) -> VkAdapterResponse:
        """Обрабатывает ввод ticket_id для показа карточки тикета."""

        ticket_id = self._parse_ticket_id(raw_ticket_id)
        if ticket_id is None:
            return VkAdapterResponse(text="Некорректный ticket_id. Ожидается UUID.")

        if self._ticket_details_use_case is None:
            return VkAdapterResponse(
                text="Команда карточки тикета пока недоступна: details-use-case не подключен."
            )

        try:
            details = self._ticket_details_use_case.execute(ticket_id)
        except ValueError as error:
            return VkAdapterResponse(text=f"Не удалось загрузить тикет: {error}")

        self._moderator_state_by_user_id[vk_user_id] = _STATE_MOD_MENU
        self._moderator_context_by_user_id.pop(vk_user_id, None)
        linked = ", ".join(details.linked_platforms)
        return VkAdapterResponse(
            text=(
                f"Тикет: {details.ticket_id}\n"
                f"Статус: {details.status}\n"
                f"Канал создания: {details.source_platform}\n"
                f"Последний канал гостя: {details.last_guest_platform or '-'}\n"
                f"Каналы гостя: {linked}\n\n"
                f"{self._build_moderation_menu_text()}"
            )
        )

    def _build_open_tickets_text(self, *, limit: int) -> str:
        """Формирует текст открытых тикетов для модераторского меню."""

        if self._list_open_tickets_use_case is None:
            return "Список тикетов недоступен: list-open-use-case не подключен."

        tickets = self._list_open_tickets_use_case.execute(limit=limit)
        if not tickets:
            return "Открытых тикетов сейчас нет."

        lines = ["Открытые тикеты:"]
        for index, ticket in enumerate(tickets, start=1):
            lines.append(
                f"{index}. #{ticket.ticket_id} | канал={ticket.source_platform} | "
                f"последний={ticket.last_guest_platform or '-'}"
            )
        return "\n".join(lines)

    @staticmethod
    def _build_moderation_menu_text() -> str:
        """Возвращает текст главного меню модератора."""

        return (
            "🛠 Меню модератора\n"
            "1 — Список открытых тикетов\n"
            "2 — Ответить на тикет\n"
            "3 — Показать карточку тикета\n"
            "0 — Выйти из режима модератора"
        )

    @staticmethod
    def _parse_target_and_reply_text(raw_message: str) -> tuple[str | None, str] | None:
        """Разбирает optional `--to=` и текст ответа модератора."""

        raw = str(raw_message).strip()
        if not raw:
            return None

        parts = raw.split()
        preferred_target: str | None = None
        if parts and parts[0].lower().startswith("--to="):
            preferred_target = parts[0].split("=", maxsplit=1)[1].strip().lower()
            message_text = " ".join(parts[1:]).strip()
        else:
            message_text = raw

        if not message_text:
            return None
        return preferred_target, message_text

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

    def _clear_moderator_state(self, vk_user_id: int) -> None:
        """Очищает модераторское FSM-состояние пользователя."""

        self._moderator_state_by_user_id.pop(vk_user_id, None)
        self._moderator_context_by_user_id.pop(vk_user_id, None)

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
            return self._handle_balance_action(person_phone_e164=person.phone_e164)

        if action == GuestMenuAction.VIRTUAL_CARD:
            return self._handle_virtual_card_action(person_phone_e164=person.phone_e164)

        if action == GuestMenuAction.MY_TICKETS:
            tickets = self._list_user_tickets(
                platform="vk",
                external_id=str(vk_user_id),
                limit=10,
            )
            if not tickets:
                return VkAdapterResponse(
                    text=(
                        "📭 У вас пока нет обращений.\n\n"
                        "Чтобы создать обращение, нажмите «❓ Мне только спросить» в меню отдела заботы."
                    )
                )
            return VkAdapterResponse(text=self._format_person_tickets_message(tickets))

        if action == GuestMenuAction.SUPPORT_QUESTION:
            self._state_by_user_id[vk_user_id] = _STATE_WAITING_SUPPORT_QUESTION
            screen = self._menu_adapter.resolve_action_screen(action)
            return VkAdapterResponse(text=screen.text, screen=screen)

        if action == GuestMenuAction.MAIN_MENU:
            screen = self._menu_adapter.build_main_menu_screen(user_name="Гость")
            return VkAdapterResponse(text=screen.text, screen=screen)

        has_tickets = self._has_user_tickets(platform="vk", external_id=str(vk_user_id))
        screen = self._menu_adapter.resolve_action_screen(action, user_name="Гость", has_tickets=has_tickets)
        return VkAdapterResponse(text=screen.text, screen=screen)

    def _handle_balance_action(self, *, person_phone_e164: str) -> VkAdapterResponse:
        """Обрабатывает пункт меню «Мой баланс» через общий use-case лояльности."""

        if self._balance_use_case is None:
            return VkAdapterResponse(
                text=(
                    "❌ Информация о бонусах временно недоступна.\n"
                    "Пожалуйста, попробуйте позже или обратитесь к администратору."
                )
            )

        result = self._balance_use_case.execute(phone_e164=person_phone_e164)
        return VkAdapterResponse(text=result.message)

    def _handle_virtual_card_action(self, *, person_phone_e164: str) -> VkAdapterResponse:
        """Обрабатывает пункт меню «Виртуальная карта» через общий use-case лояльности."""

        if self._virtual_card_use_case is None:
            return VkAdapterResponse(
                text=(
                    "❌ Раздел виртуальной карты временно недоступен.\n"
                    "Пожалуйста, попробуйте позже или обратитесь к администратору."
                )
            )

        result = self._virtual_card_use_case.execute(phone_e164=person_phone_e164)
        return VkAdapterResponse(text=result.message)

    def _has_user_tickets(self, *, platform: str, external_id: str) -> bool:
        """Проверяет, есть ли у пользователя хотя бы один тикет поддержки."""

        return bool(self._list_user_tickets(platform=platform, external_id=external_id, limit=1))

    def _list_user_tickets(
        self,
        *,
        platform: str,
        external_id: str,
        limit: int,
    ) -> tuple[PersonSupportTicketSummary, ...]:
        """Возвращает тикеты пользователя для раздела «Мои обращения»."""

        if self._list_person_tickets_use_case is None:
            return ()
        try:
            return self._list_person_tickets_use_case.execute(
                platform=platform,  # type: ignore[arg-type]
                external_id=external_id,
                limit=limit,
            )
        except ValueError:
            return ()

    @staticmethod
    def _format_person_tickets_message(tickets: tuple[PersonSupportTicketSummary, ...]) -> str:
        """Форматирует список тикетов пользователя в текстовое представление."""

        lines = ["📋 Ваши обращения:"]
        status_emoji = {"open": "🆕", "closed": "🔒"}
        for ticket in tickets:
            created_at = ticket.created_at.strftime("%d.%m.%Y %H:%M") if ticket.created_at else "—"
            lines.append(
                "\n".join(
                    (
                        f"{status_emoji.get(ticket.status.value, '❓')} Тикет #{ticket.ticket_id}",
                        f"Статус: {ticket.status.value}",
                        f"Канал создания: {ticket.source_platform}",
                        f"Последняя платформа: {ticket.last_guest_platform or '—'}",
                        f"Создан: {created_at}",
                    )
                )
            )
        lines.append("\nЧтобы добавить новое сообщение, выберите «❓ Мне только спросить».")
        return "\n\n".join(lines)
