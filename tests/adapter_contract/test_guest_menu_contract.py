"""Контрактные тесты согласованности меню между Telegram/VK/MAX."""

from __future__ import annotations

from types import TracebackType

from vtelemax.adapters.max import MaxGuestMenuAdapter, MaxIdentityAdapter, MaxButton
from vtelemax.adapters.telegram import TelegramIdentityAdapter
from vtelemax.adapters.vk import VkGuestMenuAdapter, VkIdentityAdapter, VkButton
from vtelemax.core import (
    GetPersonByAccountTransactionalUseCase,
    GuestMenuAction,
    IdentityRepository,
    IdentityUnitOfWork,
    InMemoryIdentityRepository,
    RegisterOrAttachAccountTransactionalUseCase,
    build_main_menu_screen,
    build_start_contact_screen,
    build_start_rules_screen,
    build_support_menu_screen,
)


class InMemoryIdentityUnitOfWork(IdentityUnitOfWork):
    """Тестовый UnitOfWork поверх in-memory репозитория."""

    def __init__(self, repository: IdentityRepository) -> None:
        self.identity_repository = repository

    def __enter__(self) -> "InMemoryIdentityUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return

    def commit(self) -> None:
        return

    def rollback(self) -> None:
        return


def _build_adapters() -> tuple[TelegramIdentityAdapter, VkIdentityAdapter, MaxIdentityAdapter]:
    repository = InMemoryIdentityRepository()
    registration_use_case = RegisterOrAttachAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    lookup_use_case = GetPersonByAccountTransactionalUseCase(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(repository)
    )
    return (
        TelegramIdentityAdapter(registration_use_case, lookup_use_case),
        VkIdentityAdapter(registration_use_case, lookup_use_case),
        MaxIdentityAdapter(registration_use_case, lookup_use_case),
    )


def _flatten_rows(rows: tuple[tuple[object, ...], ...]) -> list[object]:
    return [button for row in rows for button in row]


def _complete_cross_platform_registration(
    telegram: TelegramIdentityAdapter,
    vk: VkIdentityAdapter,
    max_adapter: MaxIdentityAdapter,
) -> None:
    telegram.register_contact(telegram_user_id=1001, raw_phone="+79123456789")

    vk.handle_start(vk_user_id=2002)
    vk.handle_incoming(vk_user_id=2002, text="✅ Согласен", payload=None)
    vk.handle_incoming(vk_user_id=2002, text="+79123456789", payload=None)
    vk.handle_incoming(vk_user_id=2002, text="Иван", payload=None)
    vk.handle_incoming(vk_user_id=2002, text="Да", payload=None)

    max_adapter.handle_start(max_user_id=3003)
    max_adapter.handle_incoming(max_user_id=3003, text="✅ Согласен", payload=None)
    max_adapter.handle_incoming(max_user_id=3003, text="+79123456789", payload=None)
    max_adapter.handle_incoming(max_user_id=3003, text="Иван", payload=None)
    max_adapter.handle_incoming(max_user_id=3003, text="Да", payload=None)


def test_main_menu_labels_are_identical_between_core_vk_max() -> None:
    """Проверяет единый набор кнопок главного меню."""

    core_labels = [button.label for button in build_main_menu_screen().buttons]

    vk_screen = VkGuestMenuAdapter().build_main_menu_screen(user_name="Гость")
    max_screen = MaxGuestMenuAdapter().build_main_menu_screen(user_name="Гость")
    vk_labels = [button.label for button in _flatten_rows(vk_screen.rows)]
    max_labels = [button.label for button in _flatten_rows(max_screen.rows)]

    assert vk_labels == core_labels
    assert max_labels == core_labels


def test_support_menu_labels_are_identical_without_tickets() -> None:
    """Проверяет единый набор кнопок раздела поддержки без тикетов."""

    core_labels = [button.label for button in build_support_menu_screen(has_tickets=False).buttons]

    vk_screen = VkGuestMenuAdapter().build_support_menu_screen(has_tickets=False)
    max_screen = MaxGuestMenuAdapter().build_support_menu_screen(has_tickets=False)
    vk_labels = [button.label for button in _flatten_rows(vk_screen.rows)]
    max_labels = [button.label for button in _flatten_rows(max_screen.rows)]

    assert vk_labels == core_labels
    assert max_labels == core_labels


def test_profile_phone_is_consistent_for_telegram_vk_max() -> None:
    """Проверяет, что все адаптеры показывают один и тот же телефон профиля."""

    telegram, vk, max_adapter = _build_adapters()
    _complete_cross_platform_registration(telegram, vk, max_adapter)

    telegram_profile = telegram.handle_menu_action(telegram_user_id=1001, action_text="👤 Профиль")
    vk_profile = vk.handle_incoming(vk_user_id=2002, text="👤 Профиль", payload=None)
    max_profile = max_adapter.handle_incoming(max_user_id=3003, text="👤 Профиль", payload=None)

    assert "+79123456789" in telegram_profile.message
    assert "+79123456789" in vk_profile.text
    assert "+79123456789" in max_profile.text
    assert "Привязанных аккаунтов" in telegram_profile.message and "3" in telegram_profile.message
    assert "Привязанных аккаунтов" in vk_profile.text and "3" in vk_profile.text
    assert "Привязанных аккаунтов" in max_profile.text and "3" in max_profile.text


def test_unknown_action_is_reported_consistently_for_registered_users() -> None:
    """Проверяет единый префикс ошибки для неизвестной команды."""

    telegram, vk, max_adapter = _build_adapters()
    _complete_cross_platform_registration(telegram, vk, max_adapter)

    telegram_result = telegram.handle_menu_action(telegram_user_id=1001, action_text="случайная_команда")
    vk_result = vk.handle_incoming(vk_user_id=2002, text="случайная_команда", payload=None)
    max_result = max_adapter.handle_incoming(max_user_id=3003, text="случайная_команда", payload=None)

    assert "Команда не распознана" in telegram_result.message
    assert "Команда не распознана" in vk_result.text
    assert "Команда не распознана" in max_result.text


def test_url_button_present_in_rules_screen() -> None:
    """Проверяет, что кнопка «Документы» имеет URL во всех адаптерах."""
    vk_adapter = VkGuestMenuAdapter()
    max_adapter = MaxGuestMenuAdapter()

    vk_screen = vk_adapter.build_start_rules_screen()
    max_screen = max_adapter.build_start_rules_screen()

    # В экране правил две вертикальные кнопки: первая — URL, вторая — callback
    vk_url_button = vk_screen.rows[0][0]
    max_url_button = max_screen.rows[0][0]

    assert vk_url_button.url is not None
    assert max_url_button.url is not None
    assert vk_url_button.url == max_url_button.url  # URL должны совпадать

    # Проверяем, что вторая кнопка не имеет URL
    vk_callback_button = vk_screen.rows[1][0]
    max_callback_button = max_screen.rows[1][0]
    assert vk_callback_button.url is None
    assert max_callback_button.url is None
    # В MAX кнопка «Согласен» — обычный callback (request_contact только у шага телефона)
    assert max_callback_button.request_contact is False


def test_request_contact_button_present_in_contact_screen() -> None:
    """Проверяет, что кнопка «Поделиться контактом» имеет request_contact в MAX и отсутствие URL в VK."""
    vk_adapter = VkGuestMenuAdapter()
    max_adapter = MaxGuestMenuAdapter()

    vk_screen = vk_adapter.build_start_contact_screen()
    max_screen = max_adapter.build_start_contact_screen()

    # В экране контакта одна кнопка
    vk_button = vk_screen.rows[0][0]
    max_button = max_screen.rows[0][0]

    # В VK кнопка должна быть обычной (без URL и request_contact)
    assert vk_button.url is None
    # В MAX кнопка должна иметь request_contact = True
    assert max_button.request_contact is True
    assert max_button.url is None
    # Действие кнопки — SHARE_CONTACT
    # (можно проверить через payload, но это уже проверяется в других тестах)


def test_callback_buttons_have_no_url_or_request_contact() -> None:
    """Проверяет, что кнопки главного меню не имеют лишних полей (только callback)."""
    vk_adapter = VkGuestMenuAdapter()
    max_adapter = MaxGuestMenuAdapter()

    vk_screen = vk_adapter.build_main_menu_screen()
    max_screen = max_adapter.build_main_menu_screen()

    for vk_row, max_row in zip(vk_screen.rows, max_screen.rows):
        for vk_button, max_button in zip(vk_row, max_row):
            assert vk_button.url is None
            assert max_button.url is None
            assert max_button.request_contact is False


def test_onboarding_flow_transitions() -> None:
    """Проверяет корректность переходов между экранами в процессе регистрации."""
    telegram, vk, max_adapter = _build_adapters()

    # Шаг 1: старт -> экран правил
    vk_start = vk.handle_start(vk_user_id=2002)
    assert vk_start.screen is not None
    assert vk_start.screen.screen_id == "start_rules"
    max_start = max_adapter.handle_start(max_user_id=3003)
    assert max_start.screen is not None
    assert max_start.screen.screen_id == "start_rules"

    # Шаг 2: принятие правил -> экран телефона
    vk_accept = vk.handle_incoming(vk_user_id=2002, text="✅ Согласен", payload=None)
    assert vk_accept.screen is not None
    assert vk_accept.screen.screen_id == "start_contact"
    max_accept = max_adapter.handle_incoming(max_user_id=3003, text="✅ Согласен", payload=None)
    assert max_accept.screen is not None
    assert max_accept.screen.screen_id == "start_contact"

    # Шаг 3: отправка телефона -> шаг имени
    vk_phone = vk.handle_incoming(vk_user_id=2002, text="+79123456789", payload=None)
    assert vk_phone.screen is None
    assert "имя" in vk_phone.text.lower()
    max_phone = max_adapter.handle_incoming(max_user_id=3003, text="+79123456789", payload=None)
    assert max_phone.screen is None
    assert "имя" in max_phone.text.lower()

    # Шаг 4: имя -> экран согласия на рассылку
    vk_name = vk.handle_incoming(vk_user_id=2002, text="Иван", payload=None)
    assert vk_name.screen is not None
    assert vk_name.screen.screen_id == "notifications_consent"
    max_name = max_adapter.handle_incoming(max_user_id=3003, text="Иван", payload=None)
    assert max_name.screen is not None
    assert max_name.screen.screen_id == "notifications_consent"

    # Шаг 5: выбор по рассылке -> главное меню
    vk_notify = vk.handle_incoming(vk_user_id=2002, text="Да", payload=None)
    assert vk_notify.screen is not None
    assert vk_notify.screen.screen_id == "main_menu"
    max_notify = max_adapter.handle_incoming(max_user_id=3003, text="Да", payload=None)
    assert max_notify.screen is not None
    assert max_notify.screen.screen_id == "main_menu"


def test_invalid_phone_returns_error() -> None:
    """Проверяет, что невалидный номер телефона возвращает ошибку и остаётся на экране контакта."""
    telegram, vk, max_adapter = _build_adapters()

    # Пройти шаг правил
    vk.handle_start(vk_user_id=2002)
    vk.handle_incoming(vk_user_id=2002, text="✅ Согласен", payload=None)
    max_adapter.handle_start(max_user_id=3003)
    max_adapter.handle_incoming(max_user_id=3003, text="✅ Согласен", payload=None)

    # Отправить невалидный номер (не цифры)
    vk_response = vk.handle_incoming(vk_user_id=2002, text="abc", payload=None)
    max_response = max_adapter.handle_incoming(max_user_id=3003, text="abc", payload=None)

    # Проверяем, что screen остался start_contact
    assert vk_response.screen is not None
    assert vk_response.screen.screen_id == "start_contact"
    assert max_response.screen is not None
    assert max_response.screen.screen_id == "start_contact"
    # Проверяем, что текст содержит сообщение об ошибке
    assert "Не удалось обработать номер телефона" in vk_response.text
    assert "Не удалось обработать номер телефона" in max_response.text

