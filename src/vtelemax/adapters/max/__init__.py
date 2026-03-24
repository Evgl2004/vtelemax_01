"""MAX-адаптер.

Слой отвечает за интеграцию с библиотекой maxapi:

1. Преобразование событий MAX в унифицированные команды ядра.
2. Преобразование ответов ядра в сообщения и клавиатуры MAX.
3. Поддержку гостевого сценария strict identity на общей бизнес-логике.
"""

from .identity_adapter import MaxAdapterResponse, MaxIdentityAdapter
from .keyboard_renderer import render_max_keyboard
from .menu_adapter import MaxButton, MaxGuestMenuAdapter, MaxScreen
from .payloads import build_max_payload, resolve_action_from_max_payload
from .router import register_max_guest_handlers

__all__ = [
    "MaxButton",
    "MaxScreen",
    "MaxAdapterResponse",
    "MaxIdentityAdapter",
    "MaxGuestMenuAdapter",
    "render_max_keyboard",
    "build_max_payload",
    "resolve_action_from_max_payload",
    "register_max_guest_handlers",
]
