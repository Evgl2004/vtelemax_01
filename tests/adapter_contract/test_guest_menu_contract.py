"""Contract tests for aligned menu behavior across Telegram, VK and MAX adapters."""

from __future__ import annotations

from collections import Counter
from types import TracebackType

from vtelemax.adapters.max import MaxButton, MaxGuestMenuAdapter, MaxIdentityAdapter
from vtelemax.adapters.telegram import TelegramIdentityAdapter
from vtelemax.adapters.vk import VkButton, VkGuestMenuAdapter, VkIdentityAdapter
from vtelemax.core import (
    GetPersonByAccountTransactionalUseCase,
    GuestMenuAction,
    IdentityRepository,
    IdentityUnitOfWork,
    InMemoryIdentityRepository,
    RegisterOrAttachAccountTransactionalUseCase,
    build_main_menu_screen,
    build_start_rules_screen,
    build_support_menu_screen,
)


class InMemoryIdentityUnitOfWork(IdentityUnitOfWork):
    """Test UnitOfWork over in-memory repository."""

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
    vk.handle_incoming(vk_user_id=2002, text="", payload={"cmd": GuestMenuAction.ACCEPT_RULES.value})
    vk.handle_incoming(vk_user_id=2002, text="+79123456789", payload=None)
    vk.handle_incoming(vk_user_id=2002, text="Ivan", payload=None)
    vk.handle_incoming(vk_user_id=2002, text="", payload={"cmd": GuestMenuAction.NOTIFY_YES.value})

    max_adapter.handle_start(max_user_id=3003)
    max_adapter.handle_incoming(max_user_id=3003, text="", payload=GuestMenuAction.ACCEPT_RULES.value)
    max_adapter.handle_incoming(max_user_id=3003, text="", payload=None, contact_phone="+79123456789")
    max_adapter.handle_incoming(max_user_id=3003, text="Ivan", payload=None)
    max_adapter.handle_incoming(max_user_id=3003, text="", payload=GuestMenuAction.NOTIFY_YES.value)


def test_main_menu_labels_are_identical_between_core_vk_max() -> None:
    """Main menu labels should stay aligned across core/VK/MAX."""

    core_labels = [button.label for button in build_main_menu_screen().buttons]

    vk_screen = VkGuestMenuAdapter().build_main_menu_screen(user_name="Guest")
    max_screen = MaxGuestMenuAdapter().build_main_menu_screen(user_name="Guest")
    vk_labels = [button.label for button in _flatten_rows(vk_screen.rows)]
    max_labels = [button.label for button in _flatten_rows(max_screen.rows)]

    # VK и MAX могут группировать строки платформенно (в рамках UX/ограничений SDK).
    # Контракт здесь — паритет доступных пунктов меню, а не строгий порядок.
    assert Counter(vk_labels) == Counter(core_labels)
    assert Counter(max_labels) == Counter(core_labels)


def test_support_menu_labels_are_identical_without_tickets() -> None:
    """Support menu labels should stay aligned when user has no tickets."""

    core_labels = [button.label for button in build_support_menu_screen(has_tickets=False).buttons]

    vk_screen = VkGuestMenuAdapter().build_support_menu_screen(has_tickets=False)
    max_screen = MaxGuestMenuAdapter().build_support_menu_screen(has_tickets=False)
    vk_labels = [button.label for button in _flatten_rows(vk_screen.rows)]
    max_labels = [button.label for button in _flatten_rows(max_screen.rows)]

    assert vk_labels == core_labels
    assert max_labels == core_labels


def test_profile_phone_is_consistent_for_telegram_vk_max() -> None:
    """All adapters should expose the same registered phone in profile view."""

    telegram, vk, max_adapter = _build_adapters()
    _complete_cross_platform_registration(telegram, vk, max_adapter)

    telegram_profile = telegram.handle_menu_action(telegram_user_id=1001, action_text="👤 Профиль")
    vk_profile = vk.handle_incoming(vk_user_id=2002, text="", payload={"cmd": GuestMenuAction.PROFILE.value})
    max_profile = max_adapter.handle_incoming(
        max_user_id=3003, text="", payload=GuestMenuAction.PROFILE.value
    )

    assert telegram_profile.status == "profile"
    assert vk_profile.screen is not None and vk_profile.screen.screen_id == "profile"
    assert max_profile.screen is not None and max_profile.screen.screen_id == "profile"
    assert "+79123456789" in telegram_profile.message
    assert "+79123456789" in vk_profile.text
    assert "+79123456789" in max_profile.text


def test_unknown_action_is_reported_consistently_for_registered_users() -> None:
    """Unknown action should keep users in a safe menu state on each platform."""

    telegram, vk, max_adapter = _build_adapters()
    _complete_cross_platform_registration(telegram, vk, max_adapter)

    telegram_result = telegram.handle_menu_action(telegram_user_id=1001, action_text="random_unknown_command")
    vk_result = vk.handle_incoming(vk_user_id=2002, text="random_unknown_command", payload=None)
    max_result = max_adapter.handle_incoming(max_user_id=3003, text="random_unknown_command", payload=None)

    assert telegram_result.status == "unknown_action"
    assert vk_result.screen is not None and vk_result.screen.screen_id == "main_menu"
    assert max_result.screen is not None and max_result.screen.screen_id == "main_menu"


def test_rules_screen_has_expected_inline_buttons() -> None:
    """Rules screen should keep parity with core contract for VK and MAX."""

    vk_adapter = VkGuestMenuAdapter()
    max_adapter = MaxGuestMenuAdapter()
    core_screen = build_start_rules_screen()

    vk_screen = vk_adapter.build_start_rules_screen()
    max_screen = max_adapter.build_start_rules_screen()

    assert len(vk_screen.rows) == len(core_screen.buttons)
    assert len(max_screen.rows) == len(core_screen.buttons)

    for index, core_button in enumerate(core_screen.buttons):
        vk_button = vk_screen.rows[index][0]
        assert isinstance(vk_button, VkButton)
        assert vk_button.label == core_button.label
        assert vk_button.payload.get("cmd") == core_button.action.value
        if index == len(core_screen.buttons) - 1:
            assert vk_button.url is None
        else:
            assert vk_button.url is not None

    for index, core_button in enumerate(core_screen.buttons):
        max_button = max_screen.rows[index][0]
        assert isinstance(max_button, MaxButton)
        assert max_button.label == core_button.label
        assert max_button.payload == core_button.action.value
        if index == len(core_screen.buttons) - 1:
            assert max_button.url is None
        else:
            assert max_button.url is not None


def test_contact_screen_buttons_are_platform_specific() -> None:
    """VK keeps manual input, MAX keeps request_contact button."""

    vk_adapter = VkGuestMenuAdapter()
    max_adapter = MaxGuestMenuAdapter()

    vk_screen = vk_adapter.build_start_contact_screen()
    max_screen = max_adapter.build_start_contact_screen()

    assert vk_screen.rows == ()
    assert len(max_screen.rows) == 1
    assert isinstance(max_screen.rows[0][0], MaxButton)
    assert max_screen.rows[0][0].request_contact is True
    assert max_screen.rows[0][0].payload == GuestMenuAction.SHARE_CONTACT.value


def test_callback_buttons_have_no_url_or_request_contact() -> None:
    """Main menu buttons should match URL/request_contact contract from core."""

    vk_adapter = VkGuestMenuAdapter()
    max_adapter = MaxGuestMenuAdapter()
    core_screen = build_main_menu_screen()
    expected_url_by_label = {button.label: button.url for button in core_screen.buttons}

    vk_screen = vk_adapter.build_main_menu_screen()
    max_screen = max_adapter.build_main_menu_screen()

    for vk_button in _flatten_rows(vk_screen.rows):
        assert vk_button.url == expected_url_by_label[vk_button.label]

    for max_button in _flatten_rows(max_screen.rows):
        assert max_button.url == expected_url_by_label[max_button.label]
        assert max_button.request_contact is False


def test_onboarding_flow_transitions() -> None:
    """Onboarding transitions should keep expected screen order."""

    _, vk, max_adapter = _build_adapters()

    vk_start = vk.handle_start(vk_user_id=2002)
    assert vk_start.screen is not None
    assert vk_start.screen.screen_id == "start_rules"
    max_start = max_adapter.handle_start(max_user_id=3003)
    assert max_start.screen is not None
    assert max_start.screen.screen_id == "start_rules"

    vk_accept = vk.handle_incoming(
        vk_user_id=2002,
        text="",
        payload={"cmd": GuestMenuAction.ACCEPT_RULES.value},
    )
    assert vk_accept.screen is not None
    assert vk_accept.screen.screen_id == "start_contact"
    max_accept = max_adapter.handle_incoming(
        max_user_id=3003,
        text="",
        payload=GuestMenuAction.ACCEPT_RULES.value,
    )
    assert max_accept.screen is not None
    assert max_accept.screen.screen_id == "start_contact"

    vk_phone = vk.handle_incoming(vk_user_id=2002, text="+79123456789", payload=None)
    assert vk_phone.screen is None
    assert "имя" in vk_phone.text.lower()
    max_phone = max_adapter.handle_incoming(max_user_id=3003, text="", payload=None, contact_phone="+79123456789")
    assert max_phone.screen is None
    assert "имя" in max_phone.text.lower()

    vk_name = vk.handle_incoming(vk_user_id=2002, text="Ivan", payload=None)
    assert vk_name.screen is not None
    assert vk_name.screen.screen_id == "notifications_consent"
    max_name = max_adapter.handle_incoming(max_user_id=3003, text="Ivan", payload=None)
    assert max_name.screen is not None
    assert max_name.screen.screen_id == "notifications_consent"

    vk_notify = vk.handle_incoming(
        vk_user_id=2002,
        text="",
        payload={"cmd": GuestMenuAction.NOTIFY_YES.value},
    )
    assert vk_notify.screen is not None
    assert vk_notify.screen.screen_id == "main_menu"
    max_notify = max_adapter.handle_incoming(
        max_user_id=3003,
        text="",
        payload=GuestMenuAction.NOTIFY_YES.value,
    )
    assert max_notify.screen is not None
    assert max_notify.screen.screen_id == "main_menu"


def test_invalid_phone_returns_error() -> None:
    """Invalid phone should keep user on contact step and return validation error."""

    _, vk, max_adapter = _build_adapters()

    vk.handle_start(vk_user_id=2002)
    vk.handle_incoming(vk_user_id=2002, text="", payload={"cmd": GuestMenuAction.ACCEPT_RULES.value})
    max_adapter.handle_start(max_user_id=3003)
    max_adapter.handle_incoming(max_user_id=3003, text="", payload=GuestMenuAction.ACCEPT_RULES.value)

    vk_response = vk.handle_incoming(vk_user_id=2002, text="abc", payload=None)
    max_response = max_adapter.handle_incoming(max_user_id=3003, text="abc", payload=None)

    assert vk_response.screen is not None
    assert vk_response.screen.screen_id == "start_contact"
    assert max_response.screen is not None
    assert max_response.screen.screen_id == "start_contact"
    assert "+79991234567" in vk_response.text
    assert "Поделиться контактом" in max_response.text
