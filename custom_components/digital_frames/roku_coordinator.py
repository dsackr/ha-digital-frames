"""DataUpdateCoordinator for Roku TV (cast-via-media_player driver).

Roku has no local API to receive arbitrary image bytes the way Fraimic/
Meural/Samsung do. Instead this driver stages a PNG behind a short-lived
HA-hosted token URL (same pattern as ``samsung_coordinator.py``) and calls
HA core's own ``roku`` integration's ``media_player.play_media`` service,
which launches Roku's built-in "Roku Media Player" app pointed at that URL.
No Roku cloud account, no protocol of our own -- the transport is an HA
service call onto a `media_player.roku_*` entity the user already has.

Duck-types the Fraimic/Meural/Samsung coordinator surface used by library
send, scenes, walls, and preview storage.
"""

from __future__ import annotations

import base64
import logging
import secrets
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.network import get_url
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    API_REFRESH,
    API_RESTART,
    API_SLEEP,
    CONF_ROKU_ENTITY_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_PREVIEW_STORE_VERSION = 1
# Keep staged PNG fetchable while the Roku Media Player app loads it.
_CONTENT_TTL_SEC = 600


class RokuCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Cast images to a Roku by calling HA core's `roku` media_player."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.roku_entity_id: str = config_entry.data[CONF_ROKU_ENTITY_ID]
        # No IP/PIN of our own -- reuse the target entity_id as the stand-in
        # identity for the frame-coordinator duck-type check and command
        # logging (see http_api.py's _is_frame_coordinator).
        self.host: str = self.roku_entity_id

        scan_seconds: int = config_entry.options.get(
            "scan_interval", DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} roku {self.roku_entity_id}",
            update_interval=timedelta(seconds=scan_seconds),
            config_entry=config_entry,
        )
        self.config_entry = config_entry

        self.last_image_id: str | None = None
        self.last_thumbnail: bytes | None = None
        self.pending_send: dict[str, Any] | None = None

        self._content_token: str | None = None
        self._content_bytes: bytes | None = None
        self._content_expires: float = 0.0

        self._preview_store = Store(
            hass,
            _PREVIEW_STORE_VERSION,
            f"{DOMAIN}_roku_preview_{config_entry.entry_id}",
        )

    async def async_load_last_image(self) -> None:
        data = await self._preview_store.async_load()
        if not isinstance(data, dict):
            return
        self.last_image_id = data.get("image_id")
        thumb_b64 = data.get("thumbnail_b64")
        if thumb_b64:
            try:
                self.last_thumbnail = base64.b64decode(thumb_b64)
            except Exception:  # noqa: BLE001
                self.last_thumbnail = None

    async def async_load_pending_send(self) -> None:
        return

    async def async_set_last_image(
        self,
        *,
        image_id: str | None = None,
        thumbnail: bytes | None = None,
    ) -> None:
        self.last_image_id = image_id
        self.last_thumbnail = thumbnail
        await self._preview_store.async_save(
            {
                "image_id": image_id,
                "thumbnail_b64": (
                    base64.b64encode(thumbnail).decode("ascii") if thumbnail else None
                ),
            }
        )

    def stage_content(self, image_bytes: bytes) -> str:
        """Stage PNG bytes; return content token for the public fetch URL."""
        self._content_token = secrets.token_urlsafe(18)
        self._content_bytes = image_bytes
        self._content_expires = time.time() + _CONTENT_TTL_SEC
        return self._content_token

    def get_staged_content(self, token: str) -> bytes | None:
        if not token or token != self._content_token:
            return None
        if time.time() > self._content_expires:
            return None
        return self._content_bytes

    def content_url(self, token: str) -> str:
        base = get_url(
            self.hass,
            prefer_external=False,
            allow_cloud=False,
            allow_external=True,
        ).rstrip("/")
        return f"{base}/api/digital_frames/roku/{token}/content.png"

    async def _async_update_data(self) -> dict[str, Any]:
        state = self.hass.states.get(self.roku_entity_id)
        reachable = state is not None and state.state not in (
            "unavailable",
            "unknown",
        )
        return {
            "driver": "roku",
            "host": self.roku_entity_id,
            "reachable": reachable,
            "ip_address": None,
            "firmware_version": None,
            "device_orientation": None,
        }

    async def async_config_entry_updated(
        self,
        hass: HomeAssistant,  # noqa: ARG002
        entry: ConfigEntry,
    ) -> None:
        self.roku_entity_id = entry.data.get(CONF_ROKU_ENTITY_ID, self.roku_entity_id)
        self.host = self.roku_entity_id
        await self.async_request_refresh()

    async def async_send_image(self, image_bytes: bytes) -> int:
        """Stage PNG, cast via HA's roku `media_player.play_media`."""
        if self.hass.states.get(self.roku_entity_id) is None:
            raise HomeAssistantError(
                f"Roku media player {self.roku_entity_id} not found"
            )

        # Normalize to PNG if JPEG was somehow passed.
        if image_bytes[:2] == b"\xff\xd8":
            image_bytes = await self.hass.async_add_executor_job(
                _jpeg_to_png, image_bytes
            )
        token = self.stage_content(image_bytes)
        url = self.content_url(token)

        try:
            # HA core's `roku` integration has no dedicated "image" media
            # type; MediaType.URL/VIDEO both launch the Roku Media Player
            # app with t=v, which sniffs the fetched content itself -- this
            # is the documented community pattern for casting a still photo.
            await self.hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": self.roku_entity_id,
                    "media_content_id": url,
                    "media_content_type": "video",
                },
                blocking=True,
            )
        except Exception as err:
            _LOGGER.error("Roku cast to %s failed: %s", self.roku_entity_id, err)
            raise HomeAssistantError(f"Roku cast failed: {err}") from err

        return 200

    async def async_send_image_or_queue(
        self,
        image_bytes: bytes,
        *,
        image_id: str | None = None,
        thumbnail: bytes | None = None,
    ) -> dict[str, Any]:
        try:
            await self.async_send_image(image_bytes)
        except (HomeAssistantError, OSError, TimeoutError, ValueError) as err:
            return {"success": False, "queued": False, "message": str(err)}
        await self.async_set_last_image(image_id=image_id, thumbnail=thumbnail)
        return {"success": True, "queued": False}

    async def async_send_command(self, endpoint: str) -> int:
        key = (endpoint or "").strip()
        if key in (API_SLEEP, "/api/sleep", "sleep"):
            await self.hass.services.async_call(
                "media_player",
                "turn_off",
                {"entity_id": self.roku_entity_id},
                blocking=True,
            )
            return 200
        if key in (API_REFRESH, "/api/refresh", "refresh", "/api/wake", "wake"):
            await self.hass.services.async_call(
                "media_player",
                "turn_on",
                {"entity_id": self.roku_entity_id},
                blocking=True,
            )
            return 200
        if key in (API_RESTART, "/api/restart", "restart"):
            raise HomeAssistantError("Restart is not supported on Roku")
        raise HomeAssistantError(f"Unsupported Roku command: {endpoint!r}")


def _jpeg_to_png(jpeg_bytes: bytes) -> bytes:
    import io  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415

    img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
