"""Тесты вспомогательных функций VK-роутера."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from vtelemax.adapters.vk.router import (
    build_vk_pending_delivery_sender,
    _build_vk_coupon_delivery_keyboard_json,
    _build_vk_moderation_notification_keyboard_json,
    _build_vk_photo_attachment,
    _is_message_not_modified_error,
    _normalize_vk_message,
    _send_coupon_qr_message,
    _send_virtual_card_qr_messages,
    _upload_vk_png_for_messages,
    _with_virtual_card_delivery_notice,
)
from vtelemax.adapters.vk.identity_adapter import VkAdapterResponse
from vtelemax.core import PendingModeratorDelivery, SupportMessageAuthor


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


def test_build_vk_moderation_notification_keyboard_contains_reply_and_phone_buttons() -> None:
    """Проверяет, что клавиатура уведомления модератора VK содержит две callback-кнопки."""

    keyboard_json = _build_vk_moderation_notification_keyboard_json(
        "11111111-1111-1111-1111-111111111111"
    )
    payload = json.loads(keyboard_json)

    assert payload["inline"] is True
    assert len(payload["buttons"]) == 1
    assert len(payload["buttons"][0]) == 2

    reply_button = payload["buttons"][0][0]
    phone_button = payload["buttons"][0][1]

    reply_cmd = json.loads(reply_button["action"]["payload"])["cmd"]
    phone_cmd = json.loads(phone_button["action"]["payload"])["cmd"]

    assert reply_button["action"]["label"] == "✍️ Ответить"
    assert phone_button["action"]["label"] == "📞 Телефон гостя"
    assert reply_cmd.startswith("mod_reply_")
    assert phone_cmd.startswith("mod_phone_show_")


def test_build_vk_coupon_delivery_keyboard_opens_coupons_menu() -> None:
    """Проверяет VK-кнопку перехода из купонной рассылки в меню купонов."""

    keyboard_json = _build_vk_coupon_delivery_keyboard_json()
    payload = json.loads(keyboard_json)

    button = payload["buttons"][0][0]
    callback_payload = json.loads(button["action"]["payload"])

    assert payload["inline"] is True
    assert button["action"]["label"] == "🎟️ Перейти к купонам"
    assert callback_payload == {"cmd": "coupons"}


@pytest.mark.asyncio
async def test_vk_pending_delivery_sender_adds_coupon_menu_button() -> None:
    """Проверяет кнопку перехода в купоны под VK-рассылкой купона."""

    class _FakeMessages:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def send(self, **kwargs: object) -> None:
            self.calls.append(kwargs)

    class _FakeBot:
        def __init__(self) -> None:
            self.api = type("_Api", (), {"messages": _FakeMessages()})()

    bot = _FakeBot()
    sender = build_vk_pending_delivery_sender(bot)
    await sender(
        PendingModeratorDelivery(
            message_id=uuid4(),
            author=SupportMessageAuthor.SYSTEM,
            ticket_id=uuid4(),
            source_platform="vk",
            target_platform="vk",
            target_external_id="1001",
            body="Код купона: E2E-OVT89GWN",
            created_at=None,
        ),
        "Код купона: E2E-OVT89GWN",
    )

    call = bot.api.messages.calls[0]
    keyboard = json.loads(call["keyboard"])
    button = keyboard["buttons"][0][0]
    payload = json.loads(button["action"]["payload"])

    assert call["user_id"] == 1001
    assert button["action"]["label"] == "🎟️ Перейти к купонам"
    assert payload == {"cmd": "coupons"}


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


@pytest.mark.asyncio
async def test_send_virtual_card_qr_messages_sends_text_fallback_when_upload_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Проверяет текстовый fallback, если VK upload QR не отвечает."""

    class _FakeMessages:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def send(self, **kwargs: object) -> None:
            self.calls.append(kwargs)

    class _FakeApi:
        def __init__(self) -> None:
            self.messages = _FakeMessages()

    async def _fake_upload_vk_png_for_messages(*, ctx_api, peer_id: int, image_bytes: bytes) -> str:  # noqa: ANN001
        raise TimeoutError("upload timeout")

    monkeypatch.setattr("vtelemax.adapters.vk.router.generate_qr_png_bytes", lambda _: b"png")
    monkeypatch.setattr(
        "vtelemax.adapters.vk.router._upload_vk_png_for_messages",
        _fake_upload_vk_png_for_messages,
    )

    fake_api = _FakeApi()
    result = await _send_virtual_card_qr_messages(
        ctx_api=fake_api,
        peer_id=12345,
        card_numbers=("79000000001_20260331",),
    )

    assert result.total == 1
    assert result.sent == 0
    assert result.failed == 1
    assert len(fake_api.messages.calls) == 1
    fallback = fake_api.messages.calls[0]
    assert fallback["peer_id"] == 12345
    assert "QR-код карты временно не удалось отправить" in fallback["message"]
    assert "79000000001_20260331" in fallback["message"]


@pytest.mark.asyncio
async def test_send_coupon_qr_message_sends_attachment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверяет успешную отправку QR купона в VK."""

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
    await _send_coupon_qr_message(
        ctx_api=fake_api,
        peer_id=12345,
        response=VkAdapterResponse(
            text="Карточка купона",
            coupon_qr_payload="PROMO-2026-7777",
            coupon_qr_caption="🎟️ Купон • PROMO-2026-7777",
        ),
    )

    assert fake_api.messages.calls == [
        {
            "peer_id": 12345,
            "random_id": 0,
            "message": "🎟️ Купон • PROMO-2026-7777",
            "attachment": "photo10_20_abc",
        }
    ]


@pytest.mark.asyncio
async def test_send_coupon_qr_message_does_not_raise_when_attachment_send_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Проверяет fallback-поведение: ошибка отправки QR купона не роняет текстовую карточку."""

    class _FakeMessages:
        async def send(self, **kwargs: object) -> None:
            raise RuntimeError("messages.send failed")

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

    await _send_coupon_qr_message(
        ctx_api=_FakeApi(),
        peer_id=12345,
        response=VkAdapterResponse(
            text="Карточка купона",
            coupon_qr_payload="PROMO-2026-7777",
            coupon_qr_caption="🎟️ Купон • PROMO-2026-7777",
        ),
    )


def test_with_virtual_card_delivery_notice_replaces_inaccurate_qr_text() -> None:
    """Проверяет, что итоговый текст не обещает QR после сбоя upload."""

    response = VkAdapterResponse(
        text="✅ Регистрация успешно завершена.\n\n🪪 Выше представлены QR-коды ваших карт.",
    )

    updated = _with_virtual_card_delivery_notice(
        response,
        result=type("_Result", (), {"total": 1, "sent": 0, "failed": 1})(),
    )

    assert "Выше представлены QR-коды" not in updated.text
    assert "QR-код карты временно не удалось отправить" in updated.text


@pytest.mark.asyncio
async def test_upload_vk_png_retries_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверяет retry upload QR в VK после временного таймаута."""

    attempts: list[str] = []
    sleeps: list[float] = []

    class _FakeResponse:
        status = 200

        async def __aenter__(self) -> "_FakeResponse":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def json(self, *, content_type: object = None) -> dict[str, object]:
            return {"photo": "photo-json", "server": 10, "hash": "hash-value"}

    class _FakeSession:
        async def __aenter__(self) -> "_FakeSession":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        def post(self, upload_url: str, **kwargs: object) -> _FakeResponse:
            attempts.append(upload_url)
            if len(attempts) == 1:
                raise TimeoutError("upload timeout")
            return _FakeResponse()

    class _FakePhotos:
        async def get_messages_upload_server(self, *, peer_id: int) -> dict[str, str]:
            return {"upload_url": "https://upload.vk.example/path?secret=hidden"}

        async def save_messages_photo(
            self,
            *,
            photo: str,
            server: int,
            hash: str,
        ) -> list[dict[str, object]]:
            assert photo == "photo-json"
            assert server == 10
            assert hash == "hash-value"
            return [{"owner_id": 1, "id": 2, "access_key": "key"}]

    class _FakeApi:
        def __init__(self) -> None:
            self.photos = _FakePhotos()

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("vtelemax.adapters.vk.router.aiohttp.ClientSession", _FakeSession)
    monkeypatch.setattr("vtelemax.adapters.vk.router.asyncio.sleep", _fake_sleep)

    attachment = await _upload_vk_png_for_messages(
        ctx_api=_FakeApi(),
        peer_id=12345,
        image_bytes=b"png",
    )

    assert attachment == "photo1_2_key"
    assert len(attempts) == 2
    assert sleeps == [0.75]
