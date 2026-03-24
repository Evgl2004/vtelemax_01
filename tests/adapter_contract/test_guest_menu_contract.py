"""Контрактные тесты согласованности меню между Telegram/VK/MAX."""

from __future__ import annotations

from types import TracebackType

from vtelemax.adapters.max import MaxGuestMenuAdapter, MaxIdentityAdapter
from vtelemax.adapters.telegram import TelegramIdentityAdapter
from vtelemax.adapters.vk import VkGuestMenuAdapter, VkIdentityAdapter
from vtelemax.core import (
    GetPersonByAccountTransactionalUseCase,
    IdentityRepository,
    IdentityUnitOfWork,
    InMemoryIdentityRepository,
    RegisterOrAttachAccountTransactionalUseCase,
    build_main_menu_screen,
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

    max_adapter.handle_start(max_user_id=3003)
    max_adapter.handle_incoming(max_user_id=3003, text="✅ Согласен", payload=None)
    max_adapter.handle_incoming(max_user_id=3003, text="+79123456789", payload=None)


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

    telegram_profile = telegram.handle_menu_action(telegram_user_id=1001, action_text="Мой профиль")
    vk_profile = vk.handle_incoming(vk_user_id=2002, text="Мой профиль", payload=None)
    max_profile = max_adapter.handle_incoming(max_user_id=3003, text="Мой профиль", payload=None)

    assert "+79123456789" in telegram_profile.message
    assert "+79123456789" in vk_profile.text
    assert "+79123456789" in max_profile.text
    assert "Привязанных аккаунтов: 3" in telegram_profile.message
    assert "Привязанных аккаунтов: 3" in vk_profile.text
    assert "Привязанных аккаунтов: 3" in max_profile.text


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
