"""Full-quality copy of the last image accepted for each frame.

The Frames panel preview (``last_thumbnail``) is a small PNG. It is not a
stand-in for the payload that was actually delivered. This module keeps, per
config entry:

* the wire bytes last handed to ``async_send_image_or_queue`` (Spectra
  ``.bin``, Meural JPEG, Samsung/Roku PNG) — already at frame resolution
* when the send started from an original photo (direct upload / ``send_image``
  service), those source bytes too, so Resend can run them through the
  current render spec (orientation, codec) instead of replaying a stale
  encode

Library sends are re-encoded from ``last_image_id`` on resend; the saved wire
bytes are the fallback if that image is gone. Nothing here is the preview
thumbnail.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .const import CACHE_DIRNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

NO_PREVIOUS_IMAGE = "No image has been sent to this frame yet"
LIBRARY_IMAGE_UNAVAILABLE = (
    "The last image sent to this frame is no longer available to resend"
)
PREVIEW_ONLY = (
    "No full-quality copy of this frame's last image is available to resend. "
    "Send the image once more, then Resend will work."
)


def _wire_path(hass, entry_id: str) -> Path:
    return Path(hass.config.path(CACHE_DIRNAME, "last_sent", f"{entry_id}.wire"))


def _source_path(hass, entry_id: str) -> Path:
    return Path(hass.config.path(CACHE_DIRNAME, "last_sent", f"{entry_id}.source"))


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _read_if_present(path: Path) -> bytes | None:
    try:
        if not path.is_file():
            return None
        data = path.read_bytes()
    except OSError:
        return None
    return data or None


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as err:
        _LOGGER.debug("Could not remove %s: %s", path, err)


def _persist(
    wire_path: str,
    source_path: str,
    wire: bytes,
    source: bytes | None,
    clear_source: bool,
) -> None:
    _write_atomic(Path(wire_path), wire)
    src = Path(source_path)
    if source:
        _write_atomic(src, source)
    elif clear_source:
        _unlink_quiet(src)


async def async_store_last_sent(
    hass,
    entry_id: str,
    *,
    wire_bytes: bytes,
    source_bytes: bytes | None = None,
    clear_source: bool = True,
) -> None:
    """Persist *wire_bytes* (and optional original *source_bytes*) for *entry_id*.

    ``clear_source`` drops a previously saved original when this send did not
    come from one (library image, skill, message). Flush-on-wake passes
    ``clear_source=False`` so a queued direct upload keeps its original.
    Disk errors are logged and swallowed: a failed preview write must not
    fail a send that already reached the frame.
    """
    if not wire_bytes or not entry_id:
        return
    try:
        await hass.async_add_executor_job(
            _persist,
            str(_wire_path(hass, entry_id)),
            str(_source_path(hass, entry_id)),
            wire_bytes,
            source_bytes,
            clear_source,
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning(
            "Failed to persist last sent image for %s: %s", entry_id, err
        )


def _load_pair(wire_path: str, source_path: str) -> tuple[bytes | None, bytes | None]:
    return _read_if_present(Path(wire_path)), _read_if_present(Path(source_path))


async def async_load_last_sent(
    hass, entry_id: str
) -> tuple[bytes | None, bytes | None]:
    """Return ``(wire_bytes, source_bytes)``; either may be None."""
    if not entry_id:
        return None, None
    try:
        return await hass.async_add_executor_job(
            _load_pair,
            str(_wire_path(hass, entry_id)),
            str(_source_path(hass, entry_id)),
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Failed to load last sent image for %s: %s", entry_id, err)
        return None, None


def frame_can_resend(hass, coordinator) -> bool:
    """True when Resend has a library id or a saved full-quality payload."""
    if coordinator is None:
        return False
    if getattr(coordinator, "last_image_id", None):
        return True
    if getattr(coordinator, "_last_wire_bytes", None):
        return True
    entry = getattr(coordinator, "config_entry", None)
    if entry is None:
        return False
    wire = _wire_path(hass, entry.entry_id)
    source = _source_path(hass, entry.entry_id)
    try:
        if wire.is_file() and wire.stat().st_size > 0:
            return True
        if source.is_file() and source.stat().st_size > 0:
            return True
    except OSError:
        return False
    return False


def _with_bytes_sent(result: dict[str, Any], nbytes: int) -> dict[str, Any]:
    if "bytes_sent" in result:
        return result
    return {**result, "bytes_sent": nbytes}


async def async_resend_last_image(hass, coordinator) -> dict[str, Any]:
    """Re-push this frame's last image through its normal send path.

    Library images are re-encoded with the current render spec (orientation,
    crop, codec, color pipeline). Direct uploads are re-encoded from the
    saved original the same way. Anything else (skills, messages, crops)
    replays the saved full-resolution wire bytes. Delivery goes through
    ``async_send_image_or_queue``, so asleep frames queue / pull as usual.

    Raises ``HomeAssistantError`` when there is nothing full-quality to send.
    """
    image_id = getattr(coordinator, "last_image_id", None) or None
    entry = coordinator.config_entry
    entry_id = entry.entry_id
    wire, source = await async_load_last_sent(hass, entry_id)
    if wire is None:
        mem = getattr(coordinator, "_last_wire_bytes", None)
        if mem:
            wire = mem

    if image_id:
        library = (hass.data.get(DOMAIN) or {}).get("_library")
        if library is not None:
            try:
                fresh = await _encode_library_image(hass, coordinator, image_id)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Resend of library image %s on %s could not re-encode (%s); "
                    "trying the saved full-resolution payload",
                    image_id,
                    getattr(coordinator, "host", entry_id),
                    err,
                )
            else:
                result = await coordinator.async_send_image_or_queue(
                    fresh, image_id=image_id
                )
                return _with_bytes_sent(result, len(fresh))
        if wire:
            result = await coordinator.async_send_image_or_queue(
                wire, image_id=image_id
            )
            return _with_bytes_sent(result, len(wire))
        raise HomeAssistantError(LIBRARY_IMAGE_UNAVAILABLE)

    if source:
        try:
            fresh, preview = await _encode_source(hass, coordinator, source)
        except Exception as err:  # noqa: BLE001
            if not wire:
                raise HomeAssistantError(f"Failed to resend image: {err}") from err
            _LOGGER.warning(
                "Resend could not re-encode the saved original for %s (%s); "
                "replaying the last wire payload",
                getattr(coordinator, "host", entry_id),
                err,
            )
        else:
            result = await coordinator.async_send_image_or_queue(
                fresh, thumbnail=preview, source_bytes=source
            )
            return _with_bytes_sent(result, len(fresh))

    if wire:
        thumb = getattr(coordinator, "last_thumbnail", None)
        result = await coordinator.async_send_image_or_queue(
            wire,
            thumbnail=thumb,
            # Keep a saved original if re-encode failed above.
            source_bytes=source,
        )
        return _with_bytes_sent(result, len(wire))

    if getattr(coordinator, "last_thumbnail", None):
        raise HomeAssistantError(PREVIEW_ONLY)
    raise HomeAssistantError(NO_PREVIOUS_IMAGE)


async def _encode_library_image(hass, coordinator, image_id: str) -> bytes:
    from .helpers import render_spec_for_hass_entry  # noqa: PLC0415
    from .panel_codec import panel_codec_for_entry  # noqa: PLC0415

    library = hass.data[DOMAIN]["_library"]
    entry = coordinator.config_entry
    spec = render_spec_for_hass_entry(hass, entry)
    try:
        codec_id = panel_codec_for_entry(entry).id
    except ValueError:
        codec_id = None
    return await library.async_get_bin_for_send(
        image_id, spec, codec_id=codec_id, entry=entry
    )


async def _encode_source(hass, coordinator, source: bytes) -> tuple[bytes, bytes]:
    from .helpers import render_spec_for_hass_entry  # noqa: PLC0415
    from .panel_codec import (  # noqa: PLC0415
        encode_for_panel_with_preview,
        panel_codec_for_entry,
    )

    entry = coordinator.config_entry
    spec = render_spec_for_hass_entry(hass, entry)
    try:
        codec_id = panel_codec_for_entry(entry).id
    except ValueError:
        codec_id = None
    return await hass.async_add_executor_job(
        encode_for_panel_with_preview,
        source,
        spec.width,
        spec.height,
        spec.rotation,
        spec.locked,
        codec_id,
    )
