"""DataUpdateCoordinator for Fraimic frames."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import aiohttp

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_IMAGE,
    API_INFO,
    CONF_HOST,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)


class FraimicCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls a single Fraimic frame for status data."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialise the coordinator."""
        self.config_entry = config_entry
        self.host: str = config_entry.data[CONF_HOST]

        # Allow the scan interval to be overridden via entry options.
        scan_seconds: int = config_entry.options.get(
            "scan_interval", DEFAULT_SCAN_INTERVAL
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {self.host}",
            update_interval=timedelta(seconds=scan_seconds),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base_url(self, endpoint: str) -> str:
        """Return the full URL for a given API endpoint."""
        return f"http://{self.host}{endpoint}"

    # ------------------------------------------------------------------
    # DataUpdateCoordinator protocol
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from the frame's /api/info endpoint."""
        session = async_get_clientsession(self.hass)
        url = self._base_url(API_INFO)

        try:
            async with session.get(url, timeout=_REQUEST_TIMEOUT) as response:
                response.raise_for_status()
                return await response.json()  # type: ignore[no-any-return]
        except aiohttp.ClientConnectionError as err:
            raise UpdateFailed(
                "Frame is unreachable — it may be sleeping or off-network"
            ) from err
        except TimeoutError as err:
            raise UpdateFailed(
                "Frame is unreachable — it may be sleeping (request timed out)"
            ) from err
        except aiohttp.ClientResponseError as err:
            raise UpdateFailed(
                f"Frame returned unexpected HTTP {err.status}"
            ) from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Unexpected error fetching frame data: {err}") from err

    # ------------------------------------------------------------------
    # Command helpers called from services / buttons
    # ------------------------------------------------------------------

    async def async_send_command(self, endpoint: str) -> int:
        """POST to the given endpoint and return the HTTP status code.

        Args:
            endpoint: API path, e.g. ``/api/restart``.

        Returns:
            HTTP status code from the frame.

        Raises:
            HomeAssistantError-compatible exceptions are not raised here;
            callers should handle aiohttp exceptions as appropriate.
        """
        session = async_get_clientsession(self.hass)
        url = self._base_url(endpoint)

        try:
            async with session.post(url, timeout=_REQUEST_TIMEOUT) as response:
                response.raise_for_status()
                status: int = response.status
                _LOGGER.debug("POST %s → %s", url, status)
                return status
        except aiohttp.ClientError as err:
            _LOGGER.error("Error sending command to %s: %s", url, err)
            raise

    async def async_send_image(self, image_bytes: bytes) -> int:
        """Upload a binary image to the frame.

        Posts *image_bytes* to ``/api/image`` with
        ``Content-Type: application/octet-stream``.

        Args:
            image_bytes: Raw image data in the frame's expected binary format.

        Returns:
            HTTP status code from the frame.
        """
        session = async_get_clientsession(self.hass)
        url = self._base_url(API_IMAGE)
        headers = {"Content-Type": "application/octet-stream"}

        try:
            async with session.post(
                url,
                data=image_bytes,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),  # uploads may take longer
            ) as response:
                response.raise_for_status()
                status: int = response.status
                _LOGGER.debug(
                    "Uploaded %d bytes to %s → %s", len(image_bytes), url, status
                )
                return status
        except aiohttp.ClientError as err:
            _LOGGER.error("Error uploading image to %s: %s", url, err)
            raise
