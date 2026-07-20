"""Periodic background discovery of frames on the local network.

DHCP discovery (config_flow.async_step_dhcp) only fires when HA happens to
observe a live DHCP handshake from a matching MAC OUI — a frame with an
existing lease, or a Wi-Fi module from an unlisted OUI batch, never triggers
it. This module closes that gap: a recurring subnet sweep that feeds every
genuinely new frame into HA's standard discovery pipeline
(SOURCE_INTEGRATION_DISCOVERY), so it surfaces on the Settings → Devices &
Services "Discovered" card and the "new devices discovered" notification
exactly like any other discoverable integration.

There is **no shared broadcast protocol** between Fraimic and Meural.
Discovery is active HTTP probing of the HA host's /24: ``GET /api/info``
for Fraimic-family frames and ``GET /remote/identify/`` for Meural Canvas
(local). Same sweep machinery; different per-host probes.

Registered from async_setup (domain-level, alongside the scenes-hub entry),
so discovery works from the very first restart after install — before any
frame is configured.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import SOURCE_INTEGRATION_DISCOVERY
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_DEVICE_KEY,
    CONF_DRIVER,
    CONF_HOST,
    DOMAIN,
    DRIVER_FRAIMIC,
    DRIVER_MEURAL,
    KIND_SCENES_HUB,
)
from .helpers import (
    device_key_from_info,
    get_local_ip,
    match_and_update_entry,
    scan_subnet,
)
from .meural import meural_unique_id

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=20)


@callback
def async_setup_discovery(hass: "HomeAssistant") -> None:
    """Register the periodic background scan (idempotent)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "_discovery_unsub" in domain_data:
        return

    # Skip-if-running rather than queue: a sweep that fires while the
    # previous one is still probing has nothing new to add.
    scan_lock = asyncio.Lock()

    async def _async_scan(_now=None) -> None:
        if scan_lock.locked():
            return
        async with scan_lock:
            try:
                await _async_scan_once(hass)
            except Exception:  # noqa: BLE001
                # A failed sweep must never kill the timer — the next
                # interval retries from scratch.
                _LOGGER.exception("Digital Frames background discovery scan failed")

    unsubs: list = []

    # First sweep as soon as HA is fully started (or immediately if the
    # integration loaded into an already-running instance, e.g. via a
    # reload), so a new install doesn't wait a full interval for its
    # first discovery.
    if hass.is_running:
        hass.async_create_task(_async_scan())
    else:

        async def _on_started(_event) -> None:
            await _async_scan()

        unsubs.append(
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_started)
        )

    unsubs.append(async_track_time_interval(hass, _async_scan, SCAN_INTERVAL))

    @callback
    def _on_stop(_event) -> None:
        for unsub in domain_data.pop("_discovery_unsub", []):
            unsub()

    unsubs.append(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop))
    domain_data["_discovery_unsub"] = unsubs

    # Exposed for the on-demand rescan endpoint below: frames sleep, so a
    # single boot-time sweep goes stale fast -- the panel re-runs the sweep
    # whenever it opens, keeping its discovery banner current.
    domain_data["_discovery_scan"] = _async_scan
    hass.http.register_view(DigitalFramesDiscoveryScanView())


class DigitalFramesDiscoveryScanView(HomeAssistantView):
    """POST /api/digital_frames/discovery/scan — run one discovery sweep now."""

    url = "/api/digital_frames/discovery/scan"
    name = "api:digital_frames:discovery:scan"
    requires_auth = True

    async def post(self, request):
        hass = request.app["hass"]
        # The sweep starts config flows, an admin-only capability -- mirror
        # that here rather than letting any authenticated user trigger it.
        if not request["hass_user"].is_admin:
            return self.json_message("Admin required", status_code=403)
        scan = hass.data.get(DOMAIN, {}).get("_discovery_scan")
        if scan is None:
            return self.json_message("Discovery not initialised", status_code=500)
        await scan()
        return self.json({"success": True})


def _match_and_update_meural(
    hass: "HomeAssistant",
    entries: list["ConfigEntry"],
    ip: str,
    unique: str,
) -> "ConfigEntry | None":
    """Return the configured Meural entry for *unique*/*ip*, updating host if moved."""
    for entry in entries:
        if entry.data.get(CONF_DRIVER) != DRIVER_MEURAL:
            continue
        entry_key = entry.data.get(CONF_DEVICE_KEY) or ""
        entry_host = entry.data.get(CONF_HOST)
        is_same = (entry_key and entry_key == unique) or (entry_host == ip)
        if not is_same:
            continue
        if entry_host != ip or entry_key != unique:
            _LOGGER.info(
                "Meural %s moved: %s → %s", unique, entry_host, ip
            )
            hass.config_entries.async_update_entry(
                entry,
                data={
                    **entry.data,
                    CONF_HOST: ip,
                    CONF_DEVICE_KEY: unique,
                },
            )
        return entry
    return None


async def _async_scan_once(hass: "HomeAssistant") -> None:
    """One subnet sweep: update moved frames, start flows for new ones.

    Dual-probes Fraimic + Meural (``include_meural=True``). Not a shared
    broadcast — sequential per-IP HTTP probes on the HA host's /24.
    """
    local_ip = await hass.async_add_executor_job(get_local_ip)
    found = await scan_subnet(
        local_ip, async_get_clientsession(hass), include_meural=True
    )
    if not found:
        return

    frame_entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get("kind") != KIND_SCENES_HUB
    ]

    for item in found:
        ip: str = item["ip"]
        info: dict[str, Any] = item["info"]
        driver = item.get("driver") or DRIVER_FRAIMIC
        try:
            if driver == DRIVER_MEURAL:
                unique = meural_unique_id(info, ip)
                if _match_and_update_meural(
                    hass, frame_entries, ip, unique
                ) is not None:
                    continue

                _LOGGER.info(
                    "Discovered new Meural at %s (unique_id=%s)", ip, unique
                )
                await hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": SOURCE_INTEGRATION_DISCOVERY},
                    data={
                        "ip": ip,
                        "info": info,
                        "driver": DRIVER_MEURAL,
                    },
                )
                continue

            key = device_key_from_info(info)
            if not key:
                continue
            # Configured frame (host refreshed in place if it moved)?
            if match_and_update_entry(hass, frame_entries, ip, info) is not None:
                continue

            _LOGGER.info(
                "Discovered new Fraimic frame at %s (device_key=%s)", ip, key
            )
            # Feeds HA's discovery pipeline; a flow already pending for
            # this device_key aborts itself via async_set_unique_id's
            # raise_on_progress, so rescans never stack duplicates.
            await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_INTEGRATION_DISCOVERY},
                data={
                    "ip": ip,
                    "info": info,
                    "driver": DRIVER_FRAIMIC,
                },
            )
        except Exception:  # noqa: BLE001
            # One bad frame (e.g. it went to sleep mid-probe) must not
            # kill the rest of the sweep.
            _LOGGER.exception("Failed to process discovered frame at %s", ip)
