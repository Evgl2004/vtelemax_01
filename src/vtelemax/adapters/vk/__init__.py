"""VK-адаптер.

Здесь будет размещаться интеграция с vkbottle:

1. Обработка входящих событий VK.
2. Преобразование payload/callback в команды ядра.
3. Отправка ответов ядра в формате сообщений VK.
"""

from .menu_adapter import VkButton, VkGuestMenuAdapter, VkScreen
from .payloads import build_vk_payload, resolve_action_from_vk_payload

__all__ = [
    "VkButton",
    "VkScreen",
    "VkGuestMenuAdapter",
    "build_vk_payload",
    "resolve_action_from_vk_payload",
]
