"""Test DigitalFramesOpenApiView OpenAPI discovery endpoint."""

from __future__ import annotations

import json
from unittest.mock import MagicMock
import pytest

from custom_components.digital_frames.http_api import DigitalFramesOpenApiView


@pytest.mark.asyncio
async def test_openapi_view_endpoint():
    view = DigitalFramesOpenApiView()
    assert view.url == "/api/digital_frames/openapi.json"
    assert view.name == "api:digital_frames:openapi"
    assert view.requires_auth is True

    hass = MagicMock()
    hass.config.config_dir = "/tmp"
    hass.async_add_executor_job = MagicMock(side_effect=lambda func, *args: func(*args))

    request = MagicMock()
    request.app = {"hass": hass}

    response = await view.get(request)
    assert response.status == 200
    assert response.content_type == "application/json"

    data = json.loads(response.body.decode("utf-8"))
    assert data["openapi"] == "3.0.3"
    assert "info" in data
    assert "paths" in data
    assert "/api/digital_frames/openapi.json" in data["paths"]
    assert "/api/digital_frames/frames" in data["paths"]
