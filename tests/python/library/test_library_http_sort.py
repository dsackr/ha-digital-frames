"""Image library sort order (KPF 8 extension): GET
/api/digital_frames/library/list supports ?sort=uploaded_desc|uploaded_asc|
name_asc|name_desc, defaulting to uploaded_desc ("last uploaded first") when
the param is absent or unrecognized.

If this silently breaks: newly uploaded photos stop appearing first in the
gallery grid by default, or the Sort dropdown's other options silently
return the wrong order.
"""

from __future__ import annotations

import pytest
from homeassistant.setup import async_setup_component

from custom_components.digital_frames import library as library_module
from custom_components.digital_frames.const import DOMAIN
from custom_components.digital_frames.library import LibraryManager
from custom_components.digital_frames.library_http import DigitalFramesLibraryListView


@pytest.fixture
async def sort_client(hass, hass_client):
    await async_setup_component(hass, "http", {})
    hass.http.register_view(DigitalFramesLibraryListView())
    return await hass_client()


@pytest.fixture
async def library_manager(hass):
    manager = LibraryManager(hass)
    await manager.async_load()
    hass.data.setdefault(DOMAIN, {})["_library"] = manager
    return manager


class _FakeClock:
    """Stands in for the stdlib `time` module inside library.py's namespace
    only -- patching the real `time.time` in place would also break aiohttp's
    own internal use of it for response headers."""

    def __init__(self, values):
        self._remaining = iter(values)

    def time(self):
        return next(self._remaining)


def _stub_upload_times(monkeypatch, *values):
    monkeypatch.setattr(library_module, "time", _FakeClock(values))


async def test_default_sort_is_last_uploaded_first(
    library_manager, sort_client, sample_image_bytes, monkeypatch
):
    _stub_upload_times(monkeypatch, 100.0, 200.0, 300.0)
    first = await library_manager.async_upload("a.jpg", sample_image_bytes(50, 50))
    second = await library_manager.async_upload("b.jpg", sample_image_bytes(50, 50))
    third = await library_manager.async_upload("c.jpg", sample_image_bytes(50, 50))

    resp = await sort_client.get("/api/digital_frames/library/list")
    assert resp.status == 200
    body = await resp.json()
    assert body["sort"] == "uploaded_desc"
    assert [img["image_id"] for img in body["images"]] == [
        third["image_id"],
        second["image_id"],
        first["image_id"],
    ]


async def test_sort_uploaded_asc(
    library_manager, sort_client, sample_image_bytes, monkeypatch
):
    _stub_upload_times(monkeypatch, 100.0, 200.0)
    first = await library_manager.async_upload("a.jpg", sample_image_bytes(50, 50))
    second = await library_manager.async_upload("b.jpg", sample_image_bytes(50, 50))

    resp = await sort_client.get("/api/digital_frames/library/list?sort=uploaded_asc")
    body = await resp.json()
    assert [img["image_id"] for img in body["images"]] == [
        first["image_id"],
        second["image_id"],
    ]


async def test_sort_by_name(library_manager, sort_client, sample_image_bytes):
    await library_manager.async_upload("charlie.jpg", sample_image_bytes(50, 50))
    await library_manager.async_upload("alpha.jpg", sample_image_bytes(50, 50))
    await library_manager.async_upload("bravo.jpg", sample_image_bytes(50, 50))

    resp = await sort_client.get("/api/digital_frames/library/list?sort=name_asc")
    body = await resp.json()
    assert [img["filename"] for img in body["images"]] == [
        "alpha.jpg",
        "bravo.jpg",
        "charlie.jpg",
    ]

    resp = await sort_client.get("/api/digital_frames/library/list?sort=name_desc")
    body = await resp.json()
    assert [img["filename"] for img in body["images"]] == [
        "charlie.jpg",
        "bravo.jpg",
        "alpha.jpg",
    ]


async def test_unknown_sort_param_falls_back_to_default(
    library_manager, sort_client, sample_image_bytes, monkeypatch
):
    _stub_upload_times(monkeypatch, 100.0, 200.0)
    first = await library_manager.async_upload("a.jpg", sample_image_bytes(50, 50))
    second = await library_manager.async_upload("b.jpg", sample_image_bytes(50, 50))

    resp = await sort_client.get("/api/digital_frames/library/list?sort=bogus")
    body = await resp.json()
    assert body["sort"] == "uploaded_desc"
    assert [img["image_id"] for img in body["images"]] == [
        second["image_id"],
        first["image_id"],
    ]


async def test_album_filter_and_sort_combine(
    library_manager, sort_client, sample_image_bytes, monkeypatch
):
    _stub_upload_times(monkeypatch, 100.0, 200.0, 300.0)
    await library_manager.async_upload(
        "outside.jpg", sample_image_bytes(50, 50), albums=["Other"]
    )
    older = await library_manager.async_upload(
        "vacation1.jpg", sample_image_bytes(50, 50), albums=["Vacation"]
    )
    newer = await library_manager.async_upload(
        "vacation2.jpg", sample_image_bytes(50, 50), albums=["Vacation"]
    )

    resp = await sort_client.get("/api/digital_frames/library/list?album=Vacation")
    body = await resp.json()
    assert [img["image_id"] for img in body["images"]] == [
        newer["image_id"],
        older["image_id"],
    ]
