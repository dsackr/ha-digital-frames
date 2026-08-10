"""Spanned wall image API view (KPF 36): test 2D spatial image spanning across a wall layout."""

from __future__ import annotations

import pytest
from homeassistant.setup import async_setup_component

from custom_components.digital_frames.const import DOMAIN
from custom_components.digital_frames.library import LibraryManager
from custom_components.digital_frames.scenes import SceneManager
from custom_components.digital_frames.walls import WallManager, Wall
from custom_components.digital_frames.walls_http import (
    DigitalFramesWallGeometryView,
    DigitalFramesWallSpanImageView,
)


class _FakeCoordinator:
    """Records every push instead of touching real hardware.

    Matches the real signature every DigitalFramesCoordinator/
    MeuralCoordinator/SamsungCoordinator subclass implements (image_bytes
    positional, thumbnail keyword) -- not the "wire_bytes"/"preview_png"
    keywords a real caller would raise TypeError against. A prior version of
    this fake used those wrong keyword names, which made it silently accept
    a caller that would have crashed every real coordinator with a
    TypeError (the exact bug a live user hit -- see walls_http.py's
    async_send_image_or_queue call sites).
    """

    def __init__(self):
        self.sent = []

    async def async_send_image_or_queue(self, image_bytes, *, image_id=None, thumbnail=None):
        self.sent.append({"image_id": image_id, "image_bytes": image_bytes, "thumbnail": thumbnail})
        return {"queued": False}


@pytest.fixture
async def span_client(hass, hass_client):
    await async_setup_component(hass, "http", {})
    hass.http.register_view(DigitalFramesWallSpanImageView())
    hass.http.register_view(DigitalFramesWallGeometryView())

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


async def test_span_image_push_now_false_saves_scene_without_touching_hardware(
    hass, span_client, make_frame_entry, sample_image_bytes
):
    """The wallpaper editor's "Save as Scene" action must build a crop-based
    scene without pushing any bytes to the physical frames -- only an
    explicit "Send to Frames" (push_now=True, the default) does that."""
    e1 = make_frame_entry(entry_id="frame-1", width=1200, height=1600)
    e2 = make_frame_entry(entry_id="frame-2", width=1200, height=1600)
    e1.add_to_hass(hass)
    e2.add_to_hass(hass)

    coord1, coord2 = _FakeCoordinator(), _FakeCoordinator()
    hass.data[DOMAIN]["frame-1"] = coord1
    hass.data[DOMAIN]["frame-2"] = coord2

    wall_mgr = hass.data[DOMAIN]["_walls"]
    created = await wall_mgr.async_save_wall(
        "Living Room",
        {
            "frame-1": {"x": 40.0, "y": 40.0},
            "frame-2": {"x": 200.0, "y": 40.0},
        },
    )
    wall_id = created["wall_id"]

    lib_mgr = hass.data[DOMAIN]["_library"]
    record = await lib_mgr.async_upload("bg.png", sample_image_bytes(2400, 1600), ["Backgrounds"])
    image_id = record.get("image_id") if isinstance(record, dict) else record.image_id

    resp = await span_client.post(
        f"/api/digital_frames/walls/{wall_id}/span_image",
        json={
            "source_type": "library",
            "image_id": image_id,
            "push_now": False,
            "save_scene": True,
            "scene_name": "Wallpaper Scene",
        },
    )

    assert resp.status == 200
    body = await resp.json()
    assert body["success"] is True
    assert body["scene_id"] is not None
    assert coord1.sent == []
    assert coord2.sent == []

    scene_mgr = hass.data[DOMAIN]["_scenes"]
    scene = await scene_mgr.async_get_scene(body["scene_id"])
    assert scene.mappings["frame-1"]["type"] == "image_crop"
    assert scene.mappings["frame-2"]["type"] == "image_crop"


async def test_span_image_re_saving_with_scene_id_updates_in_place(
    hass, span_client, make_frame_entry, sample_image_bytes
):
    """Re-opening a saved wallpaper scene for editing (a new background, a
    dragged frame) and saving again must update the same scene record, not
    collide with its own name as a duplicate -- without threading scene_id
    back through, async_save_scene(scene_id=None) rejects a name that
    already belongs to a different scene_id."""
    e1 = make_frame_entry(entry_id="frame-1", width=1200, height=1600)
    e1.add_to_hass(hass)

    wall_mgr = hass.data[DOMAIN]["_walls"]
    created = await wall_mgr.async_save_wall("Living Room", {"frame-1": {"x": 40.0, "y": 40.0}})
    wall_id = created["wall_id"]

    lib_mgr = hass.data[DOMAIN]["_library"]
    record1 = await lib_mgr.async_upload("bg1.png", sample_image_bytes(1200, 1600, color=(10, 10, 10)), ["Backgrounds"])
    image_id_1 = record1.get("image_id") if isinstance(record1, dict) else record1.image_id

    first = await span_client.post(
        f"/api/digital_frames/walls/{wall_id}/span_image",
        json={
            "source_type": "library",
            "image_id": image_id_1,
            "push_now": False,
            "save_scene": True,
            "scene_name": "Living Room Wallpaper",
        },
    )
    assert first.status == 200
    first_body = await first.json()
    scene_id = first_body["scene_id"]
    assert scene_id is not None

    # Edit: a different background, same scene name, scene_id threaded back
    # (as the wallpaper editor now does after loading a scene for editing).
    record2 = await lib_mgr.async_upload("bg2.png", sample_image_bytes(1200, 1600, color=(200, 200, 200)), ["Backgrounds"])
    image_id_2 = record2.get("image_id") if isinstance(record2, dict) else record2.image_id

    second = await span_client.post(
        f"/api/digital_frames/walls/{wall_id}/span_image",
        json={
            "source_type": "library",
            "image_id": image_id_2,
            "push_now": False,
            "save_scene": True,
            "scene_name": "Living Room Wallpaper",
            "scene_id": scene_id,
        },
    )

    assert second.status == 200
    second_body = await second.json()
    assert second_body["success"] is True
    assert "scene_save_error" not in second_body
    assert second_body["scene_id"] == scene_id

    scene_mgr = hass.data[DOMAIN]["_scenes"]
    all_scenes = await scene_mgr.async_list_scenes()
    assert len(all_scenes) == 1
    scene = await scene_mgr.async_get_scene(scene_id)
    assert scene.mappings["frame-1"]["image_id"] == image_id_2


async def test_span_image_same_name_without_scene_id_reports_error_not_500(
    hass, span_client, make_frame_entry, sample_image_bytes
):
    """Saving a *new* scene whose name collides with an existing one (no
    scene_id passed) must surface as scene_save_error on an otherwise-
    successful response, not silently succeed or crash."""
    e1 = make_frame_entry(entry_id="frame-1", width=1200, height=1600)
    e1.add_to_hass(hass)

    wall_mgr = hass.data[DOMAIN]["_walls"]
    created = await wall_mgr.async_save_wall("Living Room", {"frame-1": {"x": 40.0, "y": 40.0}})
    wall_id = created["wall_id"]

    lib_mgr = hass.data[DOMAIN]["_library"]
    record = await lib_mgr.async_upload("bg.png", sample_image_bytes(1200, 1600), ["Backgrounds"])
    image_id = record.get("image_id") if isinstance(record, dict) else record.image_id

    body = {
        "source_type": "library",
        "image_id": image_id,
        "push_now": False,
        "save_scene": True,
        "scene_name": "Duplicate Name",
    }
    first = await span_client.post(f"/api/digital_frames/walls/{wall_id}/span_image", json=body)
    assert first.status == 200
    assert (await first.json())["scene_id"] is not None

    second = await span_client.post(f"/api/digital_frames/walls/{wall_id}/span_image", json=body)
    assert second.status == 200
    second_body = await second.json()
    assert second_body["success"] is True
    assert second_body["scene_id"] is None
    assert "already exists" in second_body["scene_save_error"]


async def test_span_image_push_now_true_sends_to_coordinators(
    hass, span_client, make_frame_entry, sample_image_bytes
):
    e1 = make_frame_entry(entry_id="frame-1", width=1200, height=1600)
    e1.add_to_hass(hass)

    coord1 = _FakeCoordinator()
    hass.data[DOMAIN]["frame-1"] = coord1

    wall_mgr = hass.data[DOMAIN]["_walls"]
    created = await wall_mgr.async_save_wall("Living Room", {"frame-1": {"x": 40.0, "y": 40.0}})
    wall_id = created["wall_id"]

    lib_mgr = hass.data[DOMAIN]["_library"]
    record = await lib_mgr.async_upload("bg.png", sample_image_bytes(1200, 1600), ["Backgrounds"])
    image_id = record.get("image_id") if isinstance(record, dict) else record.image_id

    resp = await span_client.post(
        f"/api/digital_frames/walls/{wall_id}/span_image",
        json={"source_type": "library", "image_id": image_id},
    )

    assert resp.status == 200
    body = await resp.json()
    assert body["success"] is True
    assert len(coord1.sent) == 1


async def test_geometry_view_returns_canvas_and_crop_boxes_without_side_effects(
    hass, span_client, make_frame_entry
):
    """GET .../geometry must be read-only: no library upload, no coordinator
    push, no scene created -- the wallpaper editor polls this freely to size
    a "generate for this wall" request."""
    e1 = make_frame_entry(entry_id="frame-1", width=1200, height=1600)
    e2 = make_frame_entry(entry_id="frame-2", width=1200, height=1600)
    e1.add_to_hass(hass)
    e2.add_to_hass(hass)

    coord1 = _FakeCoordinator()
    hass.data[DOMAIN]["frame-1"] = coord1

    wall_mgr = hass.data[DOMAIN]["_walls"]
    created = await wall_mgr.async_save_wall(
        "Living Room",
        {
            "frame-1": {"x": 40.0, "y": 40.0},
            "frame-2": {"x": 200.0, "y": 40.0},
        },
    )
    wall_id = created["wall_id"]

    resp = await span_client.get(f"/api/digital_frames/walls/{wall_id}/geometry")

    assert resp.status == 200
    body = await resp.json()
    assert body["success"] is True
    assert body["canvas_width"] > 0
    assert body["canvas_height"] > 0
    assert "frame-1" in body["crop_boxes"]
    assert "frame-2" in body["crop_boxes"]
    assert coord1.sent == []

    lib_mgr = hass.data[DOMAIN]["_library"]
    assert await lib_mgr.async_list_images() == []


async def test_geometry_view_unknown_wall_returns_404(hass, span_client):
    resp = await span_client.get("/api/digital_frames/walls/nonexistent-wall/geometry")
    assert resp.status == 404


async def test_geometry_view_empty_wall_returns_400(hass, span_client):
    wall_mgr = hass.data[DOMAIN]["_walls"]
    created = await wall_mgr.async_save_wall("Empty Wall", {})
    wall_id = created["wall_id"]

    resp = await span_client.get(f"/api/digital_frames/walls/{wall_id}/geometry")
    assert resp.status == 400
