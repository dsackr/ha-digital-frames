"""Art Factory API views (KPF 38): test standalone prompt-to-art generation and AI fallback."""

from __future__ import annotations

import pytest
from homeassistant.setup import async_setup_component

from custom_components.digital_frames.art_factory_http import (
    DigitalFramesArtFactoryStatusView,
    DigitalFramesArtFactoryGenerateView,
)
from custom_components.digital_frames.const import DOMAIN
from custom_components.digital_frames.library import LibraryManager


@pytest.fixture
async def art_client(hass, hass_client):
    await async_setup_component(hass, "http", {})
    hass.http.register_view(DigitalFramesArtFactoryStatusView())
    hass.http.register_view(DigitalFramesArtFactoryGenerateView())

    lib_mgr = LibraryManager(hass)
    await lib_mgr.async_load()
    hass.data.setdefault(DOMAIN, {})["_library"] = lib_mgr

    return await hass_client()


async def test_art_factory_status_endpoint(hass, art_client):
    resp = await art_client.get("/api/digital_frames/art_factory/status")
    assert resp.status == 200
    body = await resp.json()
    assert body["success"] is True
    assert "has_ha_ai" in body
    assert "active_engine" in body


async def test_art_factory_generate_empty_prompt_returns_400(art_client):
    resp = await art_client.post(
        "/api/digital_frames/art_factory/generate",
        json={"prompt": "  "},
    )
    assert resp.status == 400
    body = await resp.json()
    assert "empty" in body["message"]


async def test_art_factory_generate_success_with_fallback(art_client, monkeypatch):
    import custom_components.digital_frames as df

    async def _mock_fetch(hass, url):
        return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"

    monkeypatch.setattr(df, "_fetch_media_bytes", _mock_fetch)

    resp = await art_client.post(
        "/api/digital_frames/art_factory/generate",
        json={
            "prompt": "Sunset over snow-capped mountains",
            "style": "plain",
            "save_to_library": True,
        },
    )

    assert resp.status == 200
    body = await resp.json()
    assert body["success"] is True
    assert body["prompt"] == "Sunset over snow-capped mountains"
    assert "data:image/png;base64," in body["preview_url"]
    assert body["image_id"] is not None
