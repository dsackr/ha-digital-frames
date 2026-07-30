"""Network device_tracker wake → flush pending send (KPF 4).

Vendor-agnostic: any device_tracker whose IP or MAC matches the frame
(UniFi, Omada, ASUSWRT, …) transitioning not_home → home flushes a
queued image. Fast 30s frame polling is separate (advanced option).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import STATE_HOME, STATE_NOT_HOME


@pytest.fixture
def coordinator(make_coordinator, make_frame_entry):
    return make_coordinator(
        make_frame_entry(host="192.168.1.50", mac="aabbccddeeff")
    )


def test_find_tracker_by_ip(hass, coordinator):
    hass.states.async_set(
        "device_tracker.other",
        STATE_NOT_HOME,
        {"ip": "10.0.0.1", "mac": "112233445566"},
    )
    hass.states.async_set(
        "device_tracker.fraimic_living",
        STATE_NOT_HOME,
        {"ip": "192.168.1.50", "mac": "aa:bb:cc:dd:ee:ff"},
    )

    assert coordinator._find_matching_device_tracker() == "device_tracker.fraimic_living"


def test_find_tracker_by_mac_when_ip_differs(hass, coordinator):
    """DHCP may change IP; MAC is the stable identity."""
    hass.states.async_set(
        "device_tracker.frame_wifi",
        STATE_HOME,
        {"ip": "192.168.1.99", "mac": "AA:BB:CC:DD:EE:FF"},
    )

    assert coordinator._find_matching_device_tracker() == "device_tracker.frame_wifi"


def test_find_tracker_by_entity_id_mac_shape(hass, coordinator):
    hass.states.async_set("device_tracker.aa_bb_cc_dd_ee_ff", STATE_NOT_HOME, {})

    assert (
        coordinator._find_matching_device_tracker()
        == "device_tracker.aa_bb_cc_dd_ee_ff"
    )


def test_no_match_returns_none(hass, coordinator):
    hass.states.async_set(
        "device_tracker.phone",
        STATE_HOME,
        {"ip": "192.168.1.20", "mac": "ffffffffffff"},
    )

    assert coordinator._find_matching_device_tracker() is None


async def test_home_transition_flushes_pending(hass, coordinator):
    hass.states.async_set(
        "device_tracker.frame",
        STATE_NOT_HOME,
        {"ip": "192.168.1.50"},
    )
    coordinator.pending_send = {
        "schema": 2,
        "token": "t1",
        "pull_only": True,
        "image_id": "img1",
    }
    coordinator.async_setup_tracker_watch()
    assert coordinator._tracker_entity_id == "device_tracker.frame"

    with (
        patch.object(
            coordinator, "_async_flush_pending_send", new_callable=AsyncMock
        ) as flush,
        patch.object(
            coordinator, "async_request_refresh", new_callable=AsyncMock
        ) as refresh,
    ):
        hass.states.async_set(
            "device_tracker.frame",
            STATE_HOME,
            {"ip": "192.168.1.50"},
        )
        await hass.async_block_till_done()

        flush.assert_awaited_once()
        refresh.assert_awaited_once()


async def test_home_with_nothing_pending_still_refreshes_status(hass, coordinator):
    """Wake signal updates battery/wifi even when no image is queued."""
    hass.states.async_set(
        "device_tracker.frame",
        STATE_NOT_HOME,
        {"ip": "192.168.1.50"},
    )
    coordinator.pending_send = None
    coordinator.async_setup_tracker_watch()

    with (
        patch.object(
            coordinator, "_async_flush_pending_send", new_callable=AsyncMock
        ) as flush,
        patch.object(
            coordinator, "async_request_refresh", new_callable=AsyncMock
        ) as refresh,
    ):
        hass.states.async_set(
            "device_tracker.frame",
            STATE_HOME,
            {"ip": "192.168.1.50"},
        )
        await hass.async_block_till_done()

        flush.assert_not_awaited()
        refresh.assert_awaited_once()


async def test_already_home_on_bind_with_pending_flushes(hass, coordinator):
    hass.states.async_set(
        "device_tracker.frame",
        STATE_HOME,
        {"ip": "192.168.1.50"},
    )
    coordinator.pending_send = {
        "schema": 2,
        "token": "t1",
        "pull_only": True,
        "image_id": "img1",
    }

    with (
        patch.object(
            coordinator, "_async_flush_pending_send", new_callable=AsyncMock
        ) as flush,
        patch.object(
            coordinator, "async_request_refresh", new_callable=AsyncMock
        ) as refresh,
    ):
        coordinator.async_setup_tracker_watch()
        await hass.async_block_till_done()

        flush.assert_awaited_once()
        refresh.assert_awaited_once()


async def test_teardown_cancels_listener(hass, coordinator):
    hass.states.async_set(
        "device_tracker.frame",
        STATE_NOT_HOME,
        {"ip": "192.168.1.50"},
    )
    coordinator.pending_send = {
        "schema": 2,
        "token": "t1",
        "pull_only": True,
        "image_id": "img1",
    }
    coordinator.async_setup_tracker_watch()
    coordinator.async_teardown_tracker_watch()
    assert coordinator._tracker_entity_id is None
    assert coordinator._unsub_tracker is None

    with patch.object(
        coordinator, "_async_flush_pending_send", new_callable=AsyncMock
    ) as flush:
        hass.states.async_set(
            "device_tracker.frame",
            STATE_HOME,
            {"ip": "192.168.1.50"},
        )
        await hass.async_block_till_done()

        flush.assert_not_awaited()
