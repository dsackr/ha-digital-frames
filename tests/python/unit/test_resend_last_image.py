"""Resend the last image sent to a frame (KPF 41).

Library sends are re-encoded from last_image_id. Direct uploads are
re-encoded from the saved original, not the preview thumbnail. Wire-only
sends (skills, messages) replay the full-resolution payload. A frame with
nothing sent raises a clear error. Asleep frames still queue.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.digital_frames.const import DOMAIN
from custom_components.digital_frames.http_api import (
    DigitalFramesResendImageView,
    DigitalFramesSendImageView,
)
from custom_components.digital_frames.last_sent import (
    NO_PREVIOUS_IMAGE,
    PREVIEW_ONLY,
    async_resend_last_image,
)


def _arm_online(coord):
    """Make push succeed and record the bytes that would hit the frame."""
    sent: list[bytes] = []

    async def _provision(*_args, **_kwargs):
        return True

    async def _send(image_bytes):
        sent.append(image_bytes)
        return 200

    coord.data = {"online": True}
    coord.async_provision_frame_pull = _provision
    coord.async_send_image = _send
    coord.async_clear_pull_bin = AsyncMock()
    return sent


async def test_resend_with_nothing_sent_raises(hass, make_coordinator, make_frame_entry):
    coord = make_coordinator(make_frame_entry())
    with pytest.raises(HomeAssistantError, match=NO_PREVIOUS_IMAGE):
        await async_resend_last_image(hass, coord)


async def test_preview_thumbnail_alone_is_not_resent(hass, make_coordinator, make_frame_entry):
    coord = make_coordinator(make_frame_entry())
    coord.last_thumbnail = b"tiny-preview-png"
    with pytest.raises(HomeAssistantError, match=PREVIEW_ONLY):
        await async_resend_last_image(hass, coord)


async def test_library_resend_reencodes_current_image(
    hass, make_coordinator, make_frame_entry
):
    coord = make_coordinator(make_frame_entry())
    sent = _arm_online(coord)
    await coord.async_send_image_or_queue(b"stale-wire", image_id="img-beach")

    library = MagicMock()
    library.async_get_bin_for_send = AsyncMock(return_value=b"FROM-LIBRARY")
    hass.data.setdefault(DOMAIN, {})["_library"] = library

    result = await async_resend_last_image(hass, coord)

    assert result["success"] is True
    assert result["queued"] is False
    assert sent[-1] == b"FROM-LIBRARY"
    assert b"stale-wire" == sent[0]
    library.async_get_bin_for_send.assert_awaited()
    assert library.async_get_bin_for_send.await_args.args[0] == "img-beach"


async def test_direct_upload_resend_reencodes_source_not_thumbnail(
    hass, make_coordinator, make_frame_entry
):
    coord = make_coordinator(make_frame_entry())
    sent = _arm_online(coord)
    await coord.async_send_image_or_queue(
        b"first-encode",
        thumbnail=b"low-res-thumb",
        source_bytes=b"original-photo",
    )

    with patch(
        "custom_components.digital_frames.panel_codec.encode_for_panel_with_preview",
        return_value=(b"reencoded-full", b"new-preview"),
    ):
        result = await async_resend_last_image(hass, coord)

    assert result["success"] is True
    assert sent[-1] == b"reencoded-full"
    assert b"low-res-thumb" not in sent
    # The original is kept so another resend can re-encode again.
    _wire, source = await _load(hass, coord)
    assert source == b"original-photo"


async def test_wire_only_resend_replays_full_payload_not_thumbnail(
    hass, make_coordinator, make_frame_entry
):
    coord = make_coordinator(make_frame_entry())
    sent = _arm_online(coord)
    await coord.async_send_image_or_queue(
        b"FULL-QUALITY-WIRE", thumbnail=b"low-res-thumb"
    )

    result = await async_resend_last_image(hass, coord)

    assert result["success"] is True
    assert result["bytes_sent"] == len(b"FULL-QUALITY-WIRE")
    assert sent[-1] == b"FULL-QUALITY-WIRE"


async def test_asleep_frame_queues_the_full_payload(
    hass, make_coordinator, make_frame_entry
):
    coord = make_coordinator(make_frame_entry(size="7.3", width=800, height=480))
    await coord.async_set_last_image(
        thumbnail=b"low-res-thumb", wire_bytes=b"FULL-QUALITY-WIRE"
    )

    async def _asleep(*_args, **_kwargs):
        return False

    coord.async_ble_wake = _asleep
    with patch(
        "custom_components.digital_frames.coordinator.get_url",
        return_value="http://homeassistant.local:8123",
    ):
        result = await async_resend_last_image(hass, coord)

    assert result["queued"] is True
    assert result["success"] is True
    assert coord._staged_bin == b"FULL-QUALITY-WIRE"
    assert coord._staged_bin != b"low-res-thumb"


async def test_library_miss_falls_back_to_saved_wire(
    hass, make_coordinator, make_frame_entry
):
    coord = make_coordinator(make_frame_entry())
    sent = _arm_online(coord)
    await coord.async_set_last_image(image_id="img-gone", wire_bytes=b"saved-wire")
    library = MagicMock()
    library.async_get_bin_for_send = AsyncMock(side_effect=FileNotFoundError("missing"))
    hass.data.setdefault(DOMAIN, {})["_library"] = library

    result = await async_resend_last_image(hass, coord)

    assert result["success"] is True
    assert sent[-1] == b"saved-wire"


async def test_resend_view_requires_a_frame_id():
    view = DigitalFramesResendImageView()
    request = MagicMock()
    request.app = {"hass": MagicMock()}
    request.json = AsyncMock(return_value={})
    response = await view.post(request)
    assert response.status == 400
    assert "required" in json.loads(response.body)["message"]


async def test_resend_view_no_previous_image_is_409(monkeypatch):
    view = DigitalFramesResendImageView()
    request = MagicMock()
    request.app = {"hass": MagicMock()}
    request.json = AsyncMock(return_value={"entry_id": "entry-1"})

    monkeypatch.setattr(
        "custom_components.digital_frames.http_api.resolve_frame_by_entity",
        lambda *_a, **_k: (MagicMock(), MagicMock()),
    )

    async def _none(*_a, **_k):
        raise HomeAssistantError(NO_PREVIOUS_IMAGE)

    monkeypatch.setattr(
        "custom_components.digital_frames.last_sent.async_resend_last_image",
        _none,
    )
    response = await view.post(request)
    assert response.status == 409
    assert NO_PREVIOUS_IMAGE in json.loads(response.body)["message"]


async def test_resend_view_returns_queued_payload(monkeypatch):
    view = DigitalFramesResendImageView()
    request = MagicMock()
    request.app = {"hass": MagicMock()}
    request.json = AsyncMock(return_value={"entry_id": "entry-1"})
    monkeypatch.setattr(
        "custom_components.digital_frames.http_api.resolve_frame_by_entity",
        lambda *_a, **_k: (MagicMock(), MagicMock()),
    )

    async def _queued(*_a, **_k):
        return {
            "success": True,
            "queued": True,
            "message": "Image staged for frame pull on next wake",
            "bytes_sent": 12,
        }

    monkeypatch.setattr(
        "custom_components.digital_frames.last_sent.async_resend_last_image",
        _queued,
    )
    response = await view.post(request)
    body = json.loads(response.body)
    assert response.status == 200
    assert body["queued"] is True
    assert body["bytes_sent"] == 12


async def test_send_image_view_passes_original_bytes_for_resend(monkeypatch):
    """Direct multipart upload must hand the original photo to the coordinator."""
    view = DigitalFramesSendImageView()
    raw = b"\x89PNG\r\n\x1a\noriginal-photo"

    class _File:
        def read(self):
            return raw

    class _Field:
        file = _File()

    hass = MagicMock()

    async def _exec(fn, *args):
        return fn(*args)

    hass.async_add_executor_job = _exec
    coord = MagicMock()
    coord.host = "192.168.1.50"
    coord.async_send_image_or_queue = AsyncMock(
        return_value={"success": True, "queued": False}
    )
    entry = MagicMock()

    monkeypatch.setattr(
        "custom_components.digital_frames.http_api.resolve_frame_by_entity",
        lambda *_a, **_k: (coord, entry),
    )
    monkeypatch.setattr(
        "custom_components.digital_frames.http_api.render_spec_for_hass_entry",
        lambda *_a, **_k: SimpleNamespace(width=1200, height=1600, rotation=0, locked=False),
    )
    monkeypatch.setattr(
        "custom_components.digital_frames.panel_codec.panel_codec_for_entry",
        lambda _entry: SimpleNamespace(id="spectra6"),
    )
    monkeypatch.setattr(
        "custom_components.digital_frames.panel_codec.encode_for_panel_with_preview",
        lambda *args, **_kwargs: (b"encoded-bin", b"preview-png"),
    )

    request = MagicMock()
    request.app = {"hass": hass}
    request.post = AsyncMock(return_value={"entry_id": "entry-1", "image": _Field()})

    response = await view.post(request)
    assert response.status == 200
    coord.async_send_image_or_queue.assert_awaited_once_with(
        b"encoded-bin", thumbnail=b"preview-png", source_bytes=raw
    )


async def _load(hass, coord):
    from custom_components.digital_frames.last_sent import async_load_last_sent

    return await async_load_last_sent(hass, coord.config_entry.entry_id)
