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


def test_get_ble_status_no_adapter():
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_frame"
    entry.data = {"host": "192.168.1.195", "mac": "90:E5:B1:D6:E0:9C"}
    entry.options = {}

    coord = DigitalFramesCoordinator(hass, entry)
    mock_bluetooth = MagicMock()
    mock_bluetooth.async_scanner_count.return_value = 0

    with patch.dict(sys.modules, {"homeassistant.components.bluetooth": mock_bluetooth}):
        status = coord.get_ble_status()
        assert status["state"] == "no_adapter"
        assert status["detected"] is False


def test_get_ble_status_ready_by_address():
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_frame"
    entry.data = {"host": "192.168.1.195", "mac": "90:E5:B1:D6:E0:9C"}
    entry.options = {}

    coord = DigitalFramesCoordinator(hass, entry)
    mock_device = MagicMock()
    mock_device.address = "90:E5:B1:D6:E0:9C"
    mock_device.name = "frame-E09C"
    mock_device.rssi = -64

    mock_bluetooth = MagicMock()
    mock_bluetooth.async_scanner_count.return_value = 1
    mock_bluetooth.async_ble_device_from_address.return_value = mock_device

    with patch.dict(sys.modules, {"homeassistant.components.bluetooth": mock_bluetooth}):
        status = coord.get_ble_status()
        assert status["state"] == "ready"
        assert status["detected"] is True
        assert status["address"] == "90:E5:B1:D6:E0:9C"
        assert status["name"] == "frame-E09C"
        assert status["rssi"] == -64


def test_get_ble_status_ready_by_service_info():
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_frame"
    entry.data = {"host": "192.168.1.195", "mac": "90:E5:B1:D6:E0:9C"}
    entry.options = {}

    coord = DigitalFramesCoordinator(hass, entry)

    mock_service_info = MagicMock()
    mock_service_info.address = "90:E5:B1:D6:E0:9C"
    mock_service_info.name = "frame-E09C"
    mock_service_info.service_uuids = [DIGITAL_FRAMES_BLE_SERVICE_UUID]
    mock_service_info.rssi = -58

    mock_bluetooth = MagicMock()
    mock_bluetooth.async_scanner_count.return_value = 1
    mock_bluetooth.async_ble_device_from_address.return_value = None
    mock_bluetooth.async_discovered_service_info.return_value = [mock_service_info]

    with patch.dict(sys.modules, {"homeassistant.components.bluetooth": mock_bluetooth}):
        status = coord.get_ble_status()
        assert status["state"] == "ready"
        assert status["detected"] is True
        assert status["rssi"] == -58


def test_get_ble_status_standby():
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_frame"
    entry.data = {"host": "192.168.1.195", "mac": "90:E5:B1:D6:E0:9C"}
    entry.options = {}

    coord = DigitalFramesCoordinator(hass, entry)

    mock_bluetooth = MagicMock()
    mock_bluetooth.async_scanner_count.return_value = 1
    mock_bluetooth.async_ble_device_from_address.return_value = None
    mock_bluetooth.async_discovered_service_info.return_value = []

    with patch.dict(sys.modules, {"homeassistant.components.bluetooth": mock_bluetooth}):
        status = coord.get_ble_status()
        assert status["state"] == "standby"
        assert status["detected"] is False


def test_ble_wake_sensor():
    from custom_components.digital_frames.sensor import (
        DigitalFramesBleWakeSensor,
        DigitalFramesBatterySensor,
    )

    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_frame"
    entry.data = {"host": "192.168.1.195", "mac": "90:E5:B1:D6:E0:9C"}
    entry.options = {}

    coord = DigitalFramesCoordinator(hass, entry)
    coord.data = {"battery": {"percent": 85, "charging": False}, "online": True}

    # Ready state
    coord.get_ble_status = MagicMock(return_value={
        "state": "ready",
        "detected": True,
        "name": "frame-E09C",
        "address": "90:E5:B1:D6:E0:9C",
        "rssi": -62,
        "scanner_count": 1,
        "last_wake_sent": 1791655000.0,
        "last_wake_success": True,
    })

    sensor = DigitalFramesBleWakeSensor(coord, entry)
    assert sensor.name == "BLE Wake"
    assert sensor.native_value == "Ready"
    assert sensor.icon == "mdi:bluetooth-connect"
    attrs = sensor.extra_state_attributes
    assert attrs["ble_detected"] is True
    assert attrs["ble_rssi"] == -62
    assert attrs["ble_name"] == "frame-E09C"
    assert attrs["service_uuid"] == DIGITAL_FRAMES_BLE_SERVICE_UUID

    # Standby state
    coord.get_ble_status = MagicMock(return_value={
        "state": "standby",
        "detected": False,
        "scanner_count": 1,
    })
    assert sensor.native_value == "Standby"
    assert sensor.icon == "mdi:bluetooth"

    # Battery sensor also includes ble_wake in extra_state_attributes
    battery_sensor = DigitalFramesBatterySensor(coord, entry)
    bat_attrs = battery_sensor.extra_state_attributes
    assert bat_attrs["ble_wake"] == "standby"

    # BLE Wake and Queued Send sensors are available even when Wi-Fi polling failed
    coord.last_update_success = False
    assert sensor.available is True


def test_get_ble_status_matches_esp32_mac_offset():
    """ESP32 BLE MAC is typically Wi-Fi Station MAC + 2."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_frame"
    entry.data = {"host": "192.168.1.195", "mac": "84:F7:03:CA:4D:78"}
    entry.options = {}

    coord = DigitalFramesCoordinator(hass, entry)

    mock_service_info = MagicMock()
    mock_service_info.address = "84:F7:03:CA:4D:7A"  # +2 from 78
    mock_service_info.name = "fraimic-4d0f78"
    mock_service_info.service_uuids = [DIGITAL_FRAMES_BLE_SERVICE_UUID]
    mock_service_info.rssi = -65

    mock_bluetooth = MagicMock()
    mock_bluetooth.async_scanner_count.return_value = 1
    mock_bluetooth.async_ble_device_from_address.return_value = None
    mock_bluetooth.async_discovered_service_info.return_value = [mock_service_info]

    with patch.dict(sys.modules, {"homeassistant.components.bluetooth": mock_bluetooth}):
        status = coord.get_ble_status()
        assert status["state"] == "ready"
        assert status["detected"] is True
        assert status["address"] == "84:F7:03:CA:4D:7A"
        assert status["name"] == "fraimic-4d0f78"
        assert status["rssi"] == -65


@pytest.mark.asyncio
async def test_coordinator_retains_cached_telemetry_on_startup():
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_frame"
    entry.data = {"host": "192.168.1.195", "mac": "84:F7:03:CA:4D:78"}
    entry.options = {}

    coord = DigitalFramesCoordinator(hass, entry)
    coord.data = None
    coord._cached_telemetry = {"battery": {"percent": 72, "charging": False}}

    with patch("aiohttp.ClientSession.get", side_effect=TimeoutError()):
        stale = await coord._async_update_data()
        assert stale["online"] is False
        assert stale["battery"]["percent"] == 72


@pytest.mark.asyncio
async def test_handle_wake_service_invokes_ble_wake():
    from custom_components.digital_frames import _register_services

    hass = MagicMock()
    registered_services = {}

    def mock_register(domain, service, handler, schema=None):
        registered_services[service] = handler

    hass.services.async_register = mock_register

    _register_services(hass)
    assert "wake" in registered_services

    coord = MagicMock()
    coord.host = "192.168.1.29"
    coord.async_ble_wake = AsyncMock(return_value=True)

    call = MagicMock()
    call.data = {"device_id": "test_device"}

    with patch(
        "custom_components.digital_frames._get_coordinator_by_device_id",
        return_value=(coord, "test_entry"),
    ):
        await registered_services["wake"](call)
        coord.async_ble_wake.assert_called_once()





