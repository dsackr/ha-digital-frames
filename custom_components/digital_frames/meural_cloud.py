"""Meural / Netgear cloud API client (upload, galleries, device load).

Authentication uses AWS Cognito (same client id as HA-meural) via plain
HTTPS — no boto3 dependency. Falls back to the legacy
``POST /v0/authenticate`` form login when Cognito is unavailable.

Endpoints are documented in the unofficial Meural Postman collection
(https://documenter.getpostman.com/view/1657302/RVnWjKUL) and community
use (Martin Amps upload flow, ha-meural device load).

This module never talks to the local Canvas; pairing with a LAN host is
done by matching ``localIp`` / serial from ``user/devices``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://api.meural.com/v0/"

# Public Cognito app client used by Meural / HA-meural (eu-west-1).
_COGNITO_REGION = "eu-west-1"
_COGNITO_CLIENT_ID = "487bd4kvb1fnop6mbgk8gu5ibf"
_COGNITO_URL = f"https://cognito-idp.{_COGNITO_REGION}.amazonaws.com/"

# Gallery orientation values required by POST /galleries.
ORIENT_HORIZONTAL = "horizontal"  # landscape
ORIENT_VERTICAL = "vertical"  # portrait

# The cloud API's own vocabulary for orientation on GET responses is not
# documented and may not echo back "horizontal"/"vertical" verbatim (some
# Meural endpoints use "landscape"/"portrait" instead). Treat both spellings
# as equivalent so a vocabulary mismatch never causes ensure_named_gallery to
# miss an existing gallery and create a duplicate.
_ORIENTATION_ALIASES = {
    ORIENT_HORIZONTAL: {ORIENT_HORIZONTAL, "landscape"},
    ORIENT_VERTICAL: {ORIENT_VERTICAL, "portrait"},
}


def _orientation_matches(gallery_orientation: str, target_orientation: str) -> bool:
    if not gallery_orientation:
        return True
    aliases = _ORIENTATION_ALIASES.get(target_orientation, {target_orientation})
    return gallery_orientation in aliases


_TIMEOUT = aiohttp.ClientTimeout(total=60)
_UPLOAD_TIMEOUT = aiohttp.ClientTimeout(total=180)


class MeuralCloudError(Exception):
    """Base error for Meural cloud operations."""


class MeuralCloudAuthError(MeuralCloudError):
    """Credentials rejected or token unusable."""


class MeuralCloudAPIError(MeuralCloudError):
    """Non-auth API failure."""


def gallery_orientation_for_hang(orientation: str | None) -> str:
    """Map frame hang (portrait|landscape) to Meural gallery orientation."""
    if (orientation or "").strip().lower() == "portrait":
        return ORIENT_VERTICAL
    return ORIENT_HORIZONTAL


def pin_gallery_name(frame_title: str, gallery_orientation: str) -> str:
    """Stable per-frame pin gallery name (one image; no slideshow)."""
    hang = "portrait" if gallery_orientation == ORIENT_VERTICAL else "landscape"
    title = (frame_title or "Meural").strip() or "Meural"
    return f"Digital Frames · {title} · Pin · {hang}"


def album_gallery_name(ha_album: str, gallery_orientation: str) -> str:
    hang = "portrait" if gallery_orientation == ORIENT_VERTICAL else "landscape"
    name = (ha_album or "Album").strip() or "Album"
    return f"Digital Frames · {name} · {hang}"


class MeuralCloudClient:
    """Async client for api.meural.com."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        username: str,
        password: str,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_update_callback: Callable[[str, str | None], None] | None = None,
    ) -> None:
        self.session = session
        self.username = (username or "").strip()
        self.password = password or ""
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._token_update_callback = token_update_callback
        # Keyed by gallery name; serializes ensure_named_gallery so two
        # overlapping sends for the same gallery can't both miss each
        # other's in-flight create and each spawn a duplicate.
        self._gallery_locks: dict[str, asyncio.Lock] = {}

    def _gallery_lock(self, name: str) -> asyncio.Lock:
        lock = self._gallery_locks.get(name)
        if lock is None:
            lock = asyncio.Lock()
            self._gallery_locks[name] = lock
        return lock

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def async_login(self) -> tuple[str, str | None]:
        """Authenticate; return (access_token, refresh_token|None)."""
        if not self.username or not self.password:
            raise MeuralCloudAuthError("Meural cloud username and password required")

        try:
            access, refresh = await self._cognito_user_password()
            self.access_token = access
            if refresh:
                self.refresh_token = refresh
            self._emit_tokens()
            return access, self.refresh_token
        except MeuralCloudAuthError:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.info(
                "Meural Cognito auth failed (%s); trying legacy /authenticate",
                err,
            )

        access = await self._legacy_authenticate()
        self.access_token = access
        self.refresh_token = None
        self._emit_tokens()
        return access, None

    async def async_ensure_token(self) -> str:
        if self.access_token:
            return self.access_token
        access, _ = await self.async_login()
        return access

    def _emit_tokens(self) -> None:
        if self._token_update_callback and self.access_token:
            self._token_update_callback(self.access_token, self.refresh_token)

    async def _cognito_user_password(self) -> tuple[str, str | None]:
        headers = {
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
        }
        body = {
            "AuthFlow": "USER_PASSWORD_AUTH",
            "ClientId": _COGNITO_CLIENT_ID,
            "AuthParameters": {
                "USERNAME": self.username,
                "PASSWORD": self.password,
            },
        }
        async with self.session.post(
            _COGNITO_URL, json=body, headers=headers, timeout=_TIMEOUT
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise MeuralCloudAuthError(
                    f"Cognito auth failed ({resp.status}): {text[:200]}"
                )
            try:
                payload = await resp.json(content_type=None)
            except Exception as err:  # noqa: BLE001
                raise MeuralCloudAuthError(f"Cognito non-JSON: {text[:200]}") from err

        if "AuthenticationResult" not in payload:
            challenge = payload.get("ChallengeName", "unknown")
            raise MeuralCloudAuthError(
                f"Cognito requires unsupported challenge: {challenge}"
            )
        result = payload["AuthenticationResult"]
        access = result.get("AccessToken")
        if not access:
            raise MeuralCloudAuthError("Cognito response missing AccessToken")
        return access, result.get("RefreshToken")

    async def _cognito_refresh(self) -> str:
        if not self.refresh_token:
            raise MeuralCloudAuthError("No refresh token")
        headers = {
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
        }
        body = {
            "AuthFlow": "REFRESH_TOKEN_AUTH",
            "ClientId": _COGNITO_CLIENT_ID,
            "AuthParameters": {"REFRESH_TOKEN": self.refresh_token},
        }
        async with self.session.post(
            _COGNITO_URL, json=body, headers=headers, timeout=_TIMEOUT
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise MeuralCloudAuthError(
                    f"Cognito refresh failed ({resp.status}): {text[:200]}"
                )
            payload = await resp.json(content_type=None)
        result = payload.get("AuthenticationResult") or {}
        access = result.get("AccessToken")
        if not access:
            raise MeuralCloudAuthError("Cognito refresh missing AccessToken")
        self.access_token = access
        self._emit_tokens()
        return access

    async def _legacy_authenticate(self) -> str:
        data = aiohttp.FormData()
        data.add_field("username", self.username)
        data.add_field("password", self.password)
        async with self.session.post(
            f"{BASE_URL}authenticate", data=data, timeout=_TIMEOUT
        ) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise MeuralCloudAuthError(
                    f"Legacy authenticate failed ({resp.status}): {text[:200]}"
                )
            try:
                payload = await resp.json(content_type=None)
            except Exception as err:  # noqa: BLE001
                raise MeuralCloudAuthError(
                    f"Legacy authenticate non-JSON: {text[:200]}"
                ) from err
        # Shape varies: {data: {token}} or {token} or {data: token}
        data_obj = payload.get("data", payload)
        if isinstance(data_obj, dict):
            token = data_obj.get("token") or data_obj.get("accessToken")
        else:
            token = data_obj
        if not token or not isinstance(token, str):
            raise MeuralCloudAuthError("Legacy authenticate response missing token")
        return token

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        form: aiohttp.FormData | None = None,
        params: dict[str, Any] | None = None,
        timeout: aiohttp.ClientTimeout | None = None,
        _retried: bool = False,
    ) -> Any:
        """Call Meural API; return the ``data`` field (or full JSON)."""
        await self.async_ensure_token()
        url = f"{BASE_URL}{path.lstrip('/')}"
        headers = {
            "Authorization": f"Token {self.access_token}",
            "x-meural-api-version": "3",
        }
        kwargs: dict[str, Any] = {
            "headers": headers,
            "timeout": timeout or _TIMEOUT,
        }
        if params:
            kwargs["params"] = params
        if form is not None:
            kwargs["data"] = form
        elif json_body is not None:
            kwargs["json"] = json_body

        async with self.session.request(method, url, **kwargs) as resp:
            text = await resp.text()
            if resp.status == 401 and not _retried:
                self.access_token = None
                try:
                    if self.refresh_token:
                        await self._cognito_refresh()
                    else:
                        await self.async_login()
                except MeuralCloudAuthError:
                    raise
                return await self.request(
                    method,
                    path,
                    json_body=json_body,
                    form=form,
                    params=params,
                    timeout=timeout,
                    _retried=True,
                )
            if resp.status >= 400:
                raise MeuralCloudAPIError(
                    f"Meural {method.upper()} {path} failed ({resp.status}): {text[:300]}"
                )
            if not text.strip():
                return None
            try:
                payload = await resp.json(content_type=None)
            except Exception as err:  # noqa: BLE001
                raise MeuralCloudAPIError(
                    f"Meural {method.upper()} {path} non-JSON: {text[:200]}"
                ) from err

        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    async def get_user_devices(self) -> list[dict[str, Any]]:
        data = await self.request("get", "user/devices", params={"count": 1000})
        return data if isinstance(data, list) else []

    async def get_user_galleries(self) -> list[dict[str, Any]]:
        data = await self.request("get", "user/galleries", params={"count": 1000})
        return data if isinstance(data, list) else []

    async def get_gallery_items(self, gallery_id: int | str) -> list[dict[str, Any]]:
        data = await self.request("get", f"galleries/{gallery_id}/items")
        return data if isinstance(data, list) else []

    async def create_gallery(
        self,
        name: str,
        *,
        orientation: str,
        description: str = "",
    ) -> dict[str, Any]:
        if orientation not in (ORIENT_HORIZONTAL, ORIENT_VERTICAL):
            raise ValueError(f"Invalid gallery orientation: {orientation!r}")
        form = aiohttp.FormData()
        form.add_field("name", name)
        form.add_field("description", description or "")
        form.add_field("orientation", orientation)
        data = await self.request("post", "galleries", form=form)
        if not isinstance(data, dict) or data.get("id") is None:
            raise MeuralCloudAPIError(f"Create gallery returned unexpected data: {data!r}")
        return data

    async def delete_gallery(self, gallery_id: int | str) -> None:
        await self.request("delete", f"galleries/{gallery_id}")

    async def add_item_to_gallery(
        self, gallery_id: int | str, item_id: int | str
    ) -> Any:
        return await self.request(
            "post", f"galleries/{gallery_id}/items/{item_id}"
        )

    async def remove_item_from_gallery(
        self, gallery_id: int | str, item_id: int | str
    ) -> Any:
        return await self.request(
            "delete", f"galleries/{gallery_id}/items/{item_id}"
        )

    async def upload_item(
        self,
        image_bytes: bytes,
        *,
        content_type: str = "image/jpeg",
        filename: str = "digital_frames.jpg",
    ) -> dict[str, Any]:
        if content_type == "image/jpg":
            content_type = "image/jpeg"
        form = aiohttp.FormData()
        form.add_field(
            "image",
            image_bytes,
            filename=filename,
            content_type=content_type,
        )
        data = await self.request(
            "post", "items", form=form, timeout=_UPLOAD_TIMEOUT
        )
        if not isinstance(data, dict) or data.get("id") is None:
            raise MeuralCloudAPIError(f"Upload item returned unexpected data: {data!r}")
        return data

    async def delete_item(self, item_id: int | str) -> None:
        await self.request("delete", f"items/{item_id}")

    async def device_load_gallery(
        self, device_id: int | str, gallery_id: int | str
    ) -> Any:
        return await self.request(
            "post", f"devices/{device_id}/galleries/{gallery_id}"
        )

    async def device_load_item(
        self, device_id: int | str, item_id: int | str
    ) -> Any:
        """Push a single item to the device (ha-meural; not in older Postman docs)."""
        return await self.request("post", f"devices/{device_id}/items/{item_id}")

    async def update_device(
        self, device_id: int | str, data: dict[str, Any]
    ) -> Any:
        return await self.request("put", f"devices/{device_id}", json_body=data)

    async def sync_device(self, device_id: int | str) -> Any:
        return await self.request("post", f"devices/{device_id}/sync")

    async def find_device_for_host(
        self,
        host: str,
        *,
        serial: str | None = None,
    ) -> dict[str, Any] | None:
        """Match a cloud device to a LAN host (localIp) or serial."""
        host = (host or "").strip()
        serial_n = (serial or "").strip().lower()
        devices = await self.get_user_devices()
        if serial_n:
            for dev in devices:
                for key in ("serial", "serialNumber", "productSerial"):
                    raw = dev.get(key)
                    if raw is not None and str(raw).strip().lower() == serial_n:
                        return dev
        if host:
            for dev in devices:
                lip = str(dev.get("localIp") or dev.get("local_ip") or "").strip()
                if lip == host:
                    return dev
        return None

    async def ensure_named_gallery(
        self,
        name: str,
        *,
        orientation: str,
        description: str = "",
        expected_gallery_id: int | str | None = None,
    ) -> dict[str, Any]:
        """Return existing user gallery with *name* or create one.

        *expected_gallery_id*, when given (the id stored from a prior push),
        is checked first and returned as-is if still present — this is the
        authoritative reuse path and sidesteps any drift in name/orientation
        matching. Falls back to a name+orientation scan, and if that scan
        turns up more than one gallery with the same name (e.g. duplicates
        created by a past matching bug), keeps the oldest (lowest id) and
        best-effort deletes the rest so installs self-heal over time.
        """
        async with self._gallery_lock(name):
            galleries = await self.get_user_galleries()
            valid_galleries = [g for g in galleries if isinstance(g, dict)]

            if expected_gallery_id is not None:
                for g in valid_galleries:
                    if str(g.get("id")) == str(expected_gallery_id):
                        return g

            matches = [
                g
                for g in valid_galleries
                if (g.get("name") or "").strip() == name
                and _orientation_matches(
                    (g.get("orientation") or "").strip().lower(), orientation
                )
            ]
            if not matches:
                return await self.create_gallery(
                    name, orientation=orientation, description=description
                )

            matches.sort(key=lambda g: g.get("id") if g.get("id") is not None else 0)
            canonical, *duplicates = matches
            if duplicates:
                _LOGGER.warning(
                    "Meural gallery %r has %d duplicate(s); keeping id %s and "
                    "removing the rest",
                    name,
                    len(duplicates),
                    canonical.get("id"),
                )
                for dup in duplicates:
                    dup_id = dup.get("id")
                    if dup_id is None:
                        continue
                    try:
                        items = await self.get_gallery_items(dup_id)
                    except MeuralCloudAPIError:
                        items = []
                    for item in items:
                        item_id = item.get("id") if isinstance(item, dict) else None
                        if item_id is None:
                            continue
                        try:
                            await self.delete_item(item_id)
                        except MeuralCloudAPIError:
                            pass
                    try:
                        await self.delete_gallery(dup_id)
                    except MeuralCloudAPIError as err:
                        _LOGGER.debug(
                            "Meural delete duplicate gallery %s: %s", dup_id, err
                        )
            return canonical

    async def pin_image_on_device(
        self,
        *,
        device_id: int | str,
        image_bytes: bytes,
        gallery_name: str,
        gallery_orientation: str,
        previous_item_id: int | str | None = None,
        previous_gallery_id: int | str | None = None,
        content_type: str = "image/jpeg",
        set_no_rotation: bool = True,
    ) -> dict[str, Any]:
        """Upload image, put it alone in a pin gallery, load on device.

        Replaces *previous_item_id* (removed from gallery + deleted) so
        daily widgets / re-sends do not accumulate cloud junk.
        """
        item = await self.upload_item(image_bytes, content_type=content_type)
        item_id = item["id"]

        gallery = await self.ensure_named_gallery(
            gallery_name,
            orientation=gallery_orientation,
            description="Managed by Digital Frames (single-image pin; no rotation).",
            expected_gallery_id=previous_gallery_id,
        )
        gallery_id = gallery["id"]

        # Clear other items from the pin gallery so only the new image remains.
        try:
            existing = await self.get_gallery_items(gallery_id)
        except MeuralCloudAPIError as err:
            _LOGGER.warning("Meural list gallery items failed: %s", err)
            existing = []

        for old in existing:
            if not isinstance(old, dict):
                continue
            old_id = old.get("id")
            if old_id is None or old_id == item_id:
                continue
            try:
                await self.remove_item_from_gallery(gallery_id, old_id)
            except MeuralCloudAPIError as err:
                _LOGGER.debug("Meural remove gallery item %s: %s", old_id, err)
            try:
                await self.delete_item(old_id)
            except MeuralCloudAPIError as err:
                _LOGGER.debug("Meural delete item %s: %s", old_id, err)

        await self.add_item_to_gallery(gallery_id, item_id)

        # Explicit previous ids (in case list was empty / wrong gallery).
        if previous_item_id is not None and str(previous_item_id) != str(item_id):
            if previous_gallery_id is not None:
                try:
                    await self.remove_item_from_gallery(
                        previous_gallery_id, previous_item_id
                    )
                except MeuralCloudAPIError:
                    pass
            try:
                await self.delete_item(previous_item_id)
            except MeuralCloudAPIError as err:
                _LOGGER.debug(
                    "Meural delete previous pin item %s: %s", previous_item_id, err
                )

        await self.device_load_gallery(device_id, gallery_id)
        try:
            await self.device_load_item(device_id, item_id)
        except MeuralCloudAPIError as err:
            _LOGGER.debug("Meural device_load_item optional: %s", err)

        if set_no_rotation:
            try:
                await self.update_device(
                    device_id,
                    {
                        "imageDuration": 0,
                        "galleryRotation": False,
                        "imageShuffle": False,
                    },
                )
            except MeuralCloudAPIError as err:
                _LOGGER.debug("Meural update_device pin options: %s", err)

        try:
            await self.sync_device(device_id)
        except MeuralCloudAPIError as err:
            _LOGGER.debug("Meural sync_device: %s", err)

        return {
            "item_id": item_id,
            "gallery_id": gallery_id,
            "gallery_name": gallery_name,
            "device_id": device_id,
        }

    async def push_album_to_device(
        self,
        *,
        device_id: int | str,
        gallery_name: str,
        gallery_orientation: str,
        image_payloads: list[tuple[bytes, str]],
        previous_item_ids: list[int | str] | None = None,
        previous_gallery_id: int | str | None = None,
        enable_rotation: bool = True,
        image_duration_s: int = 1800,
    ) -> dict[str, Any]:
        """Full-mirror HA album → Meural gallery and make it live.

        *image_payloads* is a list of (bytes, content_type).
        Old items not in the new set are deleted when *previous_item_ids*
        is provided or when they already sit in the target gallery.
        """
        if not image_payloads:
            raise MeuralCloudAPIError("Cannot push empty album to Meural")

        gallery = await self.ensure_named_gallery(
            gallery_name,
            orientation=gallery_orientation,
            description="Managed by Digital Frames (HA album; rotation enabled).",
            expected_gallery_id=previous_gallery_id,
        )
        gallery_id = gallery["id"]

        new_item_ids: list[Any] = []
        for image_bytes, content_type in image_payloads:
            item = await self.upload_item(image_bytes, content_type=content_type)
            item_id = item["id"]
            new_item_ids.append(item_id)
            await self.add_item_to_gallery(gallery_id, item_id)

        # Remove items that were in this gallery before (or tracked previously)
        # and are not part of the new set.
        try:
            existing = await self.get_gallery_items(gallery_id)
        except MeuralCloudAPIError:
            existing = []
        keep = {str(i) for i in new_item_ids}
        candidates: list[Any] = []
        for old in existing:
            if isinstance(old, dict) and old.get("id") is not None:
                candidates.append(old["id"])
        if previous_item_ids:
            candidates.extend(previous_item_ids)
        seen: set[str] = set()
        for old_id in candidates:
            key = str(old_id)
            if key in keep or key in seen:
                continue
            seen.add(key)
            try:
                await self.remove_item_from_gallery(gallery_id, old_id)
            except MeuralCloudAPIError:
                pass
            try:
                await self.delete_item(old_id)
            except MeuralCloudAPIError:
                pass

        await self.device_load_gallery(device_id, gallery_id)

        if enable_rotation:
            try:
                await self.update_device(
                    device_id,
                    {
                        "imageDuration": max(0, int(image_duration_s)),
                        "galleryRotation": False,
                        "imageShuffle": False,
                    },
                )
            except MeuralCloudAPIError as err:
                _LOGGER.debug("Meural update_device album options: %s", err)

        try:
            await self.sync_device(device_id)
        except MeuralCloudAPIError as err:
            _LOGGER.debug("Meural sync_device: %s", err)

        return {
            "gallery_id": gallery_id,
            "gallery_name": gallery_name,
            "item_ids": new_item_ids,
            "device_id": device_id,
        }
