"""Roku TV cast driver (KPF 36) — no push protocol, casts via HA core's
`roku` media_player.play_media.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.digital_frames.const import (
    CONF_DRIVER,
    CONF_ROKU_ENTITY_ID,
    DRIVER_ROKU,
    ROKU_SIZE_LABEL,
)
from custom_components.digital_frames.panel_codec import (
    CODEC_PNG,
    encode_for_panel,
    panel_codec_for_entry,
)
from custom_components.digital_frames.roku_coordinator import RokuCoordinator


def test_panel_codec_for_roku_entry():
    entry = SimpleNamespace(
        entry_id="r1",
        data={
            CONF_DRIVER: DRIVER_ROKU,
            "width": 1920,
            "height": 1080,
            "size": ROKU_SIZE_LABEL,
        },
    )
    assert panel_codec_for_entry(entry).id == CODEC_PNG
    assert panel_codec_for_entry(entry).preferred_payload == "png"


def test_encode_png_for_roku_geometry(sample_image_bytes):
    out = encode_for_panel(
        sample_image_bytes(400, 300),
        1920,
        1080,
        0,
        False,
        "fast",
        None,
        CODEC_PNG,
    )
    assert out[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(out) > 100


def _make_coordinator(hass=None):
    hass = hass or MagicMock()
    entry = MagicMock()
    entry.entry_id = "roku1"
    entry.data = {CONF_ROKU_ENTITY_ID: "media_player.living_room_roku"}
    entry.options = {}
    return RokuCoordinator(hass, entry)


def test_roku_coordinator_stages_content():
    coord = _make_coordinator()
    token = coord.stage_content(b"\x89PNG fake")
    assert coord.get_staged_content(token) == b"\x89PNG fake"
    assert coord.get_staged_content("wrong") is None


def test_roku_coordinator_host_is_entity_id():
    coord = _make_coordinator()
    assert coord.host == "media_player.living_room_roku"


async def test_async_send_image_calls_play_media(monkeypatch):
    hass = MagicMock()
    hass.states.get.return_value = SimpleNamespace(state="idle")
    hass.services.async_call = AsyncMock()
    hass.async_add_executor_job = AsyncMock()

    coord = _make_coordinator(hass)
    monkeypatch.setattr(coord, "content_url", lambda token: f"http://ha/{token}")

    status = await coord.async_send_image(b"\x89PNG\r\n\x1a\nfake")

    assert status == 200
    hass.services.async_call.assert_awaited_once()
    args, kwargs = hass.services.async_call.await_args
    assert args[0] == "media_player"
    assert args[1] == "play_media"
    call_data = args[2]
    assert call_data["entity_id"] == "media_player.living_room_roku"
    assert call_data["media_content_type"] == "video"
    assert call_data["media_content_id"].startswith("http://ha/")
    assert kwargs["blocking"] is True


async def test_async_send_image_missing_entity_raises():
    from homeassistant.exceptions import HomeAssistantError

    hass = MagicMock()
    hass.states.get.return_value = None

    coord = _make_coordinator(hass)
    with pytest.raises(HomeAssistantError):
        await coord.async_send_image(b"\x89PNG fake")


async def test_async_send_image_or_queue_never_queues(monkeypatch):
    hass = MagicMock()
    hass.states.get.return_value = SimpleNamespace(state="idle")
    hass.services.async_call = AsyncMock()

    coord = _make_coordinator(hass)
    monkeypatch.setattr(coord, "content_url", lambda token: f"http://ha/{token}")
    monkeypatch.setattr(coord, "async_set_last_image", AsyncMock())

    result = await coord.async_send_image_or_queue(
        b"\x89PNG\r\n\x1a\nfake", image_id="img1", thumbnail=b"thumb"
    )
    assert result == {"success": True, "queued": False}
    coord.async_set_last_image.assert_awaited_once_with(
        image_id="img1", thumbnail=b"thumb"
    )


async def test_async_send_image_or_queue_reports_failure():
    hass = MagicMock()
    hass.states.get.return_value = None

    coord = _make_coordinator(hass)
    result = await coord.async_send_image_or_queue(b"\x89PNG fake")
    assert result["success"] is False
    assert result["queued"] is False


async def test_async_send_command_sleep_turns_off():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    coord = _make_coordinator(hass)

    status = await coord.async_send_command("/api/sleep")
    assert status == 200
    hass.services.async_call.assert_awaited_once_with(
        "media_player",
        "turn_off",
        {"entity_id": "media_player.living_room_roku"},
        blocking=True,
    )


async def test_async_send_command_refresh_turns_on():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    coord = _make_coordinator(hass)

    status = await coord.async_send_command("/api/refresh")
    assert status == 200
    hass.services.async_call.assert_awaited_once_with(
        "media_player",
        "turn_on",
        {"entity_id": "media_player.living_room_roku"},
        blocking=True,
    )


async def test_async_send_command_restart_unsupported():
    from homeassistant.exceptions import HomeAssistantError

    coord = _make_coordinator()
    with pytest.raises(HomeAssistantError, match="not supported"):
        await coord.async_send_command("/api/restart")


async def test_async_send_command_unknown_raises():
    from homeassistant.exceptions import HomeAssistantError

    coord = _make_coordinator()
    with pytest.raises(HomeAssistantError, match="Unsupported"):
        await coord.async_send_command("/api/bogus")
