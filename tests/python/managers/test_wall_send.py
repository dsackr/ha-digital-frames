"""DigitalFramesWallSendView (KPF 19/36): send an arbitrary batch of
{entry_id: mapping} to their frames in one call.

Exists because the Walls tab's "Send to Frames" button used to fan out
client-side, one fetch per frame, straight to /api/digital_frames/library/send
(plain image_id) or /api/digital_frames/skills/{id}/send (skill) -- but an
image_crop mapping (a wallpaper's per-frame slice, KPF 36) is an object, not
a string, so it never matched either of those and was silently skipped:
"Send to Frames" reported overall success while never touching that frame or
updating its thumbnail. This view lets the client hand the whole batch
(including image_crop mappings) to SceneManager.async_send_mappings in one
shot, the same executor scene activation/schedules/skill sends already use.
"""

from __future__ import annotations

import pytest
from homeassistant.setup import async_setup_component

from custom_components.digital_frames.const import DOMAIN
from custom_components.digital_frames.library import LibraryManager
from custom_components.digital_frames.scenes import SceneManager
from custom_components.digital_frames.walls import WallManager
from custom_components.digital_frames.walls_http import DigitalFramesWallSendView


class _FakeCoordinator:
    def __init__(self):
        self.sent = []

    async def async_send_image_or_queue(self, image_bytes, *, image_id=None, thumbnail=None):
        self.sent.append({"image_id": image_id, "image_bytes": image_bytes, "thumbnail": thumbnail})
        return {"queued": False}


@pytest.fixture
async def send_client(hass, hass_client):
    await async_setup_component(hass, "http", {})
    hass.http.register_view(DigitalFramesWallSendView())

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


async def _make_wall_with_image(hass, make_frame_entry, sample_image_bytes, *, count=2):
    entries = []
    for i in range(count):
        entry = make_frame_entry(entry_id=f"frame-{i}", width=1200, height=1600)
        entry.add_to_hass(hass)
        entries.append(entry)
        hass.data[DOMAIN][entry.entry_id] = _FakeCoordinator()

    wall_mgr = hass.data[DOMAIN]["_walls"]
    created = await wall_mgr.async_save_wall(
        "Living Room", {e.entry_id: {"x": 40.0 * (i + 1), "y": 40.0} for i, e in enumerate(entries)}
    )

    lib_mgr = hass.data[DOMAIN]["_library"]
    record = await lib_mgr.async_upload("bg.png", sample_image_bytes(2000, 1600), ["Backgrounds"])
    image_id = record.get("image_id") if isinstance(record, dict) else record.image_id

    return created["wall_id"], image_id, entries


async def test_wall_send_unknown_wall_returns_404(hass, send_client):
    resp = await send_client.post(
        "/api/digital_frames/walls/nonexistent-wall/send",
        json={"mappings": {"frame-1": "img-1"}},
    )
    assert resp.status == 404


async def test_wall_send_missing_mappings_returns_400(hass, send_client, make_frame_entry):
    wall_mgr = hass.data[DOMAIN]["_walls"]
    created = await wall_mgr.async_save_wall("Empty Wall", {})
    resp = await send_client.post(f"/api/digital_frames/walls/{created['wall_id']}/send", json={})
    assert resp.status == 400
    assert "mappings" in (await resp.json())["message"]


async def test_wall_send_empty_mappings_returns_400(hass, send_client, make_frame_entry):
    wall_mgr = hass.data[DOMAIN]["_walls"]
    created = await wall_mgr.async_save_wall("Empty Wall", {})
    resp = await send_client.post(
        f"/api/digital_frames/walls/{created['wall_id']}/send", json={"mappings": {}}
    )
    assert resp.status == 400


async def test_wall_send_image_crop_mapping_reaches_the_frame(
    hass, send_client, make_frame_entry, sample_image_bytes
):
    """The bug this view exists to fix: an image_crop mapping (a wallpaper
    slice) must actually reach the frame's coordinator, with a per-frame
    cropped thumbnail -- not be silently skipped."""
    wall_id, image_id, entries = await _make_wall_with_image(hass, make_frame_entry, sample_image_bytes)

    resp = await send_client.post(
        f"/api/digital_frames/walls/{wall_id}/send",
        json={
            "mappings": {
                entries[0].entry_id: {
                    "type": "image_crop",
                    "image_id": image_id,
                    "crop_box": [0.0, 0.0, 0.5, 1.0],
                },
            }
        },
    )

    assert resp.status == 200
    body = await resp.json()
    assert body["success"] is True
    assert body["frames_failed"] == 0
    assert body["results"] == [{"entry_id": entries[0].entry_id, "success": True}]

    coordinator = hass.data[DOMAIN][entries[0].entry_id]
    assert len(coordinator.sent) == 1
    # image_id omitted, per-frame thumbnail present -- same contract as the
    # immediate wallpaper "Send to Frames Now" push (KPF 36).
    assert coordinator.sent[0]["image_id"] is None
    assert coordinator.sent[0]["thumbnail"] is not None


async def test_wall_send_mixed_mapping_types_in_one_batch(
    hass, send_client, make_frame_entry, sample_image_bytes
):
    """A batch can mix a plain image_id, a skill, and an image_crop mapping
    -- exactly what the Walls tab's "Send to Frames" button now posts in
    one call instead of three separate client-side fan-outs."""
    wall_id, image_id, entries = await _make_wall_with_image(
        hass, make_frame_entry, sample_image_bytes, count=2
    )
    # A plain image_id needs an actual library image behind it too.
    lib_mgr = hass.data[DOMAIN]["_library"]
    record = await lib_mgr.async_upload("solo.png", sample_image_bytes(400, 300), ["Images"])
    solo_image_id = record.get("image_id") if isinstance(record, dict) else record.image_id

    resp = await send_client.post(
        f"/api/digital_frames/walls/{wall_id}/send",
        json={
            "mappings": {
                entries[0].entry_id: solo_image_id,
                entries[1].entry_id: {
                    "type": "image_crop",
                    "image_id": image_id,
                    "crop_box": [0.5, 0.0, 1.0, 1.0],
                },
            }
        },
    )

    assert resp.status == 200
    body = await resp.json()
    assert body["frames_failed"] == 0
    results_by_entry = {r["entry_id"]: r for r in body["results"]}
    assert results_by_entry[entries[0].entry_id]["success"] is True
    assert results_by_entry[entries[1].entry_id]["success"] is True


async def test_wall_send_failure_reported_not_masked_as_success(
    hass, send_client, make_frame_entry, sample_image_bytes
):
    wall_id, image_id, entries = await _make_wall_with_image(hass, make_frame_entry, sample_image_bytes)

    class _BrokenCoordinator:
        async def async_send_image_or_queue(self, *args, **kwargs):
            raise ConnectionError("frame unreachable")

    hass.data[DOMAIN][entries[0].entry_id] = _BrokenCoordinator()

    resp = await send_client.post(
        f"/api/digital_frames/walls/{wall_id}/send",
        json={"mappings": {entries[0].entry_id: image_id}},
    )

    assert resp.status == 200
    body = await resp.json()
    assert body["frames_failed"] == 1
    assert body["results"][0]["success"] is False
