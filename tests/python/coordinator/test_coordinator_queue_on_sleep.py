"""Pull-first send + optional push (KPF 4).

Battery/clone frames deep-sleep; HA stages a Spectra .bin at a token URL
and the frame GETs it on wake. If the frame is online, HA also POSTs
/api/image for an immediate update and provisions pull URL + sleep/always-on.

Flagged as the core delivery primitive every send path funnels through.
"""

from __future__ import annotations

import base64
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.exceptions import HomeAssistantError


@pytest.fixture
def coordinator(make_coordinator, make_frame_entry):
    return make_coordinator(make_frame_entry())


def _mock_online_frame(aioclient_mock, host: str, *, image_status=200):
    """Frame answers provision + optional image push."""
    aioclient_mock.post(f"http://{host}/pullurl", status=200, text="ok")
    aioclient_mock.post(f"http://{host}/sleepconfig", status=200, text="ok")
    aioclient_mock.post(f"http://{host}/api/image", status=image_status)


def _mock_offline_frame(aioclient_mock, host: str):
    """Frame unreachable for provision and push."""
    aioclient_mock.post(
        f"http://{host}/pullurl", exc=aiohttp.ClientConnectionError()
    )
    aioclient_mock.post(
        f"http://{host}/sleepconfig", exc=aiohttp.ClientConnectionError()
    )
    aioclient_mock.post(
        f"http://{host}/api/image", exc=aiohttp.ClientConnectionError()
    )
    aioclient_mock.get(
        f"http://{host}/api/info", exc=aiohttp.ClientConnectionError()
    )


@pytest.fixture(autouse=True)
def _ha_internal_url(hass):
    """get_url() used by pull_bin_url needs a configured internal URL."""
    hass.config.internal_url = "http://homeassistant.local:8123"
    with patch(
        "custom_components.digital_frames.coordinator.get_url",
        return_value="http://homeassistant.local:8123",
    ):
        yield


async def test_online_frame_push_and_stage_pull(coordinator, aioclient_mock):
    _mock_online_frame(aioclient_mock, coordinator.host)

    result = await coordinator.async_send_image_or_queue(b"binary-image-data")

    assert result["success"] is True
    assert result["queued"] is False
    assert result.get("delivery") == "push+pull"
    assert coordinator.pending_send is None
    assert coordinator.get_pull_bin(coordinator.pull_token) is None


async def test_offline_frame_stages_pull_and_reports_queued(coordinator, aioclient_mock):
    # Genuinely unreachable: provision fails → pull-only success (staged bin).
    _mock_offline_frame(aioclient_mock, coordinator.host)

    result = await coordinator.async_send_image_or_queue(
        b"binary-image-data", image_id="img1"
    )

    assert result["success"] is True
    assert result["queued"] is True
    assert result.get("delivery") == "pull"
    assert coordinator.pending_send is not None
    assert coordinator.pending_send.get("pull_only") is True
    assert coordinator.pending_send["image_id"] == "img1"
    # Payload is staged on disk/token URL, not re-stored as multi-MB bin_b64.
    assert coordinator.pending_send.get("bin_b64") == ""
    assert coordinator.get_pull_bin(coordinator.pull_token) == b"binary-image-data"
    from custom_components.digital_frames.coordinator import _FAST_POLL_INTERVAL

    assert coordinator.update_interval == _FAST_POLL_INTERVAL


async def test_timeout_on_push_after_provision_queues_pull_only(
    coordinator, aioclient_mock
):
    aioclient_mock.post(f"http://{coordinator.host}/pullurl", status=200, text="ok")
    aioclient_mock.post(f"http://{coordinator.host}/sleepconfig", status=200, text="ok")
    aioclient_mock.post(f"http://{coordinator.host}/api/image", exc=TimeoutError())
    aioclient_mock.get(f"http://{coordinator.host}/api/info", exc=TimeoutError())

    result = await coordinator.async_send_image_or_queue(b"data")

    assert result["success"] is True
    assert result["queued"] is True
    assert result.get("delivery") == "pull"


async def test_timeout_but_frame_answers_probe_is_not_requeued(
    coordinator, aioclient_mock
):
    # 7.3" clone may block HTTP on e-ink redraw; follow-up /api/info means awake.
    aioclient_mock.post(f"http://{coordinator.host}/pullurl", status=200, text="ok")
    aioclient_mock.post(f"http://{coordinator.host}/sleepconfig", status=200, text="ok")
    aioclient_mock.post(f"http://{coordinator.host}/api/image", exc=TimeoutError())
    aioclient_mock.get(f"http://{coordinator.host}/api/info", json={})

    result = await coordinator.async_send_image_or_queue(b"data", image_id="img1")

    assert result["success"] is True
    assert result["queued"] is False
    assert result.get("unconfirmed") is True
    assert coordinator.last_image_id == "img1"
    from custom_components.digital_frames.coordinator import _FAST_POLL_INTERVAL

    # No stuck fast-poll for a completed (unconfirmed) delivery.
    assert coordinator.pending_send is None or coordinator.update_interval != _FAST_POLL_INTERVAL


async def test_rejected_push_still_succeeds_via_staged_pull(
    coordinator, aioclient_mock
):
    """Push 500 must not raise when pull stage already holds the image."""
    aioclient_mock.post(f"http://{coordinator.host}/pullurl", status=200, text="ok")
    aioclient_mock.post(f"http://{coordinator.host}/sleepconfig", status=200, text="ok")
    aioclient_mock.post(f"http://{coordinator.host}/api/image", status=500)

    result = await coordinator.async_send_image_or_queue(b"data", image_id="img1")

    assert result["success"] is True
    assert result.get("delivery") == "pull"
    assert coordinator.get_pull_bin(coordinator.pull_token) == b"data"


async def test_successful_poll_reprovisions_and_clears_pull_only_pending(
    coordinator, aioclient_mock
):
    _mock_offline_frame(aioclient_mock, coordinator.host)
    await coordinator.async_send_image_or_queue(b"data", image_id="img1")
    assert coordinator.pending_send is not None
    assert coordinator.pending_send.get("pull_only") is True

    aioclient_mock.clear_requests()
    aioclient_mock.post(f"http://{coordinator.host}/pullurl", status=200, text="ok")
    aioclient_mock.post(f"http://{coordinator.host}/sleepconfig", status=200, text="ok")
    aioclient_mock.get(f"http://{coordinator.host}/api/info", json={})

    await coordinator._async_update_data()
    await coordinator.hass.async_block_till_done()

    assert coordinator.pending_send is None


async def test_restart_mid_queue_is_hydrated_from_store(
    hass, make_coordinator, make_frame_entry, hass_storage
):
    entry = make_frame_entry()
    entry.add_to_hass(hass)
    key = f"digital_frames_pending_send_{entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {
            "schema": 2,
            "token": "abc123",
            "bin_b64": "",
            "pull_only": True,
            "image_id": "img-restart",
            "thumbnail_b64": None,
            "queued_at": 0,
        },
    }

    coordinator = make_coordinator(entry)
    await coordinator.async_load_pending_send()

    assert coordinator.pending_send is not None
    assert coordinator.pending_send["image_id"] == "img-restart"
    from custom_components.digital_frames.coordinator import _FAST_POLL_INTERVAL

    assert coordinator.update_interval == _FAST_POLL_INTERVAL


async def test_stale_schema_payload_is_discarded_on_load(
    hass, make_coordinator, make_frame_entry, hass_storage
):
    entry = make_frame_entry()
    entry.add_to_hass(hass)
    key = f"digital_frames_pending_send_{entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {"bin_b64": "xxx", "image_id": "old"},
    }

    coordinator = make_coordinator(entry)
    await coordinator.async_load_pending_send()

    assert coordinator.pending_send is None


async def test_pull_token_and_url_shape(coordinator):
    token = await coordinator.async_ensure_pull_token()
    assert token
    url = coordinator.pull_bin_url()
    assert token in url
    assert url.endswith("/image.bin")
    assert "/api/digital_frames/pull/" in url


async def test_provision_sends_always_on_flag(coordinator, aioclient_mock):
    aioclient_mock.post(
        f"http://{coordinator.host}/sleepconfig",
        status=200,
        text="OK sleep_minutes=30 active_window_sec=8 always_on=true",
    )
    aioclient_mock.post(f"http://{coordinator.host}/pullurl", status=200, text="ok")

    with patch.object(coordinator, "frame_always_on", return_value=True), patch.object(
        coordinator, "frame_sleep_minutes", return_value=30
    ):
        ok = await coordinator.async_provision_frame_pull()
    assert ok is True

    found = False
    for call in aioclient_mock.mock_calls:
        url = str(call[1]) if len(call) > 1 else ""
        if "sleepconfig" not in url:
            continue
        data = call[2] if len(call) > 2 else None
        body = data.decode() if isinstance(data, (bytes, bytearray)) else str(data or "")
        assert "always_on=1" in body
        assert "minutes=30" in body
        found = True
        break
    assert found, f"sleepconfig not called: {aioclient_mock.mock_calls}"


async def test_provision_sleepconfig_runs_even_if_pullurl_fails(
    coordinator, aioclient_mock
):
    """always_on must still be written when only sleepconfig succeeds."""
    aioclient_mock.post(
        f"http://{coordinator.host}/sleepconfig",
        status=200,
        text="OK always_on=true",
    )
    aioclient_mock.post(
        f"http://{coordinator.host}/pullurl", exc=aiohttp.ClientConnectionError()
    )

    with patch.object(coordinator, "frame_always_on", return_value=True):
        ok = await coordinator.async_provision_frame_pull()
    assert ok is True


async def test_pull_bin_view_clears_bin_on_get(coordinator, hass):
    from custom_components.digital_frames.http_api import DigitalFramesFramePullBinView
    from custom_components.digital_frames.const import DOMAIN
    from unittest.mock import MagicMock

    # 1. Stage the bin
    hass.data.setdefault(DOMAIN, {})[coordinator.config_entry.entry_id] = coordinator
    await coordinator.async_stage_pull_bin(b"binary-image-data")
    token = coordinator.pull_token
    assert coordinator.get_pull_bin(token) == b"binary-image-data"

    # 2. Build mock request
    mock_app = {"hass": hass}
    mock_request = MagicMock()
    mock_request.app = mock_app

    # 3. Call the GET view
    view = DigitalFramesFramePullBinView()
    response = await view.get(mock_request, token)

    assert response.status == 200
    assert response.body == b"binary-image-data"

    # 4. Wait for background task to complete clearing
    await hass.async_block_till_done()

    # 5. Verify it is now cleared
    assert coordinator.get_pull_bin(token) is None
