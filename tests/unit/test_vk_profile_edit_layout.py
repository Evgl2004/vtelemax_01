"""VK profile edit layout tests."""

from __future__ import annotations

from vtelemax.adapters.vk import VkGuestMenuAdapter
from vtelemax.core import GuestMenuAction


def test_vk_profile_edit_screen_fits_vk_row_limit_when_birth_date_editable() -> None:
    """When birth date is editable, VK profile edit has exactly 6 rows."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_profile_edit_screen(can_edit_birth_date=True)

    assert len(screen.rows) <= 6
    assert len(screen.rows) == 6
    assert len(screen.rows[0]) == 2
    assert screen.rows[0][0].payload.get("cmd") == GuestMenuAction.PROFILE_EDIT_FIRST_NAME.value
    assert screen.rows[0][1].payload.get("cmd") == GuestMenuAction.PROFILE_EDIT_LAST_NAME.value
    assert screen.rows[1][0].payload.get("cmd") == GuestMenuAction.PROFILE_EDIT_GENDER.value
    assert screen.rows[2][0].payload.get("cmd") == GuestMenuAction.PROFILE_EDIT_BIRTH_DATE.value
    assert screen.rows[3][0].payload.get("cmd") == GuestMenuAction.PROFILE_EDIT_EMAIL.value
    assert screen.rows[4][0].payload.get("cmd") == GuestMenuAction.PROFILE_EDIT_NOTIFICATIONS.value
    assert screen.rows[5][0].payload.get("cmd") == GuestMenuAction.PROFILE_EDIT_CANCEL.value


def test_vk_profile_edit_screen_rows_when_birth_date_not_editable() -> None:
    """When birth date is not editable, VK profile edit has 5 rows."""

    adapter = VkGuestMenuAdapter()
    screen = adapter.build_profile_edit_screen(can_edit_birth_date=False)

    assert len(screen.rows) == 5
    assert len(screen.rows[0]) == 2
    assert screen.rows[0][0].payload.get("cmd") == GuestMenuAction.PROFILE_EDIT_FIRST_NAME.value
    assert screen.rows[0][1].payload.get("cmd") == GuestMenuAction.PROFILE_EDIT_LAST_NAME.value
    assert screen.rows[1][0].payload.get("cmd") == GuestMenuAction.PROFILE_EDIT_GENDER.value
    assert screen.rows[2][0].payload.get("cmd") == GuestMenuAction.PROFILE_EDIT_EMAIL.value
    assert screen.rows[3][0].payload.get("cmd") == GuestMenuAction.PROFILE_EDIT_NOTIFICATIONS.value
    assert screen.rows[4][0].payload.get("cmd") == GuestMenuAction.PROFILE_EDIT_CANCEL.value
