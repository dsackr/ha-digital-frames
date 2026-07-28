"""DataUpdateCoordinator for local Meural Canvas frames (FramePort Phase 3)."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import aiohttp

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_REFRESH,
    API_RESTART,
    API_SLEEP,
    CONF_HOST,
    CONF_ORIENTATION,
    CONF_ORIENTATION_FOLLOW_DEVICE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ORIENTATION_LANDSCAPE,
    ORIENTATION_PORTRAIT,
)
from .meural import (
    meural_get_backlight,
    meural_is_sleeping,
    meural_orientation_from_payload,
    meural_resume,
    meural_set_backlight,
    meural_set_orientation,
    meural_suspend,
    meural_system_info,
    parse_meural_system_stats,
    probe_meural,
    send_meural_postcard,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_PREVIEW_STORE_VERSION = 2
# Cap persisted last-wire JPEG so Store stays reasonable (~2.5MB binary).
_MAX_WIRE_STORE_BYTES = 2_500_000

# Fraimic service endpoints → Meural local control_command paths.
_CMD_MAP = {
    API_SLEEP: "suspend",
    "/api/sleep": "suspend",
    "sleep": "suspend",
    "/api/wake": "resume",
    "wake": "resume",
    API_REFRESH: "resume",
    "/api/refresh": "resume",
    "refresh": "resume",
}


class MeuralCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls a single local Meural and delivers JPEG postcards.

    Duck-types the DigitalFramesCoordinator surface used by scenes, library send,
    walls list, and preview storage so core product code stays driver-agnostic.

    Orientation note: firmware keeps orientation-scoped galleries (e.g.
    Recents). Physically rotating the Canvas swaps to the last *app/cloud*
    image for that hang — not our postcard. When hang changes we re-push our
    last library image (or last wire bytes) so HA content stays on screen.
    """

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.host: str = config_entry.data[CONF_HOST]
        self.device_key: str = config_entry.data.get("device_key", "") or f"meural:{self.host}"

        scan_seconds: int = config_entry.options.get(
            "scan_interval", DEFAULT_SCAN_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} meural {self.host}",
            update_interval=timedelta(seconds=scan_seconds),
            config_entry=config_entry,
        )
        self.config_entry = config_entry

        self.last_image_id: str | None = None
        self.last_thumbnail: bytes | None = None
        self._last_wire_bytes: bytes | None = None
        # Meural local postcard has no Fraimic-style sleep queue.
        self.pending_send: dict[str, Any] | None = None
        self._redisplay_lock = asyncio.Lock()

        self._preview_store = Store(
            hass,
            _PREVIEW_STORE_VERSION,
            f"{DOMAIN}_meural_preview_{config_entry.entry_id}",
        )

    async def async_load_last_image(self) -> None:
        data = await self._preview_store.async_load()
        if not isinstance(data, dict):
            return
        import base64  # noqa: PLC0415

        self.last_image_id = data.get("image_id")
        thumb_b64 = data.get("thumbnail_b64")
        if thumb_b64:
            try:
                self.last_thumbnail = base64.b64decode(thumb_b64)
            except Exception:  # noqa: BLE001
                self.last_thumbnail = None
        wire_b64 = data.get("wire_b64")
        if wire_b64:
            try:
                self._last_wire_bytes = base64.b64decode(wire_b64)
            except Exception:  # noqa: BLE001
                self._last_wire_bytes = None

    async def async_load_pending_send(self) -> None:
        """No-op: Meural driver does not queue sends on sleep."""
        return

    async def async_set_last_image(
        self,
        *,
        image_id: str | None = None,
        thumbnail: bytes | None = None,
        wire_bytes: bytes | None = None,
    ) -> None:
        import base64  # noqa: PLC0415

        self.last_image_id = image_id
        self.last_thumbnail = thumbnail
        if wire_bytes is not None:
            self._last_wire_bytes = (
                wire_bytes if len(wire_bytes) <= _MAX_WIRE_STORE_BYTES else None
            )
        await self._preview_store.async_save(
            {
                "image_id": image_id,
                "thumbnail_b64": (
                    base64.b64encode(thumbnail).decode("ascii") if thumbnail else None
                ),
                "wire_b64": (
                    base64.b64encode(self._last_wire_bytes).decode("ascii")
                    if self._last_wire_bytes
                    else None
                ),
            }
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Poll Meural over LAN.

        Unreachable frames return offline data instead of raising UpdateFailed.
        Raising on first_refresh used to leave the config entry NotReady with
        no coordinator in hass.data while entity-registry rows remained —
        library send then failed with "No frame coordinator" for that entry_id.
        Postcard send still works whenever the host answers.
        """
        session = async_get_clientsession(self.hass)
        info = await probe_meural(session, self.host)
        if info is None:
            _LOGGER.debug("Meural at %s unreachable (keeping entry loaded)", self.host)
            return {
                "driver": "meural",
                "host": self.host,
                "identify": None,
                "firmware_version": None,
                "device_orientation": None,
                "ip_address": self.host,
                "backlight": None,
                "lux": None,
                "free_space_mb": None,
                "wifi_rssi": None,
                "wifi_ssid": None,
                "sleeping": None,
                "online": False,
            }

        system = await meural_system_info(session, self.host)
        device_orientation = meural_orientation_from_payload(
            system
        ) or meural_orientation_from_payload(info)
        stats = parse_meural_system_stats(system)

        wifi_ip: str | None = None
        if isinstance(info, dict) and info.get("wifi_ip"):
            wifi_ip = str(info["wifi_ip"])
        if wifi_ip is None and isinstance(system, dict):
            wifi_status = system.get("wifi_status")
            if isinstance(wifi_status, dict) and wifi_status.get("ip"):
                wifi_ip = str(wifi_status["ip"])

        bl = await meural_get_backlight(session, self.host)
        if bl is not None:
            stats["backlight"] = bl

        sleeping = await meural_is_sleeping(session, self.host)

        data: dict[str, Any] = {
            "driver": "meural",
            "host": self.host,
            "identify": info,
            "firmware_version": None,
            "device_orientation": device_orientation,
            "ip_address": wifi_ip or self.host,
            "backlight": stats["backlight"],
            "lux": stats["lux"],
            "free_space_mb": stats["free_space_mb"],
            "wifi_rssi": stats["wifi_rssi"],
            "wifi_ssid": stats["wifi_ssid"],
            "sleeping": sleeping,
            "online": True,
        }

        if system:
            data["system"] = system
            for key in ("version", "firmware", "fw_version", "sw_version"):
                if key in system and system[key]:
                    data["firmware_version"] = str(system[key])
                    break
            if not data.get("firmware_version") and system.get("version"):
                data["firmware_version"] = str(system["version"])

        if device_orientation in (ORIENTATION_PORTRAIT, ORIENTATION_LANDSCAPE):
            self.hass.async_create_task(
                self._async_maybe_follow_device_orientation(device_orientation)
            )
        return data

    async def _async_maybe_follow_device_orientation(self, device_orientation: str) -> None:
        """Mirror gsensor into options.

        Canvas firmware swaps to orientation-scoped Recents (often last official
        app content) on physical rotate, so HA content needs re-pushing for the
        new hang -- but not from here: async_update_entry schedules
        __init__.py's _async_update_listener for every registered listener on
        this entry regardless of who else also awaits a redisplay, and that
        listener already redisplays on this exact option change. Calling
        async_redisplay_last() directly here as well used to double-send the
        postcard (two full re-encodes, two POSTs, a visible double-redraw
        flash) every time the frame's orientation changed. Leave
        _async_update_listener as the single trigger.
        """
        entry = self.config_entry
        follow = entry.options.get(CONF_ORIENTATION_FOLLOW_DEVICE, True)
        if not follow:
            return
        if entry.options.get(CONF_ORIENTATION) == device_orientation:
            return
        self.hass.config_entries.async_update_entry(
            entry,
            options={
                **entry.options,
                CONF_ORIENTATION: device_orientation,
                CONF_ORIENTATION_FOLLOW_DEVICE: True,
            },
        )

    async def async_redisplay_last(self) -> bool:
        """Re-send last HA content for the current render_spec orientation.

        Prefers library ``last_image_id`` (re-encode for new aspect). Falls
        back to last wire JPEG if the send had no library id.

        Returns True if a postcard was attempted successfully.
        """
        async with self._redisplay_lock:
            image_id = self.last_image_id
            if image_id:
                library = self.hass.data.get(DOMAIN, {}).get("_library")
                if library is None:
                    _LOGGER.debug(
                        "Meural redisplay: no library for image_id=%s", image_id
                    )
                else:
                    try:
                        from .helpers import render_spec_for_hass_entry  # noqa: PLC0415
                        from .panel_codec import panel_codec_for_entry  # noqa: PLC0415

                        entry = self.config_entry
                        spec = render_spec_for_hass_entry(self.hass, entry)
                        try:
                            codec_id = panel_codec_for_entry(entry).id
                        except ValueError:
                            codec_id = "jpeg_q90"
                        wire = await library.async_get_bin_for_send(
                            image_id, spec, codec_id=codec_id
                        )
                        await self.async_send_image(wire)
                        await self.async_set_last_image(
                            image_id=image_id,
                            thumbnail=self.last_thumbnail,
                            wire_bytes=wire,
                        )
                        _LOGGER.info(
                            "Meural %s: redisplayed library image %s after orientation change",
                            self.host,
                            image_id,
                        )
                        return True
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.warning(
                            "Meural %s: redisplay from library failed (%s); "
                            "trying last wire bytes",
                            self.host,
                            err,
                        )

            if self._last_wire_bytes:
                try:
                    await self.async_send_image(self._last_wire_bytes)
                    _LOGGER.info(
                        "Meural %s: redisplayed last wire postcard after orientation change",
                        self.host,
                    )
                    return True
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "Meural %s: redisplay last wire failed: %s", self.host, err
                    )
                    return False

            _LOGGER.debug(
                "Meural %s: orientation changed but nothing to redisplay", self.host
            )
            return False

    async def async_config_entry_updated(
        self,
        hass: HomeAssistant,  # noqa: ARG002
        entry: ConfigEntry,
    ) -> None:
        new_host = entry.data.get(CONF_HOST, self.host)
        if new_host != self.host:
            _LOGGER.info("Meural coordinator host updated to %s", new_host)
            self.host = new_host
            await self.async_request_refresh()

    async def async_set_backlight(self, level: int) -> None:
        session = async_get_clientsession(self.hass)
        await meural_set_backlight(session, self.host, level)
        if self.data is not None:
            self.data = {**self.data, "backlight": max(0, min(100, int(level)))}
        self.async_update_listeners()

    async def async_suspend(self) -> None:
        session = async_get_clientsession(self.hass)
        await meural_suspend(session, self.host)
        if self.data is not None:
            self.data = {**self.data, "sleeping": True}
        self.async_update_listeners()

    async def async_resume(self) -> None:
        session = async_get_clientsession(self.hass)
        await meural_resume(session, self.host)
        if self.data is not None:
            self.data = {**self.data, "sleeping": False}
        self.async_update_listeners()

    async def async_set_device_orientation(self, orientation: str) -> None:
        session = async_get_clientsession(self.hass)
        await meural_set_orientation(session, self.host, orientation)

    def _image_content_type(self, image_bytes: bytes) -> str:
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        return "image/jpeg"

    async def async_send_image(self, image_bytes: bytes) -> int:
        """Deliver *image_bytes* to the Canvas.

        Always postcards over LAN first (immediate pixels). When a Meural
        cloud account is linked, also pin the image in a single-image cloud
        gallery and make that gallery live (no rotation). Fail-closed:
        cloud failure after a successful postcard still raises so the
        caller reports the send as failed.
        """
        session = async_get_clientsession(self.hass)
        if self.data and self.data.get("sleeping"):
            try:
                await meural_resume(session, self.host)
            except (aiohttp.ClientError, ValueError) as err:
                _LOGGER.debug("Meural resume-before-send: %s", err)

        content_type = self._image_content_type(image_bytes)
        await send_meural_postcard(
            session, self.host, image_bytes, content_type=content_type
        )
        if self.data is not None:
            self.data = {**self.data, "sleeping": False}

        await self._async_cloud_pin_after_postcard(
            image_bytes, content_type=content_type
        )
        return 200

    async def _async_cloud_pin_after_postcard(
        self,
        image_bytes: bytes,
        *,
        content_type: str,
    ) -> None:
        """If cloud is linked, pin permanently; raise on cloud failure."""
        from .meural_cloud import (  # noqa: PLC0415
            MeuralCloudError,
            gallery_orientation_for_hang,
            pin_gallery_name,
        )
        from .meural_cloud_store import async_get_meural_cloud_store  # noqa: PLC0415

        store = await async_get_meural_cloud_store(self.hass)
        if not store.is_linked:
            return

        client = store.get_client()
        if client is None:
            raise MeuralCloudError("Meural cloud linked but client unavailable")

        hang = None
        if self.data:
            hang = self.data.get("device_orientation") or self.data.get("orientation")
        if not hang:
            hang = self.config_entry.options.get(CONF_ORIENTATION)
        g_orient = gallery_orientation_for_hang(
            hang if isinstance(hang, str) else None
        )
        title = self.config_entry.title or self.host
        g_name = pin_gallery_name(title, g_orient)

        frame_state = store.frame_state(self.config_entry.entry_id)
        device_id = frame_state.get("device_id")
        serial = None
        if self.data and isinstance(self.data.get("identify"), dict):
            identify = self.data["identify"]
            serial = identify.get("serial") or identify.get("serialNumber")

        if device_id is None:
            dev = await client.find_device_for_host(self.host, serial=serial)
            if dev is None or dev.get("id") is None:
                raise MeuralCloudError(
                    f"No Meural cloud device matches LAN host {self.host!r}"
                )
            device_id = dev["id"]
            await store.async_update_frame_state(
                self.config_entry.entry_id, {"device_id": device_id}
            )
            frame_state = store.frame_state(self.config_entry.entry_id)

        pin_key = f"pin_{g_orient}"
        pin_meta = frame_state.get(pin_key) if isinstance(
            frame_state.get(pin_key), dict
        ) else {}
        prev_item = pin_meta.get("item_id")
        prev_gallery = pin_meta.get("gallery_id")

        result = await client.pin_image_on_device(
            device_id=device_id,
            image_bytes=image_bytes,
            gallery_name=g_name,
            gallery_orientation=g_orient,
            previous_item_id=prev_item,
            previous_gallery_id=prev_gallery,
            content_type=content_type,
            set_no_rotation=True,
        )
        await store.async_update_frame_state(
            self.config_entry.entry_id,
            {
                "device_id": device_id,
                pin_key: {
                    "item_id": result["item_id"],
                    "gallery_id": result["gallery_id"],
                    "gallery_name": result["gallery_name"],
                },
            },
        )
        _LOGGER.info(
            "Meural %s: cloud pin gallery %s item %s",
            self.host,
            result["gallery_id"],
            result["item_id"],
        )

    async def async_push_ha_album(
        self,
        album_name: str,
        image_payloads: list[tuple[bytes, str]],
        *,
        hang: str | None = None,
        image_duration_s: int = 1800,
    ) -> dict[str, Any]:
        """Mirror an HA library album to Meural and make it live (rotation on)."""
        from .meural_cloud import (  # noqa: PLC0415
            MeuralCloudError,
            album_gallery_name,
            gallery_orientation_for_hang,
        )
        from .meural_cloud_store import async_get_meural_cloud_store  # noqa: PLC0415

        store = await async_get_meural_cloud_store(self.hass)
        if not store.is_linked:
            raise MeuralCloudError(
                "Link a Meural / Netgear account in frame options first"
            )
        client = store.get_client()
        if client is None:
            raise MeuralCloudError("Meural cloud client unavailable")

        if hang is None and self.data:
            hang = self.data.get("device_orientation") or self.data.get("orientation")
        if hang is None:
            hang = self.config_entry.options.get(CONF_ORIENTATION)
        g_orient = gallery_orientation_for_hang(
            hang if isinstance(hang, str) else None
        )
        g_name = album_gallery_name(album_name, g_orient)

        frame_state = store.frame_state(self.config_entry.entry_id)
        device_id = frame_state.get("device_id")
        if device_id is None:
            serial = None
            if self.data and isinstance(self.data.get("identify"), dict):
                identify = self.data["identify"]
                serial = identify.get("serial") or identify.get("serialNumber")
            dev = await client.find_device_for_host(self.host, serial=serial)
            if dev is None or dev.get("id") is None:
                raise MeuralCloudError(
                    f"No Meural cloud device matches LAN host {self.host!r}"
                )
            device_id = dev["id"]

        album_key = f"album:{album_name}:{g_orient}"
        prev = frame_state.get(album_key) if isinstance(
            frame_state.get(album_key), dict
        ) else {}
        prev_ids = list(prev.get("item_ids") or [])

        result = await client.push_album_to_device(
            device_id=device_id,
            gallery_name=g_name,
            gallery_orientation=g_orient,
            image_payloads=image_payloads,
            previous_item_ids=prev_ids,
            enable_rotation=True,
            image_duration_s=image_duration_s,
        )
        await store.async_update_frame_state(
            self.config_entry.entry_id,
            {
                "device_id": device_id,
                album_key: {
                    "gallery_id": result["gallery_id"],
                    "gallery_name": result["gallery_name"],
                    "item_ids": result["item_ids"],
                },
            },
        )
        return result

    async def async_send_image_or_queue(
        self,
        image_bytes: bytes,
        *,
        image_id: str | None = None,
        thumbnail: bytes | None = None,
    ) -> dict[str, Any]:
        """Send immediately (postcard + optional cloud pin). No sleep queue.

        Fail-closed when cloud is linked: postcard alone is not enough.
        """
        from .meural_cloud import MeuralCloudError  # noqa: PLC0415

        try:
            await self.async_send_image(image_bytes)
        except MeuralCloudError as err:
            _LOGGER.error("Meural cloud pin to %s failed: %s", self.host, err)
            return {
                "success": False,
                "queued": False,
                "message": str(err),
                "postcard_ok": True,
                "cloud_ok": False,
            }
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.error("Meural send to %s failed: %s", self.host, err)
            return {"success": False, "queued": False, "message": str(err)}
        await self.async_set_last_image(
            image_id=image_id, thumbnail=thumbnail, wire_bytes=image_bytes
        )
        return {"success": True, "queued": False}

    async def async_send_command(self, endpoint: str) -> int:
        """Map Fraimic-style service endpoints onto Meural local commands."""
        key = (endpoint or "").strip()
        action = _CMD_MAP.get(key) or _CMD_MAP.get(key.lstrip("/"))
        if action == "suspend":
            await self.async_suspend()
            return 200
        if action == "resume":
            await self.async_resume()
            return 200
        if key in (API_RESTART, "/api/restart", "restart"):
            raise HomeAssistantError(
                "Restart is not supported on Meural Canvas (local API)"
            )
        raise HomeAssistantError(
            f"Unsupported Meural command endpoint: {endpoint!r}"
        )
