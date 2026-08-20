"""Тесты точки входа MAX-бота."""

from __future__ import annotations

from vtelemax.adapters.max.sagur_message_interactions import MaxSagurInteractionFilter
from vtelemax.apps import max_app
from vtelemax.settings import AppSettings


def test_dispatcher_registers_sagur_router_before_generic_callback() -> None:
    """Проверяет приоритет служебного JSON SAGUR над общим callback MAX."""

    dispatcher = max_app.build_dispatcher(AppSettings(MAX_BOT_TOKEN="MAX_TEST_TOKEN"))

    assert len(dispatcher.routers) == 2
    assert dispatcher.routers[0].router_id == "max_sagur_message_interactions"
    handler = dispatcher.routers[0].event_handlers[0]
    assert isinstance(handler.base_filters[0], MaxSagurInteractionFilter)
