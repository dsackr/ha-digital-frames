"""Shared network helpers for probing and scanning Fraimic frames."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
from typing import Any

import aiohttp

from .const import API_INFO, FRAME_RESOLUTIONS

_LOGGER = logging.getLogger(__name__)

_PROBE_TIMEOUT = aiohttp.ClientTimeout(total=5)
_SCAN_TIMEOUT = aiohttp.ClientTimeout(total=0.5)

# /info's "Device Type" row looks like:
#   <span class='info-label'>Device Type</span><span class='info-value'>13.3" E-Ink</span>
_DEVICE_TYPE_RE = re.compile(
    r"Device\s*Type\s*</span>\s*<span[^>]*>\s*([^<]*?)\s*</span>",
    re.IGNORECASE,
)
_SIZE_INCHES_RE = re.compile(r'([\d.]+)\s*"')


async def probe_frame(
    session: aiohttp.ClientSession,
    host: str,
    timeout: aiohttp.ClientTimeout | None = None,
) -> dict[str, Any] | None:
    """GET /api/info on *host*. Returns parsed JSON or None on any failure."""
    url = f"http://{host}{API_INFO}"
    try:
        async with session.get(url, timeout=timeout or _PROBE_TIMEOUT) as resp:
            if resp.status == 200:
                return await resp.json(content_type=None)  # type: ignore[no-any-return]
    except Exception:  # noqa: BLE001
        pass
    return None


async def probe_device_size(
    session: aiohttp.ClientSession, host: str
) -> str | None:
    """Best-effort auto-detect of a frame's physical size, scraped from its
    /info admin page's "Device Type" field (e.g. '13.3" E-Ink' -> "13.3").

    /api/info -- the JSON endpoint the rest of this integration relies on --
    doesn't expose size or resolution at all (confirmed against real
    hardware, not just undocumented). /info is a separate, human-facing
    HTML page with no stability guarantee, so any request failure or
    unexpected markup here just means "couldn't detect" -- config_flow
    falls back to asking the user for size instead of raising.
    """
    try:
        async with session.get(f"http://{host}/info", timeout=_PROBE_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            html = await resp.text()
    except Exception:  # noqa: BLE001
        return None

    match = _DEVICE_TYPE_RE.search(html)
    if not match:
        return None
    inches_match = _SIZE_INCHES_RE.search(match.group(1))
    if not inches_match:
        return None
    size = inches_match.group(1)
    return size if size in FRAME_RESOLUTIONS else None


def device_key_from_info(info: dict[str, Any]) -> str | None:
    """Extract the persistent device_key from a /api/info response."""
    return info.get("device", {}).get("device_key") or None


def mac_from_info(info: dict[str, Any]) -> str:
    """Extract the normalised (no colons, lowercase) MAC from a /api/info response."""
    raw = info.get("wifi", {}).get("mac", "")
    return raw.replace(":", "").lower()


async def scan_subnet(host_ip: str) -> list[dict[str, Any]]:
    """Probe all 254 host addresses in the /24 subnet of *host_ip* concurrently.

    Returns a list of ``{"ip": str, "info": dict}`` for every address that
    responded as a Fraimic frame (i.e. returned a valid /api/info payload with
    a device_key).
    """
    try:
        network = ipaddress.IPv4Network(f"{host_ip}/24", strict=False)
    except ValueError:
        return []

    hosts = [str(h) for h in network.hosts()]

    async with aiohttp.ClientSession() as session:
        tasks = [probe_frame(session, h, _SCAN_TIMEOUT) for h in hosts]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    found: list[dict[str, Any]] = []
    for addr, result in zip(hosts, results):
        if isinstance(result, dict) and device_key_from_info(result):
            found.append({"ip": addr, "info": result})
    return found


async def find_frame_by_device_key(
    host_ip: str, device_key: str
) -> str | None:
    """Scan the /24 subnet and return the IP of the frame with *device_key*, or None."""
    results = await scan_subnet(host_ip)
    for entry in results:
        if device_key_from_info(entry["info"]) == device_key:
            return entry["ip"]
    return None
