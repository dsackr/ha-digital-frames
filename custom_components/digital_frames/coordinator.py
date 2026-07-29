"""DataUpdateCoordinator for Fraimic frames."""

from __future__ import annotations

import base64
import logging
import os
import secrets
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import aiohttp

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import get_url
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_FRAME_PULL_BIN,
    API_IMAGE,
    API_INFO,
    CACHE_DIRNAME,
    CONF_DEVICE_KEY,
    CONF_FRAME_ALWAYS_ON,
    CONF_FRAME_SLEEP_MINUTES,
    CONF_HOST,
    CONF_MAC,
    CONF_PULL_TOKEN,
    DEFAULT_FRAME_ALWAYS_ON,
    DEFAULT_FRAME_SLEEP_MINUTES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FRAME_API_PULLURL,
    FRAME_API_SLEEPCONFIG,
    CONF_WIDTH,
    CONF_HEIGHT,
)
from .helpers import (
    device_key_from_info,
    dimensions_from_info,
    find_frame_by_device_key,
    get_local_ip,
    mac_from_info,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
# After this many consecutive poll failures, trigger a subnet rescan to find
# the frame at its new IP.
_FAILURES_BEFORE_RESCAN = 3

# Storage.Store (writes to .storage/, not entry.options) for the Frames panel
# thumbnail hint. One file per config entry, keyed on entry_id, so concurrent
# sends to different frames never race on the same file. Deliberately not
# entry.options -- that would trigger a full entry reload on every single
# send (see DigitalFramesOrientationSelect for why that reload is fine there but
# not here).
_PREVIEW_STORE_VERSION = 1

# Same one-file-per-entry shape as the preview store above, but for a queued
# send awaiting delivery -- see async_send_image_or_queue.
_PENDING_STORE_VERSION = 1

# Schema stamp inside the pending payload itself (not the Store version, whose
# mismatch handling raises during load). Payloads written by v0.12.39/0.12.40
# have no stamp and are discarded on load: those versions could persist a
# stale-packed bin (see library.py's _migrate_stale_cache) and then redeliver
# it forever.
_PENDING_SCHEMA = 2

# While a send is queued, poll much more often than the user's configured
# scan_interval so a frame that wakes gets its image promptly instead of
# waiting up to the full (default 5 minute) interval. Fraimic frames have no
# documented wake-schedule/next-wake-time API to plan around instead -- the
# official REST API guide says a sleeping frame is "completely unreachable"
# until physically tapped -- so opportunistic polling is the only mechanism
# available.
_FAST_POLL_INTERVAL = timedelta(seconds=30)


class DigitalFramesCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls a single Fraimic frame for status data."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialise the coordinator."""
        self.config_entry = config_entry
        self.host: str = config_entry.data[CONF_HOST]
        self.device_key: str = config_entry.data.get(CONF_DEVICE_KEY, "")

        scan_seconds: int = config_entry.options.get(
            "scan_interval", DEFAULT_SCAN_INTERVAL
        )
        self._normal_update_interval = timedelta(seconds=scan_seconds)

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {self.host}",
            update_interval=self._normal_update_interval,
        )

        self._consecutive_failures: int = 0
        self._rescan_in_progress: bool = False

        # Library image_id of the last successful send (Library "Send to
        # Canvas" or a Scene push -- both know the image_id up front). UI-only
        # preview hint for the Frames dashboard card; persisted via
        # _preview_store (see async_load_last_image/async_set_last_image)
        # rather than entry.options so it survives a restart without
        # triggering an entry reload on every send. Not set by the raw-upload
        # HTTP view or the send_image service, since those resolve a
        # media_content_id rather than a library image_id -- see
        # last_thumbnail below for how those paths still populate a preview.
        self.last_image_id: str | None = None

        # Small PNG preview of the last-sent image, for callers that have no
        # Library image_id to hand -- currently the generic send_image
        # service and the raw-upload card path, both of which resolve
        # something other than a Library-managed image (see
        # _handle_send_image in __init__.py and DigitalFramesSendImageView in
        # http_api.py). Mutually exclusive with last_image_id: whichever send
        # path ran most recently clears the other, so the Frames panel never
        # shows a stale thumbnail from a different source. Also persisted via
        # _preview_store.
        self.last_thumbnail: bytes | None = None

        self._preview_store: Store = Store(
            hass, _PREVIEW_STORE_VERSION, f"{DOMAIN}_last_image_{config_entry.entry_id}"
        )

        # Stable pull-token for HA-hosted Spectra .bin (frame GETs this on wake).
        # Created once and stored on the config entry; see ensure_pull_token().
        self.pull_token: str = str(config_entry.data.get(CONF_PULL_TOKEN) or "")
        self._staged_bin: bytes | None = None
        self._pull_bin_path = Path(
            hass.config.path(CACHE_DIRNAME, "pull", f"{config_entry.entry_id}.bin")
        )

        # The newest image this frame hasn't confirmed receiving yet -- set
        # by async_send_image_or_queue when a send hits an unreachable
        # (sleeping) frame, and flushed by the poll loop once the frame
        # answers again. Exactly one entry, never a list: a later send always
        # overwrites an earlier still-pending one ("latest wins" -- confirmed
        # with the user, since a frame that slept through several sends
        # should end up showing the newest one, not flash through stale
        # intermediates). "token" lets _clear_pending_if_current tell a
        # slow in-flight send apart from a newer one that has since replaced
        # it, so a race can never wipe out the fresher entry.
        self.pending_send: dict[str, Any] | None = None
        self._pending_store: Store = Store(
            hass, _PENDING_STORE_VERSION, f"{DOMAIN}_pending_send_{config_entry.entry_id}"
        )
        self._flushing: bool = False

    async def async_load_last_image(self) -> None:
        """Hydrate last_image_id/last_thumbnail from disk. Call this once
        during setup, before the Frames panel can query /api/digital_frames/frames,
        so the thumbnail survives a Home Assistant restart instead of
        dropping back to the generic icon until the next send."""
        try:
            data = await self._preview_store.async_load()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to load cached frame preview for %s: %s", self.host, err)
            return
        if not data:
            return
        self.last_image_id = data.get("last_image_id")
        thumb_b64 = data.get("last_thumbnail_b64")
        if thumb_b64:
            try:
                self.last_thumbnail = base64.b64decode(thumb_b64)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to decode cached frame preview for %s: %s", self.host, err
                )

    async def async_set_last_image(
        self, *, image_id: str | None = None, thumbnail: bytes | None = None
    ) -> None:
        """Record which image was last sent to this frame, for the Frames
        panel thumbnail, and persist it to disk so it survives a restart.
        Callers should pass exactly one of *image_id* / *thumbnail* -- the
        other is cleared, keeping last_image_id/last_thumbnail mutually
        exclusive (see their docstrings above)."""
        self.last_image_id = image_id
        self.last_thumbnail = thumbnail
        await self._preview_store.async_save(
            {
                "last_image_id": image_id,
                "last_thumbnail_b64": (
                    base64.b64encode(thumbnail).decode("ascii") if thumbnail else None
                ),
            }
        )

    # ------------------------------------------------------------------
    # Pull delivery (frame wakes and GETs packed .bin from HA)
    # ------------------------------------------------------------------

    async def async_ensure_pull_token(self) -> str:
        """Ensure this entry has a stable pull token; persist if new."""
        if self.pull_token:
            return self.pull_token
        token = secrets.token_urlsafe(18)
        self.pull_token = token
        new_data = {**self.config_entry.data, CONF_PULL_TOKEN: token}
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        return token

    def pull_bin_url(self) -> str:
        """Absolute URL the frame should GET for its current Spectra image."""
        token = self.pull_token
        if not token:
            raise HomeAssistantError("pull token not provisioned")
        try:
            base = get_url(
                self.hass,
                prefer_external=False,
                allow_cloud=False,
                allow_external=True,
            ).rstrip("/")
        except Exception:  # noqa: BLE001
            # Tests / misconfigured HA: fall back so staging never hard-fails.
            base = (
                str(getattr(self.hass.config, "internal_url", None) or "")
                or str(getattr(self.hass.config, "external_url", None) or "")
                or "http://homeassistant.local:8123"
            ).rstrip("/")
        path = API_FRAME_PULL_BIN.format(token=token)
        return f"{base}{path}"

    def get_pull_bin(self, token: str) -> bytes | None:
        """Return staged .bin for *token*, or None."""
        if not token or token != self.pull_token:
            return None
        if self._staged_bin is not None:
            return self._staged_bin
        # Cold path: disk (after restart, before first stage this session)
        try:
            if self._pull_bin_path.is_file():
                data = self._pull_bin_path.read_bytes()
                if data:
                    self._staged_bin = data
                    return data
        except OSError as err:
            _LOGGER.warning("Failed reading pull bin for %s: %s", self.host, err)
        return None

    async def async_load_pull_bin(self) -> None:
        """Hydrate in-memory staged bin from disk (if any)."""
        def _read() -> bytes | None:
            try:
                if self._pull_bin_path.is_file():
                    data = self._pull_bin_path.read_bytes()
                    return data or None
            except OSError:
                return None
            return None

        self._staged_bin = await self.hass.async_add_executor_job(_read)

    async def async_stage_pull_bin(self, image_bytes: bytes) -> str:
        """Persist *image_bytes* as the frame's current pull payload.

        Returns the absolute pull URL the frame should use.
        """
        await self.async_ensure_pull_token()
        self._staged_bin = image_bytes

        def _write() -> None:
            self._pull_bin_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._pull_bin_path.with_suffix(".tmp")
            tmp.write_bytes(image_bytes)
            os.replace(tmp, self._pull_bin_path)

        await self.hass.async_add_executor_job(_write)
        url = self.pull_bin_url()
        _LOGGER.info(
            "Staged %d-byte pull image for %s at %s",
            len(image_bytes),
            self.host,
            url,
        )
        return url

    def frame_sleep_minutes(self) -> int:
        """Deep-sleep / pull-check period (minutes) from entry options."""
        raw = self.config_entry.options.get(
            CONF_FRAME_SLEEP_MINUTES, DEFAULT_FRAME_SLEEP_MINUTES
        )
        try:
            mins = int(raw)
        except (TypeError, ValueError):
            mins = DEFAULT_FRAME_SLEEP_MINUTES
        return max(1, min(mins, 24 * 60))

    def frame_always_on(self) -> bool:
        """True when keep-awake / always-on is enabled in options."""
        return bool(
            self.config_entry.options.get(
                CONF_FRAME_ALWAYS_ON, DEFAULT_FRAME_ALWAYS_ON
            )
        )

    async def async_provision_frame_pull(
        self,
        *,
        sleep_minutes: int | None = None,
        active_sec: int = 120,
        always_on: bool | None = None,
    ) -> bool:
        """Tell the frame its HA pull URL and power mode.

        Best-effort: fails quietly if the frame is asleep / unreachable.
        Returns True if the pull URL POST succeeded.
        """
        if sleep_minutes is None:
            sleep_minutes = self.frame_sleep_minutes()
        if always_on is None:
            always_on = self.frame_always_on()

        try:
            url = self.pull_bin_url()
        except HomeAssistantError:
            await self.async_ensure_pull_token()
            url = self.pull_bin_url()

        session = async_get_clientsession(self.hass)
        # Power mode first so always_on/sleep stick even if pullurl fails.
        sleep_body = urlencode(
            {
                "minutes": str(sleep_minutes),
                "active_sec": str(active_sec),
                "always_on": "1" if always_on else "0",
            }
        )
        sleep_ok = False
        try:
            async with session.post(
                self._base_url(FRAME_API_SLEEPCONFIG),
                data=sleep_body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                sleep_text = await resp.text()
                sleep_ok = resp.status < 400
                if not sleep_ok:
                    _LOGGER.warning(
                        "Frame %s rejected sleepconfig (%s): %s",
                        self.host,
                        resp.status,
                        sleep_text[:200],
                    )
                elif always_on and "always_on=true" not in sleep_text.lower():
                    # Old firmware ignores always_on — surface that clearly.
                    _LOGGER.warning(
                        "Frame %s sleepconfig OK but always_on not confirmed "
                        "(response=%r). Flash fraimic-clone firmware that "
                        "supports always_on.",
                        self.host,
                        sleep_text[:120],
                    )
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug(
                "Could not provision sleepconfig on %s (likely asleep): %s",
                self.host,
                err,
            )
            return False

        pull_ok = False
        try:
            async with session.post(
                self._base_url(FRAME_API_PULLURL),
                data=urlencode({"url": url}),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                pull_ok = resp.status < 400
                if not pull_ok:
                    body = await resp.text()
                    _LOGGER.warning(
                        "Frame %s rejected pull URL provision (%s): %s",
                        self.host,
                        resp.status,
                        body[:200],
                    )
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.warning(
                "Frame %s sleepconfig applied but pullurl failed: %s",
                self.host,
                err,
            )
            # Still count as provisioned enough to try push if sleep stuck.
            return sleep_ok

        if sleep_ok or pull_ok:
            _LOGGER.info(
                "Provisioned frame %s: pull=%s sleep=%smin always_on=%s "
                "(sleepconfig=%s pullurl=%s)",
                self.host,
                url,
                sleep_minutes,
                always_on,
                sleep_ok,
                pull_ok,
            )
        return sleep_ok or pull_ok

    # ------------------------------------------------------------------
    # Queued sends -- delivered once a sleeping frame answers again
    # ------------------------------------------------------------------

    async def async_load_pending_send(self) -> None:
        """Hydrate a queued-but-undelivered send from disk. Call this once
        during setup, before the first refresh, so a queued send survives a
        Home Assistant restart instead of being silently dropped."""
        try:
            data = await self._pending_store.async_load()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to load pending send for %s: %s", self.host, err)
            return
        if not data:
            return
        if data.get("schema") != _PENDING_SCHEMA:
            # Written by a version without the schema stamp --
            # possibly a stale-packed bin caught in a redelivery loop. Drop it
            # rather than resume delivering a payload we can't trust.
            _LOGGER.warning(
                "Discarding queued send for %s persisted by an older version "
                "-- re-send the image if it's still wanted",
                self.host,
            )
            await self._pending_store.async_save(None)
            return
        self.pending_send = data
        self.update_interval = _FAST_POLL_INTERVAL

    async def _set_pending(self, payload: dict[str, Any]) -> None:
        self.pending_send = payload
        self.update_interval = _FAST_POLL_INTERVAL
        await self._pending_store.async_save(payload)
        self.async_update_listeners()

    async def _clear_pending_if_current(self, token: str) -> None:
        """Clear pending_send, but only if it's still the entry identified by
        *token* -- a newer send may have already replaced it while this one
        was in flight, and that newer entry must not be wiped out."""
        if self.pending_send is None or self.pending_send.get("token") != token:
            return
        self.pending_send = None
        self.update_interval = self._normal_update_interval
        await self._pending_store.async_save(None)
        self.async_update_listeners()

    async def async_clear_pull_bin(self, delay: int = 0) -> None:
        """Clear staged bin and pending send queue once successfully delivered."""
        if delay > 0:
            import asyncio  # noqa: PLC0415

            await asyncio.sleep(delay)
        self._staged_bin = None
        try:
            if self._pull_bin_path.is_file():
                await self.hass.async_add_executor_job(self._pull_bin_path.unlink)
        except OSError as err:
            _LOGGER.warning("Failed deleting pull bin for %s: %s", self.host, err)

        if self.pending_send is not None:
            self.pending_send = None
            self.update_interval = self._normal_update_interval
            await self._pending_store.async_save(None)
            self.async_update_listeners()

    async def async_send_image_or_queue(
        self,
        image_bytes: bytes,
        *,
        image_id: str | None = None,
        thumbnail: bytes | None = None,
    ) -> dict[str, Any]:
        """Stage *image_bytes* for frame pull, optionally push if online.

        Primary delivery for battery / clone frames is **pull**: HA stages a
        packed Spectra ``.bin`` at a stable token URL; the frame GETs it on
        each timer wake (same idea as official Fraimic cloud pull, and as
        Samsung's staged content-download URL).

        Secondary: if the frame is reachable, we still POST ``/api/image``
        so an already-awake panel updates immediately without waiting for
        the next sleep cycle. If push fails because the frame is asleep,
        the staged pull payload is enough — no duplicate push-queue required.

        Returns a dict with ``success``, ``queued`` (True when only staged
        for later pull), and optional ``delivery`` (``push`` / ``pull`` /
        ``push+pull``).
        """
        # 1) Always stage for pull first (survives HA restart + frame sleep).
        await self.async_stage_pull_bin(image_bytes)
        await self.async_set_last_image(image_id=image_id, thumbnail=thumbnail)

        # 2) If the frame happens to be online, refresh its pull URL config
        #    and try an immediate push.
        provisioned = await self.async_provision_frame_pull()

        token = uuid.uuid4().hex
        # Keep a lightweight pending record only for UI "queued" sensor when
        # we couldn't push — delivery is pull, not a re-POST of bin_b64.
        if not provisioned and not self.last_update_success:
            # Frame definitely asleep/unreachable: staged bin is the delivery mechanism.
            payload: dict[str, Any] = {
                "schema": _PENDING_SCHEMA,
                "token": token,
                "bin_b64": "",  # pull path; do not re-store multi-MB payload
                "pull_only": True,
                "image_id": image_id,
                "thumbnail_b64": (
                    base64.b64encode(thumbnail).decode("ascii") if thumbnail else None
                ),
                "queued_at": time.time(),
            }
            await self._set_pending(payload)
            return {
                "success": True,
                "queued": True,
                "delivery": "pull",
                "message": "Image staged for frame pull on next wake",
            }

        # Either provisioned or frame is known-online (e.g. official Fraimic
        # which rejects /sleepconfig but still accepts /api/image push).
        # Fall through to the push attempt.

        self._flushing = True
        try:
            await self.async_send_image(image_bytes)
            await self.async_clear_pull_bin()
            return {"success": True, "queued": False, "delivery": "push+pull"}
        except (aiohttp.ClientConnectionError, TimeoutError):
            await self.async_refresh()
            if self.last_update_success:
                _LOGGER.info(
                    "Push to %s timed out but frame is online — image staged "
                    "for pull; treating push as unconfirmed",
                    self.host,
                )
                return {
                    "success": True,
                    "queued": False,
                    "unconfirmed": True,
                    "delivery": "pull",
                }
            # Asleep mid-call: staged pull is authoritative.
            payload = {
                "schema": _PENDING_SCHEMA,
                "token": token,
                "bin_b64": "",
                "pull_only": True,
                "image_id": image_id,
                "thumbnail_b64": (
                    base64.b64encode(thumbnail).decode("ascii") if thumbnail else None
                ),
                "queued_at": time.time(),
            }
            await self._set_pending(payload)
            return {
                "success": True,
                "queued": True,
                "delivery": "pull",
                "message": "Image staged for frame pull on next wake",
            }
        except aiohttp.ClientError as err:
            # Frame rejected push, but pull stage still valid.
            _LOGGER.warning(
                "Push to %s failed (%s); image remains staged for pull",
                self.host,
                err,
            )
            return {
                "success": True,
                "queued": True,
                "delivery": "pull",
                "message": f"Push failed ({err}); staged for pull",
            }
        finally:
            self._flushing = False

    async def _async_flush_pending_send(self) -> None:
        """When a poll succeeds, re-provision pull URL (and optional push).

        Pull-only pending entries need no re-POST of image bytes — the frame
        fetches the staged .bin itself. We re-POST /pullurl so a newly awake
        frame that never received provision while asleep still has the URL.
        Legacy pending payloads with bin_b64 still get one push attempt.
        """
        if self._flushing or self.pending_send is None:
            return
        self._flushing = True
        try:
            pending = self.pending_send
            # Always re-point the frame at HA's pull URL while it's online.
            await self.async_provision_frame_pull()

            if pending.get("pull_only") or not pending.get("bin_b64"):
                await self._clear_pending_if_current(pending["token"])
                _LOGGER.info(
                    "Frame %s is online; pull URL provisioned (pull delivery)",
                    self.host,
                )
                return

            image_bytes = base64.b64decode(pending["bin_b64"])
            try:
                await self.async_send_image(image_bytes)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "Failed to deliver queued image to %s (%s) -- dropping it "
                    "rather than retrying (image remains staged for pull).",
                    self.host,
                    err,
                )
                await self._clear_pending_if_current(pending["token"])
                return
            await self.async_clear_pull_bin()
            thumb_b64 = pending.get("thumbnail_b64")
            await self.async_set_last_image(
                image_id=pending.get("image_id"),
                thumbnail=base64.b64decode(thumb_b64) if thumb_b64 else None,
            )
            _LOGGER.info("Delivered queued image to frame %s", self.host)
        finally:
            self._flushing = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base_url(self, endpoint: str) -> str:
        return f"http://{self.host}{endpoint}"

    def _maybe_persist_fingerprint(self, data: dict[str, Any]) -> None:
        """Lazy-migrate: store device_key and mac if missing from entry data.

        Entries set up before v0.4.1 won't have these keys. The first
        successful poll after upgrading populates them so DHCP discovery
        can identify the frame on subsequent IP changes.
        """
        needs_update = False
        updates: dict[str, Any] = dict(self.config_entry.data)

        key = device_key_from_info(data)
        if key and not updates.get(CONF_DEVICE_KEY):
            updates[CONF_DEVICE_KEY] = key
            self.device_key = key
            needs_update = True

        mac = mac_from_info(data)
        if mac and not updates.get(CONF_MAC):
            updates[CONF_MAC] = mac
            needs_update = True

        if needs_update:
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=updates
            )
            _LOGGER.debug(
                "Stored fingerprint for %s: device_key=%s mac=%s",
                self.host,
                key,
                mac,
            )

    # ------------------------------------------------------------------
    # DataUpdateCoordinator protocol
    # ------------------------------------------------------------------

    async def _async_poll_accelerometer(self, session: aiohttp.ClientSession) -> str | None:
        """Opportunistically read physical orientation from accelerometer."""
        from .const import CONF_WIDTH, CONF_HEIGHT  # noqa: PLC0415
        host = self.host
        # 1. Start sensor
        try:
            async with session.post(
                f"http://{host}/test?action=accel_start",
                timeout=aiohttp.ClientTimeout(total=2),
            ) as resp:
                if resp.status != 200:
                    return None
                res = await resp.json()
                if res.get("status") != "ok":
                    return None
        except Exception:
            return None

        x, y = None, None
        try:
            # 2. Read sensor
            async with session.get(
                f"http://{host}/test?action=accel",
                timeout=aiohttp.ClientTimeout(total=2),
            ) as resp:
                if resp.status != 200:
                    return None
                res = await resp.json()
                if "error" not in res:
                    x = res.get("x")
                    y = res.get("y")
        except Exception:
            pass
        finally:
            # 3. Stop sensor
            try:
                async with session.post(
                    f"http://{host}/test?action=accel_stop",
                    timeout=aiohttp.ClientTimeout(total=2),
                ):
                    pass
            except Exception:
                pass

        if x is None or y is None:
            return None

        # Compare gravity axes to determine landscape / portrait. Per the
        # real hardware reading in ACCELEROMETER_FINDINGS.md (x ~= -0.99,
        # y ~= 0.00 while the frame sat in its normal/native resting
        # position), gravity is dominant on X -- not Y -- when the frame is
        # in its native orientation. A previous version of this check had
        # that backwards (assumed Y vertical = native), which made every
        # native-orientation frame report the opposite of its true physical
        # orientation.
        native_w = self.config_entry.data.get(CONF_WIDTH, 1200)
        native_h = self.config_entry.data.get(CONF_HEIGHT, 1600)
        native_is_landscape = native_w > native_h

        if abs(x) >= abs(y):
            return "landscape" if native_is_landscape else "portrait"
        else:
            return "portrait" if native_is_landscape else "landscape"

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch latest data from the frame's /api/info endpoint."""
        session = async_get_clientsession(self.hass)

        try:
            async with session.get(
                self._base_url(API_INFO), timeout=_REQUEST_TIMEOUT
            ) as response:
                response.raise_for_status()
                data: dict[str, Any] = await response.json()

            # Opportunistic accelerometer poll
            device_orientation = await self._async_poll_accelerometer(session)
            data["device_orientation"] = device_orientation

            # Get driver
            driver = self.config_entry.data.get("driver") or "fraimic"

            # Fetch /info admin page for fraimic family to reflect keep awake
            keep_awake_actual = None
            sleep_minutes_actual = None
            if driver == "fraimic":
                try:
                    async with session.get(
                        self._base_url("/info"),
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        if resp.status == 200:
                            html = await resp.text()
                            from .helpers import (  # noqa: PLC0415
                                parse_keep_awake_from_html,
                                parse_sleep_minutes_from_html,
                            )

                            keep_awake_actual = parse_keep_awake_from_html(html)
                            sleep_minutes_actual = parse_sleep_minutes_from_html(html)
                except (aiohttp.ClientError, TimeoutError, Exception) as err:  # noqa: BLE001
                    _LOGGER.debug(
                        "Could not fetch /info for actual sleep settings on %s: %s",
                        self.host,
                        err,
                    )

            data["keep_awake_actual"] = keep_awake_actual
            data["sleep_minutes_actual"] = sleep_minutes_actual

            # If follow device or auto is enabled, update config options
            from .const import CONF_ORIENTATION, CONF_ORIENTATION_FOLLOW_DEVICE, ORIENTATION_AUTO, ORIENTATION_PORTRAIT, ORIENTATION_LANDSCAPE  # noqa: PLC0415
            follow = self.config_entry.options.get(CONF_ORIENTATION_FOLLOW_DEVICE, True)
            if self.config_entry.options.get(CONF_ORIENTATION, ORIENTATION_AUTO) == ORIENTATION_AUTO:
                follow = True

            if follow and device_orientation in (ORIENTATION_PORTRAIT, ORIENTATION_LANDSCAPE) and self.config_entry.options.get(CONF_ORIENTATION) != device_orientation:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    options={
                        **self.config_entry.options,
                        CONF_ORIENTATION: device_orientation,
                        CONF_ORIENTATION_FOLLOW_DEVICE: True,
                    },
                )

            # Successful poll — reset failure counter and migrate fingerprint.
            self._consecutive_failures = 0
            self._maybe_persist_fingerprint(data)

            # The frame answered -- if something's queued, try to deliver it.
            # Checking "pending_send is not None" here (rather than tracking
            # a failure→success transition) is sufficient and idempotent: a
            # flush clears pending_send on success, so later successful
            # polls just no-op immediately, and it also covers the case
            # where the frame is already awake on the very first poll after
            # a Home Assistant restart with a queued send loaded from disk.
            if self.pending_send is not None and not self._flushing:
                self.hass.async_create_task(self._async_flush_pending_send())

            # Track the frame's reported native dimensions. entry.data
            # width/height are always the panel's own report -- the
            # orientation lock (entry.options, see helpers.render_spec_for_entry)
            # is applied at render time and never written back here, so the
            # two can't fight each other.
            dims = dimensions_from_info(data)
            if dims is not None:
                width, height = dims
                curr_w = self.config_entry.data.get(CONF_WIDTH)
                curr_h = self.config_entry.data.get(CONF_HEIGHT)
                if width != curr_w or height != curr_h:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={**self.config_entry.data, CONF_WIDTH: width, CONF_HEIGHT: height}
                    )
                    _LOGGER.info(
                        "Frame %s reported new dimensions: %dx%d",
                        self.host,
                        width,
                        height,
                    )

            return data

        except (aiohttp.ClientConnectionError, TimeoutError) as err:
            self._consecutive_failures += 1
            if (
                self._consecutive_failures >= _FAILURES_BEFORE_RESCAN
                and self.device_key
                and not self._rescan_in_progress
            ):
                self.hass.async_create_task(self._async_try_find_new_host())
            raise UpdateFailed(
                "Frame is unreachable — it may be sleeping or off-network"
            ) from err
        except aiohttp.ClientResponseError as err:
            self._consecutive_failures += 1
            raise UpdateFailed(
                f"Frame returned unexpected HTTP {err.status}"
            ) from err
        except Exception as err:  # noqa: BLE001
            self._consecutive_failures += 1
            raise UpdateFailed(f"Unexpected error fetching frame data: {err}") from err

    async def _async_try_find_new_host(self) -> None:
        """Scan the local /24 subnet for the frame's device_key and update host."""
        if self._rescan_in_progress:
            return
        self._rescan_in_progress = True
        try:
            _LOGGER.info(
                "Scanning subnet for Fraimic frame %s (device_key=%s)…",
                self.host,
                self.device_key,
            )
            local_ip = await self.hass.async_add_executor_job(get_local_ip)

            new_ip = await find_frame_by_device_key(
                local_ip, self.device_key, async_get_clientsession(self.hass)
            )
            if new_ip and new_ip != self.host:
                _LOGGER.info(
                    "Fraimic frame %s found at new IP %s (was %s)",
                    self.device_key,
                    new_ip,
                    self.host,
                )
                self.host = new_ip
                self._consecutive_failures = 0
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={**self.config_entry.data, CONF_HOST: new_ip},
                )
                await self.async_request_refresh()
            elif new_ip is None:
                _LOGGER.warning(
                    "Fraimic frame %s not found anywhere on subnet",
                    self.device_key,
                )
        finally:
            self._rescan_in_progress = False

    # ------------------------------------------------------------------
    # Config-entry update listener — called when entry data changes
    # (e.g. host updated by the DHCP discovery flow).
    # ------------------------------------------------------------------

    async def async_config_entry_updated(
        self,
        hass: HomeAssistant,  # noqa: ARG002
        entry: ConfigEntry,
    ) -> None:
        """Pick up host / options changes without a full integration reload."""
        self.config_entry = entry
        new_host = entry.data.get(CONF_HOST, self.host)
        if new_host != self.host:
            _LOGGER.info(
                "Fraimic coordinator %s: host updated to %s", self.device_key, new_host
            )
            self.host = new_host
            self._consecutive_failures = 0
            await self.async_request_refresh()

        # Scan interval (HA poll while online)
        scan_seconds: int = entry.options.get(
            "scan_interval", DEFAULT_SCAN_INTERVAL
        )
        self._normal_update_interval = timedelta(seconds=scan_seconds)
        if self.pending_send is None:
            self.update_interval = self._normal_update_interval

        # Push new sleep period + pull URL to the frame if it happens to be up.
        # If asleep, the next successful poll/flush will re-provision.
        self.hass.async_create_task(self.async_provision_frame_pull())

    # ------------------------------------------------------------------
    # Command helpers called from services / buttons
    # ------------------------------------------------------------------

    async def async_send_command(self, endpoint: str) -> int:
        """POST to the given endpoint and return the HTTP status code."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                self._base_url(endpoint), timeout=_REQUEST_TIMEOUT
            ) as response:
                response.raise_for_status()
                status: int = response.status
                _LOGGER.debug("POST %s → %s", self._base_url(endpoint), status)
                return status
        except aiohttp.ClientError as err:
            _LOGGER.error("Error sending command to %s: %s", self._base_url(endpoint), err)
            raise

    async def async_send_image(self, image_bytes: bytes) -> int:
        """Upload a binary image to the frame."""
        from .frame_types import send_timeout_for_entry  # noqa: PLC0415

        session = async_get_clientsession(self.hass)
        url = self._base_url(API_IMAGE)
        headers = {"Content-Type": "application/octet-stream"}
        # Timeout comes from the panel profile (FrameType.send_timeout_s).
        # ESP32 sequential panels (7.3") write the body then block on the
        # ~30s e-ink redraw BEFORE answering; a short budget expires after
        # the frame already displayed the image and used to requeue a
        # duplicate. See docs/FRAME_PORT.md transport policy.
        send_timeout = aiohttp.ClientTimeout(
            total=send_timeout_for_entry(self.config_entry)
        )
        try:
            async with session.post(
                url,
                data=image_bytes,
                headers=headers,
                timeout=send_timeout,
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
