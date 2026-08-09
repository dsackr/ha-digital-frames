"""Spanned wall image API view (KPF 36): test 2D spatial image spanning across a wall layout."""

from __future__ import annotations

import pytest
from homeassistant.setup import async_setup_component

from custom_components.digital_frames.const import DOMAIN
from custom_components.digital_frames.library import LibraryManager
from custom_components.digital_frames.scenes import SceneManager
from custom_components.digital_frames.walls import WallManager, Wall
from custom_components.digital_frames.walls_http import DigitalFramesWallSpanImageView


@pytest.fixture
async def span_client(hass, hass_client):
    await async_setup_component(hass, "http", {})
    hass.http.register_view(DigitalFramesWallSpanImageView())

    lib_mgr = LibraryManager(hass)
    await lib_mgr.async_load()
    scene_mgr = SceneManager(hass)
    await scene_mgr.async_load()
    wall_mgr = WallManager(hass)
    await wall_mgr.async_load()

    hass.data.setdefault(DOMAIN, {})["_library"] = lib_mgr
    hass.data.setdefault(DOMAIN, {})["_scenes"] = scene_mgr
    hass.data.setdefault(DOMAIN, {})["_walls"] = wall_mgr

    return await hass_client()


async def test_span_image_ai_source_success(hass, span_client, make_frame_entry):
    e1 = make_frame_entry(entry_id="frame-1", width=1200, height=1600)
    e2 = make_frame_entry(entry_id="frame-2", width=1200, height=1600)
    e1.add_to_hass(hass)
    e2.add_to_hass(hass)

    wall_mgr = hass.data[DOMAIN]["_walls"]
    created = await wall_mgr.async_save_wall(
        "Living Room",
        {
            "frame-1": {"x": 40.0, "y": 40.0},
            "frame-2": {"x": 200.0, "y": 40.0},
        },
    )
    wall_id = created["wall_id"]

    resp = await span_client.post(
        f"/api/digital_frames/walls/{wall_id}/span_image",
        json={
            "source_type": "ai",
            "prompt": "Vibrant mountain sunset",
            "preserve_bezel_gaps": True,
            "save_to_library": True,
            "save_scene": True,
            "scene_name": "Living Room Sunset",
        },
    )

    assert resp.status == 200
    body = await resp.json()
    assert body["success"] is True
    assert body["wall_id"] == wall_id
    assert body["frames_updated"] == 2
    assert "frame-1" in body["crop_boxes"]
    assert "frame-2" in body["crop_boxes"]
    assert body["saved_image_id"] is not None
    assert body["scene_id"] is not None


async def test_span_image_unknown_wall_returns_404(hass, span_client):
    resp = await span_client.post(
        "/api/digital_frames/walls/nonexistent-wall/span_image",
        json={"source_type": "ai"},
    )
    assert resp.status == 404


async def test_span_image_empty_wall_returns_400(hass, span_client):
    wall_mgr = hass.data[DOMAIN]["_walls"]
    created = await wall_mgr.async_save_wall("Empty Wall", {})
    wall_id = created["wall_id"]

    resp = await span_client.post(
        f"/api/digital_frames/walls/{wall_id}/span_image",
        json={"source_type": "ai"},
    )
    assert resp.status == 400
    body = await resp.json()
    assert "No frames" in body["message"]
