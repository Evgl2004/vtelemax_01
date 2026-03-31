"""Тесты вспомогательных функций VK-роутера."""

from __future__ import annotations

import pytest

from vtelemax.adapters.vk.router import (
    _build_vk_photo_attachment,
    _is_message_not_modified_error,
    _normalize_vk_message,
    _send_virtual_card_qr_messages,
)


def test_is_message_not_modified_error_detects_known_patterns() -> None:
    """Проверяет распознавание служебной ошибки «сообщение не изменилось»."""

    assert _is_message_not_modified_error(RuntimeError("Message is not modified"))
    assert _is_message_not_modified_error(RuntimeError("message is same as before"))


def test_is_message_not_modified_error_returns_false_for_other_errors() -> None:
    """Проверяет, что посторонние ошибки не считаются «not modified»."""

    assert not _is_message_not_modified_error(RuntimeError("invalid access token"))


def test_normalize_vk_message_strips_markdown_when_needed() -> None:
    """Проверяет, что markdown-текст приводится к плоскому виду для VK."""

    text, parse_mode = _normalize_vk_message("*Жирный* `код`", "markdown")

    assert text == "Жирный код"
    assert parse_mode is None


def test_build_vk_photo_attachment_with_access_key() -> None:
    """Проверяет формирование attachment с access_key."""

    attachment = _build_vk_photo_attachment({"owner_id": 10, "id": 20, "access_key": "abc"})

    assert attachment == "photo10_20_abc"


def test_build_vk_photo_attachment_returns_none_for_dirty_photo() -> None:
    """Проверяет dirty-сценарий: без обязательных полей attachment не формируется."""

    attachment = _build_vk_photo_attachment({"owner_id": 10})

    assert attachment is None


@pytest.mark.asyncio
async def test_send_virtual_card_qr_messages_sends_image_and_text_separately(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверяет, что VK отправляет QR-картинку и подпись отдельными сообщениями."""

    class _FakeMessages:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def send(self, **kwargs: object) -> None:
            self.calls.append(kwargs)

    class _FakeApi:
        def __init__(self) -> None:
            self.messages = _FakeMessages()

    async def _fake_upload_vk_png_for_messages(*, ctx_api, peer_id: int, image_bytes: bytes) -> str:  # noqa: ANN001
        return "photo10_20_abc"

    monkeypatch.setattr("vtelemax.adapters.vk.router.generate_qr_png_bytes", lambda _: b"png")
    monkeypatch.setattr(
        "vtelemax.adapters.vk.router._upload_vk_png_for_messages",
        _fake_upload_vk_png_for_messages,
    )

    fake_api = _FakeApi()
    await _send_virtual_card_qr_messages(
        ctx_api=fake_api,
        peer_id=12345,
        card_numbers=("79000000001_20260331",),
    )

    assert len(fake_api.messages.calls) == 2
    first_call = fake_api.messages.calls[0]
    second_call = fake_api.messages.calls[1]

    assert first_call["peer_id"] == 12345
    assert first_call["message"] == ""
    assert first_call["attachment"] == "photo10_20_abc"
    assert second_call["peer_id"] == 12345
    assert second_call["message"] == "💳 Карта: 79000000001_20260331"
    assert "attachment" not in second_call
