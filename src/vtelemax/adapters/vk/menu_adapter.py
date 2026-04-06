"""Стартовый VK-адаптер меню на едином контракте core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from vtelemax.core import (
    GuestMenuAction,
    MenuButtonContract,
    PersonSupportTicketSummary,
    BUTTON_MY_TICKETS,
    BUTTON_BACK_TO_SUPPORT,
    build_about_screen,
    build_balance_screen,
    build_delivery_screen,
    build_notifications_consent_screen,
    build_iiko_sync_pending_screen,
    build_iiko_sync_retry_screen,
    build_help_screen,
    build_main_menu_screen,
    build_profile_edit_screen,
    build_profile_gender_screen,
    build_profile_not_found_screen,
    build_profile_screen,
    build_virtual_card_result_screen,
    build_start_contact_screen,
    build_start_rules_screen,
    build_support_contacts_screen,
    build_support_feedback_screen,
    build_support_menu_screen,
    build_support_question_screen,
    build_support_question_confirmation_screen,
    build_vacancies_screen,
)

from .payloads import build_vk_payload

# Префиксы callback'ов пагинации тикетов (аналогично Telegram)
USER_TICKETS_PREV_PAGE_PREFIX = "user_tickets_prev_"
USER_TICKETS_NEXT_PAGE_PREFIX = "user_tickets_next_"
USER_TICKET_DETAILS_PREFIX = "user_ticket_"


@dataclass(frozen=True, slots=True)
class VkButton:
    """Унифицированная кнопка VK для дальнейшего рендера в vkbottle."""

    label: str
    payload: dict[str, str]
    url: str | None = None


@dataclass(frozen=True, slots=True)
class VkScreen:
    """Унифицированный ответ VK-адаптера."""

    screen_id: str
    text: str
    rows: tuple[tuple[VkButton, ...], ...]
    parse_mode: str | None = None


def _to_vk_button(button: MenuButtonContract) -> VkButton:
    return VkButton(
        label=button.label,
        payload=build_vk_payload(button.action),
        url=button.url,
    )


class VkGuestMenuAdapter:
    """Преобразует core-контент в формат VK-экрана."""

    def build_start_rules_screen(self) -> VkScreen:
        """Стартовый экран правил."""

        screen = build_start_rules_screen(platform="vk")
        rows = tuple((_to_vk_button(button),) for button in screen.buttons)
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_start_contact_screen(self) -> VkScreen:
        """Экран запроса телефона."""

        screen = build_start_contact_screen(platform="vk")
        rows = ((_to_vk_button(screen.buttons[0]),),) if screen.buttons else ()
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_main_menu_screen(self, user_name: str = "Гость") -> VkScreen:
        """Главное меню гостя (пять разделов, вертикальный список)."""

        screen = build_main_menu_screen(user_name=user_name)
        vk_buttons = [_to_vk_button(button) for button in screen.buttons]
        # Специальная группировка для соответствия лимитам VK inline-клавиатуры (макс. 6 строк)
        # и логическому объединению кнопок поддержки.
        # Порядок кнопок из guest_content:
        # 0: Баланс, 1: Виртуальная карта, 2: Доставка, 3: Мне только спросить,
        # 4: Вакансии, 5: Обратная связь, 6: Профиль
        rows: list[tuple[VkButton, ...]] = [
            (vk_buttons[0], vk_buttons[1]),                     # Баланс | Виртуальная карта
            (vk_buttons[3],),                                   # Мне только спросить
            (vk_buttons[5],),                                   # Обратная связь
            (vk_buttons[2], vk_buttons[4]),                     # Доставка | Вакансии
            (vk_buttons[6],),                                   # Профиль
        ]
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=tuple(rows))

    def build_support_menu_screen(self, has_tickets: bool) -> VkScreen:
        """Экран поддержки с условной кнопкой 'Мои обращения'."""

        screen = build_support_menu_screen(has_tickets=has_tickets)
        buttons = [_to_vk_button(button) for button in screen.buttons]
        rows: list[tuple[VkButton, ...]] = []
        for button in buttons:
            rows.append((button,))
        return VkScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=tuple(rows),
            parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_profile_screen(
        self,
        phone_e164: str,
        accounts_count: int,
        accounts_platforms: tuple[str, ...] | None = None,
        *,
        first_name_input: str | None = None,
        last_name_input: str | None = None,
        gender: str | None = None,
        birth_date: date | None = None,
        email: str | None = None,
        rules_accepted: bool = False,
        rules_accepted_at: datetime | None = None,
        notifications_allowed: bool | None = None,
        notifications_allowed_at: datetime | None = None,
    ) -> VkScreen:
        """Экран профиля зарегистрированного пользователя."""

        screen = build_profile_screen(
            phone_e164=phone_e164,
            accounts_count=accounts_count,
            accounts_platforms=accounts_platforms,
            first_name_input=first_name_input,
            last_name_input=last_name_input,
            gender=gender,
            birth_date=birth_date,
            email=email,
            rules_accepted=rules_accepted,
            rules_accepted_at=rules_accepted_at,
            notifications_allowed=notifications_allowed,
            notifications_allowed_at=notifications_allowed_at,
        )
        rows = tuple((_to_vk_button(button),) for button in screen.buttons)
        return VkScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_profile_edit_screen(self, *, can_edit_birth_date: bool) -> VkScreen:
        """Экран выбора поля для редактирования профиля."""

        screen = build_profile_edit_screen(can_edit_birth_date=can_edit_birth_date)
        rows = tuple((_to_vk_button(button),) for button in screen.buttons)
        return VkScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_profile_gender_screen(self) -> VkScreen:
        """Экран выбора пола в режиме редактирования профиля."""

        screen = build_profile_gender_screen()
        rows = tuple((_to_vk_button(button),) for button in screen.buttons)
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_notifications_consent_screen(self, profile_text: str | None = None) -> VkScreen:
        """Экран согласия на рассылку после review-анкеты."""

        screen = build_notifications_consent_screen(profile_text=profile_text, platform="vk")
        rows = tuple((_to_vk_button(button),) for button in screen.buttons)
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_balance_screen(self, balance: float) -> VkScreen:
        """Экран бонусного баланса."""

        screen = build_balance_screen(balance=balance)
        rows = ((_to_vk_button(screen.buttons[0]),),) if screen.buttons else ()
        return VkScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
        )
    def build_profile_not_found_screen(self) -> VkScreen:
        """Экран незарегистрированного пользователя."""

        screen = build_profile_not_found_screen()
        rows = ((_to_vk_button(screen.buttons[0]),),) if screen.buttons else ()
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_help_screen(self) -> VkScreen:
        """Экран справки."""

        screen = build_help_screen()
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=())

    def build_about_screen(self) -> VkScreen:
        """Экран 'О проекте'."""

        screen = build_about_screen()
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=())

    def build_vacancies_screen(self) -> VkScreen:
        """Экран вакансий."""

        screen = build_vacancies_screen()
        rows = ((_to_vk_button(screen.buttons[0]),),) if screen.buttons else ()
        return VkScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_delivery_screen(self) -> VkScreen:
        """Экран подменю «Доставка» со ссылками на заведения."""

        screen = build_delivery_screen()
        rows = tuple((_to_vk_button(button),) for button in screen.buttons)
        return VkScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_support_feedback_screen(self) -> VkScreen:
        """Экран обратной связи."""

        screen = build_support_feedback_screen()
        rows = tuple((_to_vk_button(button),) for button in screen.buttons)
        return VkScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_support_question_screen(self) -> VkScreen:
        """Экран создания обращения."""

        screen = build_support_question_screen()
        rows = ((_to_vk_button(screen.buttons[0]),),) if screen.buttons else ()
        return VkScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_support_question_confirmation_screen(self) -> VkScreen:
        """Экран подтверждения создания тикета (после отправки вопроса)."""

        screen = build_support_question_confirmation_screen()
        rows = tuple((_to_vk_button(button),) for button in screen.buttons)
        return VkScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="Markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_support_contacts_screen(self) -> VkScreen:
        """Экран контактов."""

        screen = build_support_contacts_screen()
        rows = ((_to_vk_button(screen.buttons[0]),),) if screen.buttons else ()
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_virtual_card_result_screen(self) -> VkScreen:
        """Экран после отправки QR-кодов виртуальной карты."""

        screen = build_virtual_card_result_screen()
        rows = tuple((_to_vk_button(button),) for button in screen.buttons)
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_iiko_sync_retry_screen(self) -> VkScreen:
        """Экран повторной синхронизации с iiko."""

        screen = build_iiko_sync_retry_screen()
        rows = tuple((_to_vk_button(button),) for button in screen.buttons)
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_iiko_sync_pending_screen(self) -> VkScreen:
        """Экран ожидания синхронизации с iiko."""

        screen = build_iiko_sync_pending_screen()
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=())

    def build_user_tickets_pagination_screen(
        self,
        current_page: int,
        total_pages: int,
        tickets: tuple[PersonSupportTicketSummary, ...] = (),
        has_tickets: bool = True,
    ) -> VkScreen:
        """Создает экран пагинации списка тикетов пользователя с кнопками тикетов."""
        
        rows = []
        
        # Кнопки тикетов (группируем по 2 в строке для экономии строк)
        if tickets:
            ticket_rows = []
            current_row = []
            for ticket in tickets:
                # Эмодзи статуса
                status_emoji = {
                    "open": "🆕",
                    "closed": "🔒",
                }.get(ticket.status.value, "❓")
                
                # Короткий идентификатор (последние 4 символа UUID в верхнем регистре)
                short_id = str(ticket.ticket_id)[-4:].upper()
                
                # Дата создания
                date_str = ""
                if ticket.created_at:
                    date_str = ticket.created_at.strftime("%d.%m")
                
                # Текст кнопки
                label = f"{status_emoji} #{short_id}"
                if date_str:
                    label += f" от {date_str}"
                
                # Создаем кнопку тикета
                current_row.append(
                    VkButton(
                        label=label,
                        payload={"cmd": f"{USER_TICKET_DETAILS_PREFIX}{ticket.ticket_id}"},
                    )
                )
                
                # Если в строке накопилось 2 кнопки или это последний тикет
                if len(current_row) == 2:
                    ticket_rows.append(tuple(current_row))
                    current_row = []
            
            # Добавляем оставшиеся кнопки
            if current_row:
                ticket_rows.append(tuple(current_row))
            
            # Добавляем строки с тикетами в общий список
            rows.extend(ticket_rows)
        
        # Кнопка создания нового тикета (после списка тикетов)
        if has_tickets:
            rows.append((
                VkButton(
                    label="📝 Создать новый тикет",
                    payload={"cmd": GuestMenuAction.SUPPORT_QUESTION_FROM_LIST.value},
                ),
            ))
        
        # Кнопки навигации (только если больше одной страницы)
        nav_buttons = []
        if total_pages > 1:
            if current_page > 1:
                nav_buttons.append(
                    VkButton(
                        label="◀️ Назад",
                        payload={"cmd": f"{USER_TICKETS_PREV_PAGE_PREFIX}{current_page - 1}"},
                    )
                )
            
            nav_buttons.append(
                VkButton(
                    label=f"{current_page}/{total_pages}",
                    payload={"cmd": "noop"},  # Неактивная кнопка
                )
            )
            
            if current_page < total_pages:
                nav_buttons.append(
                    VkButton(
                        label="Вперед ▶️",
                        payload={"cmd": f"{USER_TICKETS_NEXT_PAGE_PREFIX}{current_page + 1}"},
                    )
                )
        
        # Навигация (после кнопки создания)
        if nav_buttons:
            rows.append(tuple(nav_buttons))
        
        # Кнопка возврата в главное меню
        rows.append((
            VkButton(
                label="🏠 Назад в меню",
                payload={"cmd": GuestMenuAction.BACK_TO_MAIN.value},
            ),
        ))
        
        return VkScreen(
            screen_id="user_tickets_pagination",
            text="",  # Текст будет добавлен отдельно
            rows=tuple(rows),
        )

    def resolve_action_screen(
        self,
        action: GuestMenuAction,
        *,
        user_name: str = "Гость",
        has_tickets: bool = False,
    ) -> VkScreen:
        """Возвращает соответствующий экран по действию меню."""

        if action in {GuestMenuAction.MAIN_MENU, GuestMenuAction.BACK_TO_MAIN}:
            return self.build_main_menu_screen(user_name=user_name)
        if action in {GuestMenuAction.SUPPORT, GuestMenuAction.BACK_TO_SUPPORT}:
            return self.build_support_menu_screen(has_tickets=has_tickets)
        if action == GuestMenuAction.HELP:
            return self.build_help_screen()
        if action == GuestMenuAction.ABOUT:
            return self.build_about_screen()
        if action == GuestMenuAction.VACANCIES:
            return self.build_vacancies_screen()
        if action == GuestMenuAction.DELIVERY:
            return self.build_delivery_screen()
        if action == GuestMenuAction.SUPPORT_FEEDBACK:
            return self.build_support_feedback_screen()
        if action == GuestMenuAction.SUPPORT_QUESTION:
            return self.build_support_question_screen()
        if action == GuestMenuAction.SUPPORT_CONTACTS:
            return self.build_support_contacts_screen()
        if action == GuestMenuAction.PROFILE:
            # Пока возвращаем главное меню, так как профиль требует данных пользователя
            return self.build_main_menu_screen(user_name=user_name)
        if action == GuestMenuAction.BALANCE:
            # Возвращаем экран баланса с фиктивным значением (позже будет передаваться реальный баланс)
            return self.build_balance_screen(balance=0.0)
        if action == GuestMenuAction.RETRY_IIKO_SYNC:
            return self.build_iiko_sync_retry_screen()
        return self.build_main_menu_screen(user_name=user_name)
