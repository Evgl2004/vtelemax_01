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


def test_render_max_keyboard_handles_url_button() -> None:
    """Проверяет рендер кнопки-ссылки (URL)."""

    adapter = MaxGuestMenuAdapter()
    screen = adapter.build_start_rules_screen()

    keyboard = render_max_keyboard(screen)

    assert keyboard is not None
    # В тестовом окружении (без maxapi) возвращается словарь с полем url
    # Проверим, что в структуре есть url
    if isinstance(keyboard, dict):
        rows = keyboard.get("rows", [])
        assert len(rows) == 1
        row = rows[0]
        assert len(row) == 2
        # Первая кнопка — ссылка на документы
        assert row[0].get("url") is not None
        # Вторая кнопка — обычная кнопка (без url)
        assert row[1].get("url") is None
    else:
        # В реальном окружении с maxapi клавиатура будет объектом InlineKeyboardMarkup
        # Проверим, что функция не падает
        pass
