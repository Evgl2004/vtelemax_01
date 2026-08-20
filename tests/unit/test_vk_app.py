"""Тесты точки входа VK-бота."""

from __future__ import annotations

from vkbottle_types.events import GroupEventType

from vtelemax.adapters.vk.sagur_message_interactions import VkSagurInteractionRule
from vtelemax.apps import vk_app
from vtelemax.settings import AppSettings


def test_bot_registers_sagur_handler_before_generic_callback() -> None:
    """Проверяет приоритет служебного JSON SAGUR над общим callback VK."""

    bot = vk_app.build_bot(AppSettings(VK_BOT_TOKEN="VK_TEST_TOKEN"))
    handlers = bot.on.raw_event_view.handlers[GroupEventType.MESSAGE_EVENT]

    assert len(handlers) >= 2
    assert handlers[0].handler.blocking is True
    assert isinstance(handlers[0].handler.rules[0], VkSagurInteractionRule)
