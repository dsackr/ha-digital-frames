"""PanelCodec registry & encode seam (FramePort Phase 1 / KPF 7 + 23)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.fraimic.frame_types import (
    CODEC_SPECTRA6_SEQUENTIAL,
    CODEC_SPECTRA6_SPLIT_HALF,
    FRAME_TYPES,
    LAYOUT_SEQUENTIAL,
    LAYOUT_SPLIT_HALF,
)
from custom_components.fraimic.panel_codec import (
    CODECS,
    encode_for_panel,
    panel_codec_for_entry,
    panel_codec_for_frame_type_id,
    panel_codec_for_id,
    panel_codec_for_resolution,
)


def test_both_spectra_codecs_are_registered():
    assert CODEC_SPECTRA6_SPLIT_HALF in CODECS
    assert CODEC_SPECTRA6_SEQUENTIAL in CODECS
    assert CODECS[CODEC_SPECTRA6_SPLIT_HALF].byte_layout == LAYOUT_SPLIT_HALF
    assert CODECS[CODEC_SPECTRA6_SEQUENTIAL].byte_layout == LAYOUT_SEQUENTIAL


def test_panel_codec_for_resolution_matches_frame_types():
    for ft in FRAME_TYPES.values():
        w, h = ft.resolution
        codec = panel_codec_for_resolution(w, h)
        assert codec.id == ft.codec_id
        assert codec.byte_layout == ft.byte_layout


def test_panel_codec_for_frame_type_id():
    assert panel_codec_for_frame_type_id("7.3").id == CODEC_SPECTRA6_SEQUENTIAL
    assert panel_codec_for_frame_type_id("13.3").id == CODEC_SPECTRA6_SPLIT_HALF


def test_panel_codec_for_entry_prefers_size():
    entry = SimpleNamespace(
        entry_id="e1",
        data={"size": "7.3", "width": 1200, "height": 1600},
    )
    # size wins even if dimensions look like 13.3
    assert panel_codec_for_entry(entry).id == CODEC_SPECTRA6_SEQUENTIAL


def test_panel_codec_for_entry_falls_back_to_dimensions():
    entry = SimpleNamespace(entry_id="e1", data={"width": 800, "height": 480})
    assert panel_codec_for_entry(entry).id == CODEC_SPECTRA6_SEQUENTIAL


def test_panel_codec_for_entry_raises_without_hints():
    entry = SimpleNamespace(entry_id="e1", data={})
    with pytest.raises(ValueError, match="no size or dimensions"):
        panel_codec_for_entry(entry)


def test_unknown_codec_id_raises():
    with pytest.raises(ValueError, match="Unknown panel codec"):
        panel_codec_for_id("not_a_codec")


def test_encode_for_panel_uses_registered_resolution(sample_image_bytes):
    # Smoke: both codecs produce the expected 4bpp length.
    for ft in FRAME_TYPES.values():
        w, h = ft.resolution
        out = encode_for_panel(sample_image_bytes(200, 150), w, h)
        assert len(out) == (w * h) // 2


def test_encode_for_panel_rejects_unknown_resolution(sample_image_bytes):
    with pytest.raises(ValueError, match="No registered frame type"):
        encode_for_panel(sample_image_bytes(10, 10), 9999, 9999)
