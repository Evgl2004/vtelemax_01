"""Unit-тесты точки входа Telegram-бота."""

from __future__ import annotations

import pytest

from vtelemax.apps import telegram_app
from vtelemax.settings import AppSettings


def test_dispatcher_registers_sagur_router_before_generic_callbacks() -> None:
    """Проверяет приоритет служебного JSON SAGUR над общим меню Telegram."""

    dispatcher = telegram_app.build_dispatcher(
        AppSettings(TELEGRAM_BOT_TOKEN="123456:TEST_TOKEN_FOR_LOCAL_UNIT_TEST")
    )

    assert [router.name for router in dispatcher.sub_routers[:2]] == [
        "telegram_sagur_message_interactions",
        "telegram_identity",
    ]


@pytest.mark.asyncio
async def test_run_telegram_bot_uses_configured_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Проверяет передачу Telegram-прокси в polling-сессию бота."""

    captured: dict[str, object] = {}

    class FakeSession:
        def __init__(self, *, proxy: str | None) -> None:
            captured["proxy"] = proxy

    class FakeBot:
        def __init__(self, *, token: str, default: object, session: FakeSession) -> None:
            captured["token"] = token
            captured["session"] = session

    class FakeDispatcher:
        async def start_polling(self, bot: FakeBot) -> None:
            captured["bot"] = bot

    monkeypatch.setattr(telegram_app, "AiohttpSession", FakeSession)
    monkeypatch.setattr(telegram_app, "Bot", FakeBot)
    monkeypatch.setattr(telegram_app, "build_dispatcher", lambda settings: FakeDispatcher())

    await telegram_app.run_telegram_bot(
        AppSettings(
            TELEGRAM_BOT_TOKEN="dummy-token",
            TELEGRAM_PROXY_URL="http://xray-telegram:10809",
        )
    )

    assert captured["proxy"] == "http://xray-telegram:10809"
    assert "bot" in captured
