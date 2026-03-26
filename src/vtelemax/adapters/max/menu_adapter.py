"""MAX-адаптер меню на едином контракте core."""

from __future__ import annotations

from dataclasses import dataclass

from vtelemax.core import (
    GuestMenuAction,
    MenuButtonContract,
    build_about_screen,
    build_balance_screen,
    build_help_screen,
    build_main_menu_screen,
    build_profile_not_found_screen,
    build_profile_screen,
    build_start_contact_screen,
    build_start_rules_screen,
    build_support_contacts_screen,
    build_support_feedback_screen,
    build_support_menu_screen,
    build_support_question_screen,
    build_vacancies_screen,
)

from .payloads import build_max_payload


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

        screen = build_start_rules_screen()
        rows = ((_to_max_button(screen.buttons[0]), _to_max_button(screen.buttons[1])),) if screen.buttons else ()
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

    def build_profile_screen(self, phone_e164: str, accounts_count: int) -> MaxScreen:
        """Экран профиля зарегистрированного пользователя."""

        screen = build_profile_screen(phone_e164=phone_e164, accounts_count=accounts_count)
        return MaxScreen(screen_id=screen.screen_id, text=screen.text, rows=())

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

    def build_support_feedback_screen(self) -> MaxScreen:
        """Экран обратной связи."""

        screen = build_support_feedback_screen()
        rows = ((_to_max_button(screen.buttons[0]),),) if screen.buttons else ()
        return MaxScreen(
            screen_id=screen.screen_id,
            text=screen.text,
            rows=rows,
            parse_mode="markdown" if screen.parse_mode == "markdown" else None,
        )

    def build_support_question_screen(self) -> MaxScreen:
        """Экран создания обращения."""

        screen = build_support_question_screen()
        rows = ((_to_max_button(screen.buttons[0]),),) if screen.buttons else ()
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
        return self.build_main_menu_screen(user_name=user_name)
