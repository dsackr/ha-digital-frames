"""The Fraimic integration."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    API_REFRESH,
    API_RESTART,
    API_SLEEP,
    CONF_HEIGHT,
    CONF_WIDTH,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import FraimicCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service schema definitions
# ---------------------------------------------------------------------------

_ENTRY_ID_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
    }
)

_SEND_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("media_path"): cv.string,
    }
)


# ---------------------------------------------------------------------------
# Integration setup / teardown
# ---------------------------------------------------------------------------


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Fraimic frame from a config entry."""

    coordinator = FraimicCoordinator(hass, entry)

    # Perform the first data fetch; raises ConfigEntryNotReady on failure so
    # HA will retry automatically.
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services once (only for the first entry; subsequent entries
    # reuse the same service handlers).
    if not hass.services.has_service(DOMAIN, "send_image"):
        _register_services(hass)

    # Re-register listener so option changes (e.g. scan_interval) take effect.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Fraimic config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

        # Remove the top-level domain dict when no entries remain.
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

            # Remove services when the last entry is gone.
            for service in ("send_image", "refresh", "sleep", "restart"):
                hass.services.async_remove(DOMAIN, service)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry option updates (e.g. scan_interval changes)."""
    await hass.config_entries.async_reload(entry.entry_id)


# ---------------------------------------------------------------------------
# Service helpers
# ---------------------------------------------------------------------------


def _get_coordinator(hass: HomeAssistant, entry_id: str) -> FraimicCoordinator:
    """Return the coordinator for the given entry_id, or raise."""
    try:
        return hass.data[DOMAIN][entry_id]  # type: ignore[return-value]
    except KeyError as err:
        raise HomeAssistantError(
            f"No Fraimic frame found with entry_id '{entry_id}'"
        ) from err


def _register_services(hass: HomeAssistant) -> None:
    """Register all Fraimic services."""

    async def _handle_restart(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data["entry_id"])
        await coordinator.async_send_command(API_RESTART)
        _LOGGER.info("Restart command sent to frame %s", coordinator.host)

    async def _handle_sleep(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data["entry_id"])
        await coordinator.async_send_command(API_SLEEP)
        _LOGGER.info("Sleep command sent to frame %s", coordinator.host)

    async def _handle_refresh(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data["entry_id"])
        await coordinator.async_send_command(API_REFRESH)
        _LOGGER.info("Refresh command sent to frame %s", coordinator.host)

    async def _handle_send_image(call: ServiceCall) -> None:
        entry_id: str = call.data["entry_id"]
        media_path: str = call.data["media_path"]

        coordinator = _get_coordinator(hass, entry_id)
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            raise HomeAssistantError(f"Config entry '{entry_id}' not found")

        width: int = entry.data[CONF_WIDTH]
        height: int = entry.data[CONF_HEIGHT]

        # Resolve a HA media-source path to an absolute filesystem path.
        # Paths starting with /media/ are served from hass.config.media_dir.
        if media_path.startswith("/media/"):
            abs_path = os.path.join(
                hass.config.media_dirs.get("local", hass.config.path("media")),
                media_path[len("/media/"):],
            )
        else:
            abs_path = media_path

        if not os.path.isfile(abs_path):
            raise HomeAssistantError(
                f"Media file not found: {abs_path}"
            )

        # Import here to avoid a hard dependency at module load time.
        from .image_converter import convert_image  # noqa: PLC0415

        try:
            image_bytes: bytes = await hass.async_add_executor_job(
                convert_image, abs_path, width, height
            )
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(
                f"Failed to convert image '{abs_path}': {err}"
            ) from err

        await coordinator.async_send_image(image_bytes)
        _LOGGER.info(
            "Image '%s' (%dx%d) sent to frame %s",
            abs_path,
            width,
            height,
            coordinator.host,
        )

    hass.services.async_register(
        DOMAIN, "restart", _handle_restart, schema=_ENTRY_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "sleep", _handle_sleep, schema=_ENTRY_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "refresh", _handle_refresh, schema=_ENTRY_ID_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "send_image", _handle_send_image, schema=_SEND_IMAGE_SCHEMA
    )
