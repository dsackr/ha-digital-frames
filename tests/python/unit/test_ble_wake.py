"""Bluetooth Low Energy (BLE) on-demand wake (KPF 40)."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.digital_frames.const import (
    DIGITAL_FRAMES_BLE_SERVICE_UUID,
    DIGITAL_FRAMES_BLE_WAKE_CHAR_UUID,
    DIGITAL_FRAMES_BLE_STATUS_CHAR_UUID,
)
from custom_components.digital_frames.coordinator import DigitalFramesCoordinator


def test_ble_constants():
    assert DIGITAL_FRAMES_BLE_SERVICE_UUID == "df000001-0000-1000-8000-00805f9b34fb"
    assert DIGITAL_FRAMES_BLE_WAKE_CHAR_UUID == "df000002-0000-1000-8000-00805f9b34fb"
    assert DIGITAL_FRAMES_BLE_STATUS_CHAR_UUID == "df000003-0000-1000-8000-00805f9b34fb"


@pytest.mark.asyncio
async def test_async_ble_wake_no_scanners():
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_frame"
    entry.data = {"host": "192.168.1.195", "mac": "90:E5:B1:D6:E0:9C"}
    entry.options = {}

    coord = DigitalFramesCoordinator(hass, entry)

    mock_bluetooth = MagicMock()
    mock_bluetooth.async_scanner_count.return_value = 0

    with patch.dict(sys.modules, {"homeassistant.components.bluetooth": mock_bluetooth}):
        result = await coord.async_ble_wake()
        assert result is False


@pytest.mark.asyncio
async def test_async_ble_wake_device_found_and_woken():
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_frame"
    entry.data = {"host": "192.168.1.195", "mac": "90:E5:B1:D6:E0:9C"}
    entry.options = {}

    coord = DigitalFramesCoordinator(hass, entry)

    mock_ble_device = MagicMock()
    mock_ble_device.address = "90:E5:B1:D6:E0:9C"

    mock_bluetooth = MagicMock()
    mock_bluetooth.async_scanner_count.return_value = 1
    mock_bluetooth.async_ble_device_from_address.return_value = mock_ble_device

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    mock_bleak = MagicMock()
    mock_bleak.BleakClient.return_value = mock_client

    with patch.dict(
        sys.modules,
        {
            "homeassistant.components.bluetooth": mock_bluetooth,
            "bleak": mock_bleak,
        },
    ):
        result = await coord.async_ble_wake()
        assert result is True
        mock_client.write_gatt_char.assert_called_once_with(
            DIGITAL_FRAMES_BLE_WAKE_CHAR_UUID, b"\x01"
        )


@pytest.mark.asyncio
async def test_async_ble_wake_connection_failure():
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_frame"
    entry.data = {"host": "192.168.1.195", "mac": "90:E5:B1:D6:E0:9C"}
    entry.options = {}

    coord = DigitalFramesCoordinator(hass, entry)

    mock_ble_device = MagicMock()
    mock_ble_device.address = "90:E5:B1:D6:E0:9C"

    mock_bluetooth = MagicMock()
    mock_bluetooth.async_scanner_count.return_value = 1
    mock_bluetooth.async_ble_device_from_address.return_value = mock_ble_device

    mock_client = AsyncMock()
    mock_client.__aenter__.side_effect = RuntimeError("Bluetooth connection failed")

    mock_bleak = MagicMock()
    mock_bleak.BleakClient.return_value = mock_client

    with patch.dict(
        sys.modules,
        {
            "homeassistant.components.bluetooth": mock_bluetooth,
            "bleak": mock_bleak,
        },
    ):
        result = await coord.async_ble_wake()
        assert result is False


@pytest.mark.asyncio
async def test_async_send_image_with_ble_wake_success():
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_frame"
    entry.data = {"host": "192.168.1.195", "mac": "90:E5:B1:D6:E0:9C"}
    entry.options = {}

    coord = DigitalFramesCoordinator(hass, entry)
    coord.last_update_success = False

    coord.async_stage_pull_bin = AsyncMock()
    coord.async_set_last_image = AsyncMock()
    coord.async_provision_frame_pull = AsyncMock(return_value=False)
    coord.async_ble_wake = AsyncMock(return_value=True)
    coord.async_clear_pull_bin = AsyncMock()
    coord.async_send_image = AsyncMock()

    async def mock_refresh():
        coord.last_update_success = True

    coord.async_refresh = AsyncMock(side_effect=mock_refresh)

    res = await coord.async_send_image_or_queue(b"dummy_bytes")
    assert res["success"] is True
    assert res["queued"] is False
    assert res["delivery"] == "ble+push"
    coord.async_ble_wake.assert_called_once()
    coord.async_send_image.assert_called_once_with(b"dummy_bytes")


@pytest.mark.asyncio
async def test_async_send_image_with_ble_wake_fallback_pull():
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_frame"
    entry.data = {"host": "192.168.1.195", "mac": "90:E5:B1:D6:E0:9C"}
    entry.options = {}

    coord = DigitalFramesCoordinator(hass, entry)
    coord.last_update_success = False

    coord.async_stage_pull_bin = AsyncMock()
    coord.async_set_last_image = AsyncMock()
    coord.async_provision_frame_pull = AsyncMock(return_value=False)
    coord.async_ble_wake = AsyncMock(return_value=False)
    coord._set_pending = AsyncMock()

    res = await coord.async_send_image_or_queue(b"dummy_bytes")
    assert res["success"] is True
    assert res["queued"] is True
    assert res["delivery"] == "pull"
    coord.async_ble_wake.assert_called_once()
    coord._set_pending.assert_called_once()

