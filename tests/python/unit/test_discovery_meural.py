"""Background subnet discovery dual-probes Meural (KPF 1).

If this silently breaks: Meurals never surface under Settings → Devices &
Services → Discovered; moved Meurals keep a stale host forever.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.digital_frames.const import (
    CONF_DEVICE_KEY,
    CONF_DRIVER,
    CONF_HOST,
    DOMAIN,
    DRIVER_FRAIMIC,
    DRIVER_MEURAL,
)
from custom_components.digital_frames.discovery import (
    _async_scan_once,
    _match_and_update_meural,
)


@pytest.mark.asyncio
async def test_scan_once_starts_meural_discovery_flow(hass, monkeypatch):
    meural_info = {"serial": "SN-MEURAL-1", "alias": "Kitchen"}

    async def _scan(local_ip, session, *, concurrency=64, include_meural=False):
        assert include_meural is True
        return [
            {
                "ip": "192.168.1.80",
                "info": meural_info,
                "driver": DRIVER_MEURAL,
            }
        ]

    monkeypatch.setattr(
        "custom_components.digital_frames.discovery.get_local_ip",
        lambda: "192.168.1.2",
    )
    monkeypatch.setattr(
        "custom_components.digital_frames.discovery.scan_subnet",
        _scan,
    )
    monkeypatch.setattr(
        "custom_components.digital_frames.discovery.async_get_clientsession",
        lambda hass: object(),
    )

    started: list[dict] = []

    async def _init(domain, context=None, data=None):
        started.append({"domain": domain, "context": context, "data": data})
        return MagicMock()

    hass.config_entries.flow.async_init = _init  # type: ignore[method-assign]

    await _async_scan_once(hass)

    assert len(started) == 1
    assert started[0]["domain"] == DOMAIN
    assert started[0]["context"]["source"] == "integration_discovery"
    assert started[0]["data"]["ip"] == "192.168.1.80"
    assert started[0]["data"]["driver"] == DRIVER_MEURAL
    assert started[0]["data"]["info"]["serial"] == "SN-MEURAL-1"


@pytest.mark.asyncio
async def test_scan_once_skips_configured_meural(hass, make_frame_entry, monkeypatch):
    entry = make_frame_entry(
        host="192.168.1.80",
        device_key="meural:SN-MEURAL-1",
        name="Kitchen Meural",
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_DRIVER: DRIVER_MEURAL},
    )

    async def _scan(local_ip, session, *, concurrency=64, include_meural=False):
        return [
            {
                "ip": "192.168.1.80",
                "info": {"serial": "SN-MEURAL-1"},
                "driver": DRIVER_MEURAL,
            }
        ]

    monkeypatch.setattr(
        "custom_components.digital_frames.discovery.get_local_ip",
        lambda: "192.168.1.2",
    )
    monkeypatch.setattr(
        "custom_components.digital_frames.discovery.scan_subnet",
        _scan,
    )
    monkeypatch.setattr(
        "custom_components.digital_frames.discovery.async_get_clientsession",
        lambda hass: object(),
    )

    started: list = []

    async def _init(*_a, **_k):
        started.append(True)
        return MagicMock()

    hass.config_entries.flow.async_init = _init  # type: ignore[method-assign]

    await _async_scan_once(hass)
    assert started == []


@pytest.mark.asyncio
async def test_scan_once_updates_meural_host_on_move(
    hass, make_frame_entry, monkeypatch
):
    entry = make_frame_entry(
        host="192.168.1.80",
        device_key="meural:SN-MEURAL-1",
        name="Kitchen Meural",
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_DRIVER: DRIVER_MEURAL},
    )

    async def _scan(local_ip, session, *, concurrency=64, include_meural=False):
        return [
            {
                "ip": "192.168.1.90",
                "info": {"serial": "SN-MEURAL-1"},
                "driver": DRIVER_MEURAL,
            }
        ]

    monkeypatch.setattr(
        "custom_components.digital_frames.discovery.get_local_ip",
        lambda: "192.168.1.2",
    )
    monkeypatch.setattr(
        "custom_components.digital_frames.discovery.scan_subnet",
        _scan,
    )
    monkeypatch.setattr(
        "custom_components.digital_frames.discovery.async_get_clientsession",
        lambda hass: object(),
    )

    started: list = []

    async def _init(*_a, **_k):
        started.append(True)
        return MagicMock()

    hass.config_entries.flow.async_init = _init  # type: ignore[method-assign]

    await _async_scan_once(hass)
    assert started == []
    assert entry.data[CONF_HOST] == "192.168.1.90"


@pytest.mark.asyncio
async def test_scan_once_still_discovers_fraimic(hass, monkeypatch):
    fraimic_info = {
        "device": {"device_key": "fraimic-key-1"},
        "wifi": {"mac": "aa:bb:cc:dd:ee:ff"},
    }

    async def _scan(local_ip, session, *, concurrency=64, include_meural=False):
        return [
            {
                "ip": "192.168.1.50",
                "info": fraimic_info,
                "driver": DRIVER_FRAIMIC,
            }
        ]

    monkeypatch.setattr(
        "custom_components.digital_frames.discovery.get_local_ip",
        lambda: "192.168.1.2",
    )
    monkeypatch.setattr(
        "custom_components.digital_frames.discovery.scan_subnet",
        _scan,
    )
    monkeypatch.setattr(
        "custom_components.digital_frames.discovery.async_get_clientsession",
        lambda hass: object(),
    )

    started: list[dict] = []

    async def _init(domain, context=None, data=None):
        started.append({"domain": domain, "context": context, "data": data})
        return MagicMock()

    hass.config_entries.flow.async_init = _init  # type: ignore[method-assign]

    await _async_scan_once(hass)
    assert len(started) == 1
    assert started[0]["data"]["driver"] == DRIVER_FRAIMIC
    assert started[0]["data"]["ip"] == "192.168.1.50"


def test_match_and_update_meural_by_unique():
    entry = SimpleNamespace(
        data={
            CONF_DRIVER: DRIVER_MEURAL,
            CONF_HOST: "192.168.1.10",
            CONF_DEVICE_KEY: "meural:ABC",
        }
    )
    updated: list = []

    def _update(e, data=None, **_k):
        if data is not None:
            e.data = data
        updated.append(data)

    fake_hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=_update)
    )

    matched = _match_and_update_meural(
        fake_hass, [entry], "192.168.1.20", "meural:ABC"
    )
    assert matched is entry
    assert entry.data[CONF_HOST] == "192.168.1.20"
    assert updated


def test_match_and_update_meural_ignores_fraimic():
    entry = SimpleNamespace(
        data={
            CONF_HOST: "192.168.1.10",
            CONF_DEVICE_KEY: "fraimic-key",
        }
    )
    fake_hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_update_entry=lambda *a, **k: None)
    )
    assert (
        _match_and_update_meural(fake_hass, [entry], "192.168.1.10", "meural:X")
        is None
    )
