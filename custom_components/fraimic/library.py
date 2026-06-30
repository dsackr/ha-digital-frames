"""Pluggable storage backends for the Fraimic shared image library.

The library holds a single shared pool of source images. Each image gets a
pre-converted .bin generated once per distinct (width, height) resolution in
use across the user's configured frames -- NOT one per individual frame --
so any frame sharing that resolution sends the cached bytes with zero extra
conversion work. A resolution that shows up later (e.g. a newly added frame
with a different panel size) is generated lazily on first send to a frame of
that size, then cached from then on.

Storage backend is pluggable. LocalLibraryBackend (this HA install's own
storage) is fully implemented. GoogleDriveLibraryBackend and
DropboxLibraryBackend are scaffolded but not yet wired to real credentials --
selecting them raises a clear LibraryBackendError until that's done.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

from .const import CONF_HEIGHT, CONF_WIDTH, DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_SETTINGS_STORAGE_KEY = f"{DOMAIN}_library_settings"
_SETTINGS_STORAGE_VERSION = 1

BACKEND_LOCAL = "local"
BACKEND_GOOGLE_DRIVE = "google_drive"
BACKEND_DROPBOX = "dropbox"

_CONTENT_TYPE_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "WEBP": "image/webp",
    "TIFF": "image/tiff",
    "HEIC": "image/heic",
}


def _detect_content_type(raw_bytes: bytes) -> str:
    """Best-effort sniff of an uploaded image's MIME type."""
    try:
        from PIL import Image  # noqa: PLC0415

        with Image.open(io.BytesIO(raw_bytes)) as img:
            fmt = (img.format or "").upper()
    except Exception:  # noqa: BLE001
        fmt = ""
    return _CONTENT_TYPE_BY_FORMAT.get(fmt, "application/octet-stream")


def _all_frame_resolutions(hass: "HomeAssistant") -> set[tuple[int, int]]:
    """Distinct (width, height) pairs across every configured Fraimic frame."""
    resolutions: set[tuple[int, int]] = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        width = entry.data.get(CONF_WIDTH)
        height = entry.data.get(CONF_HEIGHT)
        if isinstance(width, int) and isinstance(height, int):
            resolutions.add((width, height))
    return resolutions


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return name[:128] or "image"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class LibraryImage:
    """One image in the shared library."""

    image_id: str
    filename: str
    uploaded_at: float
    content_type: str = "application/octet-stream"
    resolutions: list[list[int]] = field(default_factory=list)  # [[w, h], ...]

    def has_resolution(self, width: int, height: int) -> bool:
        return [width, height] in self.resolutions

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "filename": self.filename,
            "uploaded_at": self.uploaded_at,
            "content_type": self.content_type,
            "resolutions": self.resolutions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LibraryImage":
        return cls(
            image_id=data["image_id"],
            filename=data["filename"],
            uploaded_at=data["uploaded_at"],
            content_type=data.get("content_type", "application/octet-stream"),
            resolutions=data.get("resolutions", []),
        )


class LibraryBackendError(Exception):
    """Raised when a backend can't be used (bad/missing credentials, not yet
    implemented, network failure, etc.)."""


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------


class LibraryBackend:
    """Abstract interface every storage backend implements."""

    name = "abstract"

    async def async_setup(self) -> None:
        """Validate connectivity/credentials. Raise LibraryBackendError on failure."""

    async def async_list_images(self) -> list[LibraryImage]:
        raise NotImplementedError

    async def async_get_original(self, image_id: str) -> tuple[bytes, str]:
        """Return (raw_bytes, content_type) for the stored original."""
        raise NotImplementedError

    async def async_get_bin(
        self, image_id: str, width: int, height: int
    ) -> bytes | None:
        raise NotImplementedError

    async def async_save_bin(
        self, image_id: str, width: int, height: int, data: bytes
    ) -> None:
        raise NotImplementedError

    async def async_upload_original(
        self, filename: str, raw_bytes: bytes, content_type: str
    ) -> LibraryImage:
        raise NotImplementedError

    async def async_delete_image(self, image_id: str) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Local (HA-server) backend -- fully implemented
# ---------------------------------------------------------------------------


class LocalLibraryBackend(LibraryBackend):
    """Stores the library under <config>/fraimic_library/ on the HA host."""

    name = BACKEND_LOCAL

    def __init__(self, hass: "HomeAssistant") -> None:
        self.hass = hass
        self._root = hass.config.path("fraimic_library")
        self._manifest_path = os.path.join(self._root, "manifest.json")

    async def async_setup(self) -> None:
        await self.hass.async_add_executor_job(self._ensure_dirs)

    # -- sync helpers (always run via executor) --

    def _ensure_dirs(self) -> None:
        os.makedirs(self._root, exist_ok=True)
        os.makedirs(os.path.join(self._root, "originals"), exist_ok=True)
        os.makedirs(os.path.join(self._root, "bin"), exist_ok=True)
        if not os.path.isfile(self._manifest_path):
            with open(self._manifest_path, "w", encoding="utf-8") as f:
                json.dump({"images": []}, f)

    def _read_manifest(self) -> dict[str, Any]:
        if not os.path.isfile(self._manifest_path):
            return {"images": []}
        with open(self._manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_manifest(self, manifest: dict[str, Any]) -> None:
        tmp = self._manifest_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        os.replace(tmp, self._manifest_path)

    def _bin_path(self, image_id: str, width: int, height: int) -> str:
        return os.path.join(self._root, "bin", f"{width}x{height}", f"{image_id}.bin")

    def _original_path_for(self, image_id: str, filename: str) -> str:
        return os.path.join(
            self._root, "originals", f"{image_id}_{_safe_filename(filename)}"
        )

    def _find_original_path(self, image_id: str) -> str | None:
        originals_dir = os.path.join(self._root, "originals")
        if not os.path.isdir(originals_dir):
            return None
        prefix = f"{image_id}_"
        for fn in os.listdir(originals_dir):
            if fn.startswith(prefix):
                return os.path.join(originals_dir, fn)
        return None

    def _list_images_sync(self) -> list[LibraryImage]:
        manifest = self._read_manifest()
        return [LibraryImage.from_dict(d) for d in manifest.get("images", [])]

    def _upload_original_sync(
        self, filename: str, raw_bytes: bytes, content_type: str
    ) -> LibraryImage:
        self._ensure_dirs()
        image_id = uuid.uuid4().hex[:12]
        path = self._original_path_for(image_id, filename)
        with open(path, "wb") as f:
            f.write(raw_bytes)
        record = LibraryImage(
            image_id=image_id,
            filename=filename,
            uploaded_at=time.time(),
            content_type=content_type,
            resolutions=[],
        )
        manifest = self._read_manifest()
        manifest.setdefault("images", []).append(record.to_dict())
        self._write_manifest(manifest)
        return record

    def _get_original_sync(self, image_id: str) -> tuple[bytes, str]:
        manifest = self._read_manifest()
        entry = next(
            (d for d in manifest.get("images", []) if d["image_id"] == image_id),
            None,
        )
        content_type = entry.get("content_type", "application/octet-stream") if entry else "application/octet-stream"
        path = self._find_original_path(image_id)
        if path is None:
            raise LibraryBackendError(f"Original for image '{image_id}' not found")
        with open(path, "rb") as f:
            return f.read(), content_type

    def _get_bin_sync(self, image_id: str, width: int, height: int) -> bytes | None:
        path = self._bin_path(image_id, width, height)
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            return f.read()

    def _save_bin_sync(
        self, image_id: str, width: int, height: int, data: bytes
    ) -> None:
        path = self._bin_path(image_id, width, height)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        manifest = self._read_manifest()
        for d in manifest.get("images", []):
            if d["image_id"] == image_id:
                resolutions = d.setdefault("resolutions", [])
                if [width, height] not in resolutions:
                    resolutions.append([width, height])
                break
        self._write_manifest(manifest)

    def _delete_image_sync(self, image_id: str) -> None:
        path = self._find_original_path(image_id)
        if path and os.path.isfile(path):
            os.remove(path)
        bin_root = os.path.join(self._root, "bin")
        if os.path.isdir(bin_root):
            for res_dir in os.listdir(bin_root):
                candidate = os.path.join(bin_root, res_dir, f"{image_id}.bin")
                if os.path.isfile(candidate):
                    os.remove(candidate)
        manifest = self._read_manifest()
        manifest["images"] = [
            d for d in manifest.get("images", []) if d["image_id"] != image_id
        ]
        self._write_manifest(manifest)

    # -- async public API --

    async def async_list_images(self) -> list[LibraryImage]:
        return await self.hass.async_add_executor_job(self._list_images_sync)

    async def async_get_original(self, image_id: str) -> tuple[bytes, str]:
        return await self.hass.async_add_executor_job(self._get_original_sync, image_id)

    async def async_get_bin(
        self, image_id: str, width: int, height: int
    ) -> bytes | None:
        return await self.hass.async_add_executor_job(
            self._get_bin_sync, image_id, width, height
        )

    async def async_save_bin(
        self, image_id: str, width: int, height: int, data: bytes
    ) -> None:
        await self.hass.async_add_executor_job(
            self._save_bin_sync, image_id, width, height, data
        )

    async def async_upload_original(
        self, filename: str, raw_bytes: bytes, content_type: str
    ) -> LibraryImage:
        return await self.hass.async_add_executor_job(
            self._upload_original_sync, filename, raw_bytes, content_type
        )

    async def async_delete_image(self, image_id: str) -> None:
        await self.hass.async_add_executor_job(self._delete_image_sync, image_id)


# ---------------------------------------------------------------------------
# Cloud backends -- scaffolded, not yet wired to real credentials
# ---------------------------------------------------------------------------


class GoogleDriveLibraryBackend(LibraryBackend):
    """Google Drive backend. Needs OAuth client credentials + a refresh
    token before this can work -- not implemented yet."""

    name = BACKEND_GOOGLE_DRIVE

    def __init__(self, hass: "HomeAssistant", settings: dict[str, Any]) -> None:
        self.hass = hass
        self.settings = settings

    async def async_setup(self) -> None:
        raise LibraryBackendError(
            "Google Drive isn't wired up yet -- it needs an OAuth client "
            "ID/secret and refresh token. Staying on local storage for now."
        )


class DropboxLibraryBackend(LibraryBackend):
    """Dropbox backend. Needs a Dropbox API access token before this can
    work -- not implemented yet."""

    name = BACKEND_DROPBOX

    def __init__(self, hass: "HomeAssistant", settings: dict[str, Any]) -> None:
        self.hass = hass
        self.settings = settings

    async def async_setup(self) -> None:
        raise LibraryBackendError(
            "Dropbox isn't wired up yet -- it needs a Dropbox API access "
            "token. Staying on local storage for now."
        )


# ---------------------------------------------------------------------------
# Manager -- backend-agnostic operations used by the HTTP views
# ---------------------------------------------------------------------------


class LibraryManager:
    """Owns the active backend and implements upload / send-from-library
    logic that's the same regardless of which backend is active."""

    def __init__(self, hass: "HomeAssistant") -> None:
        self.hass = hass
        self._store: Store = Store(hass, _SETTINGS_STORAGE_VERSION, _SETTINGS_STORAGE_KEY)
        self._settings: dict[str, Any] = {"backend": BACKEND_LOCAL}
        self._backend: LibraryBackend = LocalLibraryBackend(hass)

    async def async_load(self) -> None:
        """Load persisted backend settings (if any) and stand up that backend."""
        stored = await self._store.async_load()
        if stored:
            self._settings = stored
        self._backend = self._build_backend(self._settings)
        try:
            await self._backend.async_setup()
        except LibraryBackendError as err:
            _LOGGER.warning(
                "Configured library backend '%s' failed to initialise (%s); "
                "falling back to local storage",
                self._settings.get("backend"),
                err,
            )
            self._settings = {"backend": BACKEND_LOCAL}
            self._backend = LocalLibraryBackend(self.hass)
            await self._backend.async_setup()

    def _build_backend(self, settings: dict[str, Any]) -> LibraryBackend:
        backend_type = settings.get("backend", BACKEND_LOCAL)
        if backend_type == BACKEND_GOOGLE_DRIVE:
            return GoogleDriveLibraryBackend(self.hass, settings)
        if backend_type == BACKEND_DROPBOX:
            return DropboxLibraryBackend(self.hass, settings)
        return LocalLibraryBackend(self.hass)

    @property
    def backend_name(self) -> str:
        return self._backend.name

    async def async_set_backend(self, settings: dict[str, Any]) -> None:
        """Validate then switch backends; only persists on success."""
        candidate = self._build_backend(settings)
        await candidate.async_setup()  # raises LibraryBackendError on failure
        self._backend = candidate
        self._settings = settings
        await self._store.async_save(self._settings)

    async def async_list_images(self) -> list[dict[str, Any]]:
        images = await self._backend.async_list_images()
        return [img.to_dict() for img in images]

    async def async_get_original(self, image_id: str) -> tuple[bytes, str]:
        return await self._backend.async_get_original(image_id)

    async def async_upload(self, filename: str, raw_bytes: bytes) -> dict[str, Any]:
        """Store the original, then eagerly generate a .bin for every
        resolution currently in use across configured frames."""
        content_type = await self.hass.async_add_executor_job(
            _detect_content_type, raw_bytes
        )
        record = await self._backend.async_upload_original(
            filename, raw_bytes, content_type
        )

        from .image_converter import convert_image_bytes  # noqa: PLC0415

        for width, height in _all_frame_resolutions(self.hass):
            try:
                bin_bytes = await self.hass.async_add_executor_job(
                    convert_image_bytes, raw_bytes, width, height
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "Failed converting library image %s to %dx%d: %s",
                    record.image_id,
                    width,
                    height,
                    err,
                )
                continue
            await self._backend.async_save_bin(record.image_id, width, height, bin_bytes)
            if [width, height] not in record.resolutions:
                record.resolutions.append([width, height])

        return record.to_dict()

    async def async_get_bin_for_send(
        self, image_id: str, width: int, height: int
    ) -> bytes:
        """Return a cached .bin, generating + caching it on the fly if this
        resolution hasn't been seen for this image before (e.g. a frame
        added after the image was uploaded)."""
        cached = await self._backend.async_get_bin(image_id, width, height)
        if cached is not None:
            return cached

        raw_bytes, _content_type = await self._backend.async_get_original(image_id)

        from .image_converter import convert_image_bytes  # noqa: PLC0415

        bin_bytes = await self.hass.async_add_executor_job(
            convert_image_bytes, raw_bytes, width, height
        )
        await self._backend.async_save_bin(image_id, width, height, bin_bytes)
        return bin_bytes

    async def async_delete(self, image_id: str) -> None:
        await self._backend.async_delete_image(image_id)
