"""Meural local driver + JPEG codec (FramePort Phase 3 / KPF 32)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.fraimic.const import (
    CONF_DRIVER,
    DRIVER_MEURAL,
    MEURAL_SIZE_LABEL,
)
from custom_components.fraimic.panel_codec import (
    CODEC_JPEG_Q90,
    encode_for_panel,
    panel_codec_for_entry,
)
from custom_components.fraimic.meural import probe_meural, send_meural_postcard


def test_panel_codec_for_meural_entry():
    entry = SimpleNamespace(
        entry_id="e1",
        data={
            CONF_DRIVER: DRIVER_MEURAL,
            "width": 1920,
            "height": 1080,
            "size": MEURAL_SIZE_LABEL,
        },
    )
    assert panel_codec_for_entry(entry).id == CODEC_JPEG_Q90
    assert panel_codec_for_entry(entry).preferred_payload == "jpeg"


def test_encode_jpeg_for_meural_geometry(sample_image_bytes):
    out = encode_for_panel(
        sample_image_bytes(400, 300),
        1920,
        1080,
        0,
        False,
        "fast",
        None,
        CODEC_JPEG_Q90,
    )
    # JPEG SOI marker
    assert out[:2] == b"\xff\xd8"
    assert len(out) > 100


def _mock_session(status: int, text: str):
    resp = AsyncMock()
    resp.status = status
    resp.text = AsyncMock(return_value=text)
    resp.headers = {}
    resp.request_info = MagicMock()
    resp.history = ()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.get = MagicMock(return_value=cm)
    session.post = MagicMock(return_value=cm)
    return session


@pytest.mark.asyncio
async def test_probe_meural_pass():
    session = _mock_session(
        200, '{"status":"pass","response":{"serial":"ABC","alias":"Room"}}'
    )
    info = await probe_meural(session, "192.168.1.80")
    assert info is not None
    assert info.get("serial") == "ABC"


@pytest.mark.asyncio
async def test_probe_meural_fail():
    session = _mock_session(200, '{"status":"fail","response":"nope"}')
    info = await probe_meural(session, "192.168.1.80")
    assert info is None


@pytest.mark.asyncio
async def test_send_meural_postcard_ok():
    session = _mock_session(200, '{"status":"pass","response":"ok"}')
    result = await send_meural_postcard(
        session, "192.168.1.80", b"\xff\xd8\xfffakejpeg"
    )
    assert result["status"] == "pass"
