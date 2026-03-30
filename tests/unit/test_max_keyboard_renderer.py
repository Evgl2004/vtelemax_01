"""Тесты рендера MAX-клавиатур."""

from __future__ import annotations

from vtelemax.adapters.max import MaxGuestMenuAdapter, render_max_keyboard


def test_render_max_keyboard_returns_markup_or_fallback_for_screen_with_buttons() -> None:
    """Проверяет, что экран с кнопками рендерится в клавиатуру."""

    adapter = MaxGuestMenuAdapter()
    screen = adapter.build_main_menu_screen(user_name="Гость")

    keyboard = render_max_keyboard(screen)

    assert keyboard is not None


def test_render_max_keyboard_returns_none_for_screen_without_buttons() -> None:
    """Проверяет отсутствие клавиатуры для экранов без кнопок."""

    adapter = MaxGuestMenuAdapter()
    screen = adapter.build_help_screen()

    keyboard = render_max_keyboard(screen)

    assert keyboard is None


def test_render_max_keyboard_returns_none_for_start_rules_in_temporary_text_mode() -> None:
    """Проверяет, что для onboarding-экрана правил клавиатура временно не рендерится."""

    adapter = MaxGuestMenuAdapter()
    screen = adapter.build_start_rules_screen()

    keyboard = render_max_keyboard(screen)

    assert keyboard is None
