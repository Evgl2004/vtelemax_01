"""Стартовый VK-адаптер меню на едином контракте core."""

from __future__ import annotations

from dataclasses import dataclass

from vtelemax.core import (
    GuestMenuAction,
    MenuButtonContract,
    build_about_screen,
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

from .payloads import build_vk_payload


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

        screen = build_start_rules_screen()
        rows = ((_to_vk_button(screen.buttons[0]), _to_vk_button(screen.buttons[1])),) if screen.buttons else ()
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_start_contact_screen(self) -> VkScreen:
        """Экран запроса телефона."""

        screen = build_start_contact_screen()
        rows = ((_to_vk_button(screen.buttons[0]),),) if screen.buttons else ()
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

    def build_main_menu_screen(self, user_name: str = "Гость") -> VkScreen:
        """Главное меню гостя (кнопки как в прототипах)."""

        screen = build_main_menu_screen(user_name=user_name)
        rows = (
            (_to_vk_button(screen.buttons[0]),),
            (_to_vk_button(screen.buttons[1]),),
            (_to_vk_button(screen.buttons[2]),),
            (_to_vk_button(screen.buttons[3]),),
            (_to_vk_button(screen.buttons[4]), _to_vk_button(screen.buttons[5])),
            (_to_vk_button(screen.buttons[6]), _to_vk_button(screen.buttons[7])),
        )
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

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

    def build_profile_screen(self, phone_e164: str, accounts_count: int) -> VkScreen:
        """Экран профиля зарегистрированного пользователя."""

        screen = build_profile_screen(phone_e164=phone_e164, accounts_count=accounts_count)
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=())

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

    def build_support_feedback_screen(self) -> VkScreen:
        """Экран обратной связи."""

        screen = build_support_feedback_screen()
        rows = ((_to_vk_button(screen.buttons[0]),),) if screen.buttons else ()
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

    def build_support_contacts_screen(self) -> VkScreen:
        """Экран контактов."""

        screen = build_support_contacts_screen()
        rows = ((_to_vk_button(screen.buttons[0]),),) if screen.buttons else ()
        return VkScreen(screen_id=screen.screen_id, text=screen.text, rows=rows)

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
        if action == GuestMenuAction.SUPPORT_FEEDBACK:
            return self.build_support_feedback_screen()
        if action == GuestMenuAction.SUPPORT_QUESTION:
            return self.build_support_question_screen()
        if action == GuestMenuAction.SUPPORT_CONTACTS:
            return self.build_support_contacts_screen()
        return self.build_main_menu_screen(user_name=user_name)
