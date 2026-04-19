"""Smoke-тест импорта VK Mini App verification service."""

from __future__ import annotations


def test_vk_phone_verification_service_module_is_importable() -> None:
    """Проверяет, что модуль сервиса загружается без синтаксических ошибок."""

    from vtelemax.apps.vk_phone_verification_service_app import build_web_app  # noqa: PLC0415

    assert callable(build_web_app)

