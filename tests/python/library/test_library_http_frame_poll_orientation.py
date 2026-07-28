"""Frame Information modal's Rediscover control (KPF 21): forces an
immediate accelerometer/gsensor re-read for one frame instead of waiting
for the next scheduled coordinator poll (up to scan_interval, default
300s) to see a fresh "Discovered" orientation after physically rotating a
frame.

If this silently breaks: the Rediscover button in the panel either does
nothing (stale reading shown until the next background poll) or 500s/404s
whenever a user clicks it.
"""

from __future__ import annotations

import pytest
from homeassistant.setup import async_setup_component

from custom_components.digital_frames.const import DOMAIN
from custom_components.digital_frames.library_http import (
    DigitalFramesFramePollOrientationView,
)


@pytest.fixture
async def poll_client(hass, hass_client):
    await async_setup_component(hass, "http", {})
    hass.http.register_view(DigitalFramesFramePollOrientationView())
    return await hass_client()


async def test_poll_orientation_forces_refresh_and_returns_reading(
    hass, poll_client, make_coordinator, make_frame_entry, monkeypatch
):
    coordinator = make_coordinator(make_frame_entry())
    hass.data.setdefault(DOMAIN, {})[coordinator.config_entry.entry_id] = coordinator

    refresh_calls = []

    async def _fake_refresh():
        refresh_calls.append(True)
        coordinator.data = {"device_orientation": "landscape"}

    monkeypatch.setattr(coordinator, "async_request_refresh", _fake_refresh)

    resp = await poll_client.post(
        "/api/digital_frames/frame/poll_orientation",
        json={"entry_id": coordinator.config_entry.entry_id},
    )

    assert resp.status == 200
    body = await resp.json()
    assert body == {"success": True, "device_orientation": "landscape"}
    assert refresh_calls == [True]


async def test_poll_orientation_unknown_entry_returns_404(hass, poll_client):
    resp = await poll_client.post(
        "/api/digital_frames/frame/poll_orientation",
        json={"entry_id": "does-not-exist"},
    )
    assert resp.status == 404


async def test_poll_orientation_missing_entry_id_returns_400(hass, poll_client):
    resp = await poll_client.post(
        "/api/digital_frames/frame/poll_orientation", json={}
    )
    assert resp.status == 400
