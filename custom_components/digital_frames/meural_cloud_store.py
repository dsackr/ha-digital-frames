"""Shared Meural cloud credentials + pin/album bindings for all Meural frames.

One Netgear account is shared across every Meural config entry in the
integration (product default). Frame-specific gallery/item ids live under
``frames[entry_id]``.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .meural_cloud import MeuralCloudClient

_LOGGER = logging.getLogger(__name__)

_STORE_VERSION = 1
_STORE_KEY = "digital_frames_meural_cloud"

# hass.data key for the live client singleton
DATA_MEURAL_CLOUD = "_meural_cloud"


class MeuralCloudStore:
    """Persist credentials and per-frame pin/album cloud ids."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = Store(hass, _STORE_VERSION, _STORE_KEY)
        self._data: dict[str, Any] = {
            "username": "",
            "password": "",
            "access_token": None,
            "refresh_token": None,
            "frames": {},
        }
        self._client: MeuralCloudClient | None = None
        self._loaded = False

    async def async_load(self) -> None:
        if self._loaded:
            return
        raw = await self._store.async_load()
        if isinstance(raw, dict):
            self._data.update(
                {
                    "username": raw.get("username") or "",
                    "password": raw.get("password") or "",
                    "access_token": raw.get("access_token"),
                    "refresh_token": raw.get("refresh_token"),
                    "frames": raw.get("frames")
                    if isinstance(raw.get("frames"), dict)
                    else {},
                }
            )
        self._loaded = True

    async def async_save(self) -> None:
        await self._store.async_save(self._data)

    @property
    def is_linked(self) -> bool:
        return bool(self._data.get("username") and self._data.get("password"))

    @property
    def username(self) -> str:
        return str(self._data.get("username") or "")

    def status_dict(self) -> dict[str, Any]:
        return {
            "linked": self.is_linked,
            "username": self.username if self.is_linked else None,
        }

    async def async_link(self, username: str, password: str) -> MeuralCloudClient:
        """Validate credentials, store them, and return a ready client."""
        await self.async_load()
        session = async_get_clientsession(self.hass)

        def _on_tokens(access: str, refresh: str | None) -> None:
            self._data["access_token"] = access
            if refresh is not None:
                self._data["refresh_token"] = refresh
            self.hass.async_create_task(self.async_save())

        client = MeuralCloudClient(
            session,
            username=username,
            password=password,
            token_update_callback=_on_tokens,
        )
        await client.async_login()
        self._data["username"] = username.strip()
        self._data["password"] = password
        self._data["access_token"] = client.access_token
        self._data["refresh_token"] = client.refresh_token
        await self.async_save()
        self._client = client
        return client

    async def async_unlink(self) -> None:
        await self.async_load()
        self._data = {
            "username": "",
            "password": "",
            "access_token": None,
            "refresh_token": None,
            "frames": self._data.get("frames") or {},
        }
        self._client = None
        await self.async_save()

    def get_client(self) -> MeuralCloudClient | None:
        """Return cached client if linked (may need ensure_token on first use)."""
        if not self.is_linked:
            return None
        if self._client is not None:
            return self._client
        session = async_get_clientsession(self.hass)

        def _on_tokens(access: str, refresh: str | None) -> None:
            self._data["access_token"] = access
            if refresh is not None:
                self._data["refresh_token"] = refresh
            self.hass.async_create_task(self.async_save())

        self._client = MeuralCloudClient(
            session,
            username=self._data["username"],
            password=self._data["password"],
            access_token=self._data.get("access_token"),
            refresh_token=self._data.get("refresh_token"),
            token_update_callback=_on_tokens,
        )
        return self._client

    def frame_state(self, entry_id: str) -> dict[str, Any]:
        frames = self._data.setdefault("frames", {})
        if entry_id not in frames or not isinstance(frames[entry_id], dict):
            frames[entry_id] = {}
        return frames[entry_id]

    async def async_update_frame_state(
        self, entry_id: str, updates: dict[str, Any]
    ) -> None:
        await self.async_load()
        state = self.frame_state(entry_id)
        state.update(updates)
        await self.async_save()


async def async_get_meural_cloud_store(hass: HomeAssistant) -> MeuralCloudStore:
    domain = hass.data.setdefault("digital_frames", {})
    store = domain.get(DATA_MEURAL_CLOUD)
    if isinstance(store, MeuralCloudStore):
        await store.async_load()
        return store
    store = MeuralCloudStore(hass)
    await store.async_load()
    domain[DATA_MEURAL_CLOUD] = store
    return store
