"""Meural cloud client + pin/album send path (KPF 32 extension)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.digital_frames.meural_cloud import (
    MeuralCloudAPIError,
    MeuralCloudClient,
    album_gallery_name,
    gallery_orientation_for_hang,
    pin_gallery_name,
)
from custom_components.digital_frames.const import (
    CONF_DRIVER,
    CONF_HOST,
    DRIVER_MEURAL,
)


def test_gallery_orientation_mapping():
    assert gallery_orientation_for_hang("portrait") == "vertical"
    assert gallery_orientation_for_hang("landscape") == "horizontal"
    assert gallery_orientation_for_hang(None) == "horizontal"
    assert gallery_orientation_for_hang("Portrait") == "vertical"


def test_pin_and_album_gallery_names():
    assert "Pin" in pin_gallery_name("Living Room", "horizontal")
    assert "landscape" in pin_gallery_name("Living Room", "horizontal")
    assert "portrait" in pin_gallery_name("Living Room", "vertical")
    assert "Family" in album_gallery_name("Family", "horizontal")


def _json_cm(status: int, payload: dict | list | None, text: str = ""):
    resp = AsyncMock()
    resp.status = status
    resp.text = AsyncMock(return_value=text or ("" if payload is None else "json"))
    resp.json = AsyncMock(return_value=payload if payload is not None else {})
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


@pytest.mark.asyncio
async def test_legacy_authenticate_token():
    session = MagicMock()
    session.post = MagicMock(
        return_value=_json_cm(200, {"data": {"token": "tok123"}})
    )
    client = MeuralCloudClient(session, username="u@x.com", password="secret")
    with patch.object(
        client, "_cognito_user_password", side_effect=Exception("no cognito")
    ):
        access, refresh = await client.async_login()
    assert access == "tok123"
    assert refresh is None
    assert client.access_token == "tok123"


@pytest.mark.asyncio
async def test_upload_item_returns_id():
    session = MagicMock()
    client = MeuralCloudClient(
        session, username="u", password="p", access_token="tok"
    )
    session.request = MagicMock(
        return_value=_json_cm(200, {"data": {"id": 42, "name": "x"}})
    )
    item = await client.upload_item(b"\xff\xd8\xffjpeg")
    assert item["id"] == 42
    session.request.assert_called()
    args, kwargs = session.request.call_args
    assert args[0] == "post"
    assert "items" in args[1]


@pytest.mark.asyncio
async def test_pin_image_on_device_replaces_previous():
    session = MagicMock()
    client = MeuralCloudClient(
        session, username="u", password="p", access_token="tok"
    )

    # Sequence of request() calls inside pin_image_on_device via helpers.
    client.upload_item = AsyncMock(return_value={"id": 200})
    client.ensure_named_gallery = AsyncMock(return_value={"id": 10, "name": "Pin"})
    client.get_gallery_items = AsyncMock(
        return_value=[{"id": 100}, {"id": 200}]
    )
    client.remove_item_from_gallery = AsyncMock()
    client.delete_item = AsyncMock()
    client.add_item_to_gallery = AsyncMock()
    client.device_load_gallery = AsyncMock()
    client.device_load_item = AsyncMock()
    client.update_device = AsyncMock()
    client.sync_device = AsyncMock()

    result = await client.pin_image_on_device(
        device_id=7,
        image_bytes=b"\xff\xd8\xff",
        gallery_name="Digital Frames · X · Pin · landscape",
        gallery_orientation="horizontal",
        previous_item_id=100,
        previous_gallery_id=10,
    )
    assert result["item_id"] == 200
    assert result["gallery_id"] == 10
    client.delete_item.assert_any_call(100)
    client.device_load_gallery.assert_awaited_with(7, 10)
    client.update_device.assert_awaited()
    opts = client.update_device.await_args.args[1]
    assert opts["imageDuration"] == 0
    assert opts["galleryRotation"] is False


@pytest.mark.asyncio
async def test_push_album_rejects_empty():
    client = MeuralCloudClient(
        MagicMock(), username="u", password="p", access_token="tok"
    )
    with pytest.raises(MeuralCloudAPIError, match="empty"):
        await client.push_album_to_device(
            device_id=1,
            gallery_name="Album",
            gallery_orientation="horizontal",
            image_payloads=[],
        )


@pytest.mark.asyncio
async def test_coordinator_send_fail_closed_on_cloud_error():
    from custom_components.digital_frames.meural_cloud import MeuralCloudError
    from custom_components.digital_frames.meural_coordinator import MeuralCoordinator

    hass = MagicMock()
    hass.data = {}
    entry = MagicMock()
    entry.entry_id = "meural1"
    entry.title = "Canvas"
    entry.data = {CONF_HOST: "192.168.1.32", CONF_DRIVER: DRIVER_MEURAL}
    entry.options = {}
    coord = MeuralCoordinator(hass, entry)
    coord.data = {"device_orientation": "landscape", "online": True}

    with (
        patch(
            "custom_components.digital_frames.meural_coordinator.send_meural_postcard",
            new=AsyncMock(return_value={"status": "pass"}),
        ),
        patch(
            "custom_components.digital_frames.meural_coordinator.meural_resume",
            new=AsyncMock(),
        ),
        patch.object(
            coord,
            "_async_cloud_pin_after_postcard",
            new=AsyncMock(side_effect=MeuralCloudError("cloud down")),
        ),
    ):
        result = await coord.async_send_image_or_queue(b"\xff\xd8\xffjpeg")

    assert result["success"] is False
    assert result.get("postcard_ok") is True
    assert result.get("cloud_ok") is False
    assert "cloud down" in result["message"]


@pytest.mark.asyncio
async def test_coordinator_send_postcard_only_when_unlinked():
    from custom_components.digital_frames.meural_coordinator import MeuralCoordinator

    hass = MagicMock()
    hass.data = {}
    entry = MagicMock()
    entry.entry_id = "meural1"
    entry.title = "Canvas"
    entry.data = {CONF_HOST: "192.168.1.32", CONF_DRIVER: DRIVER_MEURAL}
    entry.options = {}
    coord = MeuralCoordinator(hass, entry)
    coord.data = {"online": True}

    store = SimpleNamespace(is_linked=False)

    with (
        patch(
            "custom_components.digital_frames.meural_coordinator.send_meural_postcard",
            new=AsyncMock(return_value={"status": "pass"}),
        ),
        patch(
            "custom_components.digital_frames.meural_cloud_store.async_get_meural_cloud_store",
            new=AsyncMock(return_value=store),
        ),
        patch.object(coord, "async_set_last_image", new=AsyncMock()),
    ):
        result = await coord.async_send_image_or_queue(
            b"\xff\xd8\xffjpeg", image_id="img1"
        )

    assert result["success"] is True
