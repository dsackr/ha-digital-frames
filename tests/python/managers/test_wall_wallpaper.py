"""Wallpaper: one library image placed on a wall's canvas at an explicit,
independent rect, sliced into each frame's own crop by wherever that frame
currently sits (KPF 19/36). A wallpaper is not a separate entity -- saving
one just creates/updates an ordinary Scene whose mappings are image_crop
entries sharing one image_id, plus a `wallpaper` field recording the
image's rect for the editor to restore later.

If this silently breaks: a frame's on-screen crop could stretch/shift
whenever *any* frame moves (the bug this replaced -- the image's rect must
be completely independent of frame placement), a re-saved wallpaper scene
could duplicate instead of updating in place, or a real coordinator call
could throw (see the wire_bytes/thumbnail keyword-name history below).
"""

from __future__ import annotations

import pytest
from homeassistant.setup import async_setup_component

from custom_components.digital_frames.const import DOMAIN
from custom_components.digital_frames.library import LibraryManager
from custom_components.digital_frames.scenes import SceneManager
from custom_components.digital_frames.walls import WallManager
from custom_components.digital_frames.walls_http import DigitalFramesWallWallpaperView


class _FakeCoordinator:
    """Records every push instead of touching real hardware.

    Matches the real signature every DigitalFramesCoordinator/
    MeuralCoordinator/SamsungCoordinator subclass implements (image_bytes
    positional, thumbnail keyword) -- not "wire_bytes"/"preview_png"
    keywords a real caller would raise TypeError against. A prior version
    of this fake used those wrong keyword names, which made it silently
    accept a caller that would have crashed every real coordinator with a
    TypeError (a bug a live user actually hit).
    """

    def __init__(self):
        self.sent = []

    async def async_send_image_or_queue(self, image_bytes, *, image_id=None, thumbnail=None):
        self.sent.append({"image_id": image_id, "image_bytes": image_bytes, "thumbnail": thumbnail})
        return {"queued": False}


@pytest.fixture
async def wallpaper_client(hass, hass_client):
    await async_setup_component(hass, "http", {})
    hass.http.register_view(DigitalFramesWallWallpaperView())

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


async def _make_wall_and_image(hass, make_frame_entry, sample_image_bytes, *, placements=None):
    e1 = make_frame_entry(entry_id="frame-1", width=1200, height=1600)
    e2 = make_frame_entry(entry_id="frame-2", width=1200, height=1600)
    e1.add_to_hass(hass)
    e2.add_to_hass(hass)

    wall_mgr = hass.data[DOMAIN]["_walls"]
    created = await wall_mgr.async_save_wall(
        "Living Room",
        placements or {
            "frame-1": {"x": 40.0, "y": 40.0},
            "frame-2": {"x": 200.0, "y": 40.0},
        },
    )
    wall_id = created["wall_id"]

    lib_mgr = hass.data[DOMAIN]["_library"]
    record = await lib_mgr.async_upload("bg.png", sample_image_bytes(2000, 1600), ["Backgrounds"])
    image_id = record.get("image_id") if isinstance(record, dict) else record.image_id

    return wall_id, image_id


async def test_wallpaper_unknown_wall_returns_404(hass, wallpaper_client):
    resp = await wallpaper_client.post(
        "/api/digital_frames/walls/nonexistent-wall/wallpaper",
        json={"image_id": "img-1", "image_rect": {"x": 0, "y": 0, "width": 100, "height": 100}},
    )
    assert resp.status == 404


async def test_wallpaper_missing_image_id_returns_400(hass, wallpaper_client, make_frame_entry):
    wall_mgr = hass.data[DOMAIN]["_walls"]
    created = await wall_mgr.async_save_wall("Empty Wall", {})
    resp = await wallpaper_client.post(
        f"/api/digital_frames/walls/{created['wall_id']}/wallpaper",
        json={"image_rect": {"x": 0, "y": 0, "width": 100, "height": 100}},
    )
    assert resp.status == 400
    assert "image_id" in (await resp.json())["message"]


async def test_wallpaper_missing_image_rect_returns_400(hass, wallpaper_client, make_frame_entry):
    wall_mgr = hass.data[DOMAIN]["_walls"]
    created = await wall_mgr.async_save_wall("Empty Wall", {})
    resp = await wallpaper_client.post(
        f"/api/digital_frames/walls/{created['wall_id']}/wallpaper",
        json={"image_id": "img-1"},
    )
    assert resp.status == 400
    assert "image_rect" in (await resp.json())["message"]


async def test_wallpaper_save_scene_without_touching_hardware(
    hass, wallpaper_client, make_frame_entry, sample_image_bytes
):
    """push_now=False must build a crop-based scene without pushing any
    bytes to the physical frames."""
    wall_id, image_id = await _make_wall_and_image(hass, make_frame_entry, sample_image_bytes)

    coord1, coord2 = _FakeCoordinator(), _FakeCoordinator()
    hass.data[DOMAIN]["frame-1"] = coord1
    hass.data[DOMAIN]["frame-2"] = coord2

    resp = await wallpaper_client.post(
        f"/api/digital_frames/walls/{wall_id}/wallpaper",
        json={
            "image_id": image_id,
            "image_rect": {"x": 0.0, "y": 0.0, "width": 2000.0, "height": 1600.0},
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
    assert scene.mappings["frame-1"]["image_id"] == image_id
    assert scene.mappings["frame-2"]["type"] == "image_crop"
    assert scene.wallpaper == {"image_id": image_id, "x": 0.0, "y": 0.0, "width": 2000.0, "height": 1600.0}


async def test_wallpaper_moving_one_frame_does_not_change_another_frames_crop(
    hass, wallpaper_client, make_frame_entry, sample_image_bytes
):
    """The core bug this endpoint was rewritten to fix: a frame's crop must
    depend only on its own position and the image's rect, never on where
    *other* frames happen to be."""
    wall_id, image_id = await _make_wall_and_image(hass, make_frame_entry, sample_image_bytes)
    image_rect = {"x": 0.0, "y": 0.0, "width": 2000.0, "height": 1600.0}

    resp1 = await wallpaper_client.post(
        f"/api/digital_frames/walls/{wall_id}/wallpaper",
        json={"image_id": image_id, "image_rect": image_rect, "push_now": False},
    )
    crop_boxes_1 = (await resp1.json())["crop_boxes"]

    wall_mgr = hass.data[DOMAIN]["_walls"]
    await wall_mgr.async_save_wall(
        "Living Room",
        {"frame-1": {"x": 40.0, "y": 40.0}, "frame-2": {"x": 900.0, "y": 900.0}},
        wall_id=wall_id,
    )

    resp2 = await wallpaper_client.post(
        f"/api/digital_frames/walls/{wall_id}/wallpaper",
        json={"image_id": image_id, "image_rect": image_rect, "push_now": False},
    )
    crop_boxes_2 = (await resp2.json())["crop_boxes"]

    assert crop_boxes_1["frame-1"] == crop_boxes_2["frame-1"]
    assert crop_boxes_1["frame-2"] != crop_boxes_2["frame-2"]


async def test_wallpaper_push_now_true_sends_to_coordinators(
    hass, wallpaper_client, make_frame_entry, sample_image_bytes
):
    wall_id, image_id = await _make_wall_and_image(hass, make_frame_entry, sample_image_bytes)
    coord1 = _FakeCoordinator()
    hass.data[DOMAIN]["frame-1"] = coord1

    resp = await wallpaper_client.post(
        f"/api/digital_frames/walls/{wall_id}/wallpaper",
        json={
            "image_id": image_id,
            "image_rect": {"x": 0.0, "y": 0.0, "width": 2000.0, "height": 1600.0},
        },
    )

    assert resp.status == 200
    body = await resp.json()
    assert body["success"] is True
    assert len(coord1.sent) == 1
    # image_id deliberately omitted: this frame shows a *crop*, not the
    # whole image -- see coordinator.py's async_set_last_image docstring
    # ("pass exactly one of image_id/thumbnail").
    assert coord1.sent[0]["image_id"] is None
    assert coord1.sent[0]["thumbnail"] is not None


async def test_wallpaper_frame_outside_image_rect_excluded_from_scene(
    hass, wallpaper_client, make_frame_entry, sample_image_bytes
):
    """A frame with no overlap at all gets skipped, not sent a degenerate
    crop or included in the saved scene's mappings."""
    wall_id, image_id = await _make_wall_and_image(
        hass, make_frame_entry, sample_image_bytes,
        placements={"frame-1": {"x": 40.0, "y": 40.0}, "frame-2": {"x": 5000.0, "y": 5000.0}},
    )

    resp = await wallpaper_client.post(
        f"/api/digital_frames/walls/{wall_id}/wallpaper",
        json={
            "image_id": image_id,
            "image_rect": {"x": 0.0, "y": 0.0, "width": 500.0, "height": 500.0},
            "push_now": False,
            "save_scene": True,
            "scene_name": "Partial Wallpaper",
        },
    )

    assert resp.status == 200
    body = await resp.json()
    assert "frame-1" in body["crop_boxes"]
    assert body["crop_boxes"]["frame-2"] is None
    assert body["frames_updated"] == 1

    scene_mgr = hass.data[DOMAIN]["_scenes"]
    scene = await scene_mgr.async_get_scene(body["scene_id"])
    assert set(scene.mappings.keys()) == {"frame-1"}


async def test_wallpaper_re_saving_with_scene_id_updates_in_place(
    hass, wallpaper_client, make_frame_entry, sample_image_bytes
):
    """Editing a previously-saved wallpaper (a new zoom/pan, a dragged
    frame) and saving again must update the same scene, not collide with
    its own name as a duplicate."""
    wall_id, image_id = await _make_wall_and_image(hass, make_frame_entry, sample_image_bytes)

    first = await wallpaper_client.post(
        f"/api/digital_frames/walls/{wall_id}/wallpaper",
        json={
            "image_id": image_id,
            "image_rect": {"x": 0.0, "y": 0.0, "width": 2000.0, "height": 1600.0},
            "push_now": False,
            "save_scene": True,
            "scene_name": "Living Room Wallpaper",
        },
    )
    scene_id = (await first.json())["scene_id"]
    assert scene_id is not None

    # Re-save with a different (zoomed) image_rect and the scene_id threaded back.
    second = await wallpaper_client.post(
        f"/api/digital_frames/walls/{wall_id}/wallpaper",
        json={
            "image_id": image_id,
            "image_rect": {"x": -200.0, "y": -100.0, "width": 3000.0, "height": 2400.0},
            "push_now": False,
            "save_scene": True,
            "scene_name": "Living Room Wallpaper",
            "scene_id": scene_id,
        },
    )
    second_body = await second.json()
    assert second_body["success"] is True
    assert "scene_save_error" not in second_body
    assert second_body["scene_id"] == scene_id

    scene_mgr = hass.data[DOMAIN]["_scenes"]
    assert len(await scene_mgr.async_list_scenes()) == 1
    scene = await scene_mgr.async_get_scene(scene_id)
    assert scene.wallpaper["width"] == 3000.0


async def test_wallpaper_same_name_without_scene_id_reports_error_not_500(
    hass, wallpaper_client, make_frame_entry, sample_image_bytes
):
    wall_id, image_id = await _make_wall_and_image(hass, make_frame_entry, sample_image_bytes)
    body = {
        "image_id": image_id,
        "image_rect": {"x": 0.0, "y": 0.0, "width": 2000.0, "height": 1600.0},
        "push_now": False,
        "save_scene": True,
        "scene_name": "Duplicate Name",
    }

    first = await wallpaper_client.post(f"/api/digital_frames/walls/{wall_id}/wallpaper", json=body)
    assert (await first.json())["scene_id"] is not None

    second = await wallpaper_client.post(f"/api/digital_frames/walls/{wall_id}/wallpaper", json=body)
    second_body = await second.json()
    assert second.status == 200
    assert second_body["success"] is True
    assert second_body["scene_id"] is None
    assert "already exists" in second_body["scene_save_error"]


async def test_wallpaper_partial_send_failure_does_not_block_other_frames(
    hass, wallpaper_client, make_frame_entry, sample_image_bytes
):
    wall_id, image_id = await _make_wall_and_image(hass, make_frame_entry, sample_image_bytes)

    class _BrokenCoordinator:
        async def async_send_image_or_queue(self, *args, **kwargs):
            raise ConnectionError("frame unreachable")

    hass.data[DOMAIN]["frame-1"] = _BrokenCoordinator()
    coord2 = _FakeCoordinator()
    hass.data[DOMAIN]["frame-2"] = coord2

    resp = await wallpaper_client.post(
        f"/api/digital_frames/walls/{wall_id}/wallpaper",
        json={
            "image_id": image_id,
            "image_rect": {"x": 0.0, "y": 0.0, "width": 2000.0, "height": 1600.0},
        },
    )

    assert resp.status == 200
    body = await resp.json()
    assert body["frames_failed"] == 1
    assert len(coord2.sent) == 1
    results_by_entry = {r["entry_id"]: r for r in body["results"]}
    assert results_by_entry["frame-1"]["sent"] is False
    assert "frame unreachable" in results_by_entry["frame-1"]["message"]
    assert results_by_entry["frame-2"]["sent"] is True
