"""Unit tests for SAGUR integration API app bootstrap."""

from __future__ import annotations

import pytest

from vtelemax.apps.sagur_integration_api_app import _validate_service_settings, build_web_app
from vtelemax.settings import AppSettings


def test_sagur_integration_api_module_is_importable() -> None:
    assert callable(build_web_app)


def test_sagur_integration_app_registers_required_routes() -> None:
    settings = AppSettings()
    app = build_web_app(settings=settings)

    route_paths = {route.resource.canonical for route in app.router.routes()}

    assert "/health" in route_paths
    assert "/internal/integration/v1/sagur/recipients/snapshot" in route_paths
    assert "/internal/integration/v1/sagur/recipients/delta" in route_paths


def test_sagur_integration_settings_validation_rejects_bad_limits() -> None:
    settings = AppSettings(
        SAGUR_INTEGRATION_DEFAULT_LIMIT=5001,
        SAGUR_INTEGRATION_MAX_LIMIT=5000,
    )

    with pytest.raises(ValueError):
        _validate_service_settings(settings)

