"""VK-адаптер.

Здесь будет размещаться интеграция с vkbottle:

1. Обработка входящих событий VK.
2. Преобразование payload/callback в команды ядра.
3. Отправка ответов ядра в формате сообщений VK.
"""

from .identity_adapter import VkAdapterResponse, VkIdentityAdapter
from .keyboard_renderer import render_vk_keyboard
from .menu_adapter import VkButton, VkGuestMenuAdapter, VkScreen
from .payloads import build_vk_payload, resolve_action_from_vk_payload
from .router import register_vk_guest_handlers

__all__ = [
    "VkButton",
    "VkScreen",
    "VkAdapterResponse",
    "VkIdentityAdapter",
    "VkGuestMenuAdapter",
    "render_vk_keyboard",
    "build_vk_payload",
    "resolve_action_from_vk_payload",
    "register_vk_guest_handlers",
]
