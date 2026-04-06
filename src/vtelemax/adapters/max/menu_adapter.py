"""MAX-адаптер меню на едином контракте core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from vtelemax.core import (
    GuestMenuAction,
    MenuButtonContract,
    PersonSupportTicketSummary,
    BUTTON_MY_TICKETS,
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

from .payloads import build_max_payload

# Префиксы callback'ов пагинации тикетов (аналогично Telegram и VK)
USER_TICKETS_PREV_PAGE_PREFIX = "user_tickets_prev_"
USER_TICKETS_NEXT_PAGE_PREFIX = "user_tickets_next_"
USER_TICKET_DETAILS_PREFIX = "user_ticket_"


@dataclass(frozen=True, slots=True)
class MaxButton:
    """Унифицированная кнопка MAX для дальнейшего рендера в maxapi."""

    label: str
    payload: str
    url: str | None = None
    request_contact: bool = False


@dataclass(frozen=True, slots=True)
class MaxScreen:
    """Унифицированный экран ответа MAX-адаптера."""

    screen_id: str
    text: str
    rows: tuple[tuple[MaxButton, ...], ...]
    parse_mode: str | None = None


def _to_max_button(button: MenuButtonContract) -> MaxButton:
    return MaxButton(
        label=button.label,
        payload=build_max_payload(button.action),
        url=button.url,
        request_contact=(button.action == GuestMenuAction.SHARE_CONTACT),
    )


class MaxGuestMenuAdapter:
    """Преобразует core-контент в формат MAX-экрана."""

    def build_start_rules_screen(self) -> MaxScreen:
        """Стартовый экран правил."""

        screen = build_start_rules_screen(platform="max")
        rows = tuple((_to_max_button(button),) for button in screen.buttons)
        return MaxScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_start_contact_screen(self) -> MaxScreen:
        """Экран запроса телефона."""

        screen = build_start_contact_screen(platform="max")
        rows = ((_to_max_button(screen.buttons[0]),),) if screen.buttons else ()
        return MaxScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_main_menu_screen(self, user_name: str = "Гость") -> MaxScreen:
        """Главное меню гостя (пять разделов, вертикальный список)."""

        screen = build_main_menu_screen(user_name=user_name)
        rows = tuple((_to_max_button(button),) for button in screen.buttons)
        return MaxScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_support_menu_screen(self, has_tickets: bool) -> MaxScreen:
        """Экран поддержки с условной кнопкой «Мои обращения»."""

        screen = build_support_menu_screen(has_tickets=has_tickets)
        buttons = [_to_max_button(button) for button in screen.buttons]
        rows = tuple((button,) for button in buttons)
        return MaxScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="markdown" if screen.parse_mode == "markdown" else None,
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
    ) -> MaxScreen:
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
        rows = tuple((_to_max_button(button),) for button in screen.buttons)
        return MaxScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_profile_edit_screen(self, *, can_edit_birth_date: bool) -> MaxScreen:
        """Экран выбора поля для редактирования профиля."""

        screen = build_profile_edit_screen(can_edit_birth_date=can_edit_birth_date)
        rows = tuple((_to_max_button(button),) for button in screen.buttons)
        return MaxScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_profile_gender_screen(self) -> MaxScreen:
        """Экран выбора пола в режиме редактирования профиля."""

        screen = build_profile_gender_screen()
        rows = tuple((_to_max_button(button),) for button in screen.buttons)
        return MaxScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_notifications_consent_screen(self, profile_text: str | None = None) -> MaxScreen:
        """Экран согласия на рассылку после review-анкеты."""

        screen = build_notifications_consent_screen(profile_text=profile_text, platform="max")
        rows = tuple((_to_max_button(button),) for button in screen.buttons)
        return MaxScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_balance_screen(self, balance: float) -> MaxScreen:
        """Экран бонусного баланса."""

        screen = build_balance_screen(balance=balance)
        rows = ((_to_max_button(screen.buttons[0]),),) if screen.buttons else ()
        return MaxScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="markdown" if screen.parse_mode == "markdown" else None,
        )
    def build_profile_not_found_screen(self) -> MaxScreen:
        """Экран незарегистрированного пользователя."""

        screen = build_profile_not_found_screen()
        rows = ((_to_max_button(screen.buttons[0]),),) if screen.buttons else ()
        return MaxScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_help_screen(self) -> MaxScreen:
        """Экран справки."""

        screen = build_help_screen()
        return MaxScreen(screen_id=screen.screen_id, text=screen.text, rows=())

    def build_about_screen(self) -> MaxScreen:
        """Экран «О проекте»."""

        screen = build_about_screen()
        return MaxScreen(screen_id=screen.screen_id, text=screen.text, rows=())

    def build_vacancies_screen(self) -> MaxScreen:
        """Экран вакансий."""

        screen = build_vacancies_screen()
        rows = ((_to_max_button(screen.buttons[0]),),) if screen.buttons else ()
        return MaxScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_delivery_screen(self) -> MaxScreen:
        """Экран подменю «Доставка» со ссылками на заведения."""

        screen = build_delivery_screen()
        rows = tuple((_to_max_button(button),) for button in screen.buttons)
        return MaxScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_support_feedback_screen(self) -> MaxScreen:
        """Экран обратной связи."""

        screen = build_support_feedback_screen()
        rows = tuple((_to_max_button(button),) for button in screen.buttons)
        return MaxScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_support_question_screen(self) -> MaxScreen:
        """Экран создания обращения."""

        screen = build_support_question_screen()
        rows = (
            (
                MaxButton(
                    label=BUTTON_MY_TICKETS,
                    payload=build_max_payload(GuestMenuAction.MY_TICKETS),
                ),
            ),
        )
        return MaxScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_support_question_confirmation_screen(self) -> MaxScreen:
        """Экран подтверждения создания тикета (после отправки вопроса)."""

        screen = build_support_question_confirmation_screen()
        rows = tuple((_to_max_button(button),) for button in screen.buttons)
        return MaxScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_support_contacts_screen(self) -> MaxScreen:
        """Экран контактов."""

        screen = build_support_contacts_screen()
        rows = ((_to_max_button(screen.buttons[0]),),) if screen.buttons else ()
        return MaxScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_virtual_card_result_screen(self) -> MaxScreen:
        """Экран после отправки QR-кодов виртуальной карты."""

        screen = build_virtual_card_result_screen()
        rows = tuple((_to_max_button(button),) for button in screen.buttons)
        return MaxScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_iiko_sync_retry_screen(self) -> MaxScreen:
        """Экран повторной синхронизации с iiko."""

        screen = build_iiko_sync_retry_screen()
        rows = tuple((_to_max_button(button),) for button in screen.buttons)
        return MaxScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_iiko_sync_pending_screen(self) -> MaxScreen:
        """Экран ожидания синхронизации с iiko."""

        screen = build_iiko_sync_pending_screen()
        return MaxScreen(screen_id=screen.screen_id, text=screen.text, rows=())

    def build_user_tickets_pagination_screen(
        self,
        current_page: int,
        total_pages: int,
        tickets: tuple[PersonSupportTicketSummary, ...] = (),
        has_tickets: bool = True,
    ) -> MaxScreen:
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
                    MaxButton(
                        label=label,
                        payload=f"{USER_TICKET_DETAILS_PREFIX}{ticket.ticket_id}",
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
                MaxButton(
                    label="📝 Создать новый тикет",
                    payload=build_max_payload(GuestMenuAction.SUPPORT_QUESTION_FROM_LIST),
                ),
            ))
        
        # Кнопки навигации (только если больше одной страницы)
        nav_buttons = []
        if total_pages > 1:
            if current_page > 1:
                nav_buttons.append(
                    MaxButton(
                        label="◀️ Назад",
                        payload=f"{USER_TICKETS_PREV_PAGE_PREFIX}{current_page - 1}",
                    )
                )
            
            nav_buttons.append(
                MaxButton(
                    label=f"{current_page}/{total_pages}",
                    payload="noop",  # Неактивная кнопка
                )
            )
            
            if current_page < total_pages:
                nav_buttons.append(
                    MaxButton(
                        label="Вперед ▶️",
                        payload=f"{USER_TICKETS_NEXT_PAGE_PREFIX}{current_page + 1}",
                    )
                )
        
        # Навигация (после кнопки создания)
        if nav_buttons:
            rows.append(tuple(nav_buttons))
        
        # Кнопка возврата в главное меню
        rows.append((
            MaxButton(
                label="🏠 Назад в меню",
                payload=build_max_payload(GuestMenuAction.BACK_TO_MAIN),
            ),
        ))
        
        return MaxScreen(
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
    ) -> MaxScreen:
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
