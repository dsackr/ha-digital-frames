"""Frame-type registry, codec ids & byte-layout dispatch (KPF 23).

Garbles the displayed image on an unregistered/misregistered panel size --
same failure mode as image_converter, one layer up. Pure logic, no HA
dependency.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.digital_frames.frame_types import (
    CODEC_SPECTRA6_SEQUENTIAL,
    CODEC_SPECTRA6_SPLIT_HALF,
    DEFAULT_SEND_TIMEOUT_S,
    FRAME_TYPES,
    LAYOUT_SEQUENTIAL,
    LAYOUT_SPLIT_HALF,
    byte_layout_for_resolution,
    codec_id_for_resolution,
    frame_type_for_resolution,
    frame_types_for_vendor,
    send_timeout_for_entry,
)


def test_every_registered_resolution_resolves_to_its_declared_layout():
    for frame_type in FRAME_TYPES.values():
        width, height = frame_type.resolution
        assert byte_layout_for_resolution(width, height) == frame_type.byte_layout


def test_every_registered_resolution_resolves_to_its_codec_id():
    for frame_type in FRAME_TYPES.values():
        width, height = frame_type.resolution
        # Shared resolutions (13.3 vs 13.3_clone) may return either FrameType id;
        # codecs must still agree (enforced by _validate_registry).
        assert codec_id_for_resolution(width, height) == frame_type.codec_id
        assert (
            frame_type_for_resolution(width, height).codec_id == frame_type.codec_id
        )


def test_unknown_resolution_raises():
    with pytest.raises(ValueError, match="No registered frame type"):
        byte_layout_for_resolution(9999, 9999)
    with pytest.raises(ValueError, match="No registered frame type"):
        codec_id_for_resolution(9999, 9999)


def test_orientation_swapped_dimensions_still_resolve():
    # Some frames report swapped (h, w) after a physical rotation; the
    # coordinator persists whatever's reported, so lookup must be
    # orientation-agnostic (see frame_type_for_resolution's docstring).
    for frame_type in FRAME_TYPES.values():
        width, height = frame_type.resolution
        assert byte_layout_for_resolution(height, width) == frame_type.byte_layout
        assert codec_id_for_resolution(height, width) == frame_type.codec_id


def test_known_layouts_and_codecs_are_represented():
    layouts = {ft.byte_layout for ft in FRAME_TYPES.values()}
    codecs = {ft.codec_id for ft in FRAME_TYPES.values()}
    assert LAYOUT_SPLIT_HALF in layouts
    assert LAYOUT_SEQUENTIAL in layouts
    assert CODEC_SPECTRA6_SPLIT_HALF in codecs
    assert CODEC_SPECTRA6_SEQUENTIAL in codecs


def test_7_3_is_sequential_codec_not_split_half():
    """7.3\" is a different PanelCodec under the same local Spectra driver."""
    ft = FRAME_TYPES["7.3"]
    assert ft.byte_layout == LAYOUT_SEQUENTIAL
    assert ft.codec_id == CODEC_SPECTRA6_SEQUENTIAL
    assert codec_id_for_resolution(800, 480) == CODEC_SPECTRA6_SEQUENTIAL


def test_official_13_3_is_split_half_codec():
    ft = FRAME_TYPES["13.3"]
    assert ft.byte_layout == LAYOUT_SPLIT_HALF
    assert ft.codec_id == CODEC_SPECTRA6_SPLIT_HALF


def test_send_timeout_from_size_on_entry():
    entry = SimpleNamespace(data={"size": "7.3"})
    assert send_timeout_for_entry(entry) == FRAME_TYPES["7.3"].send_timeout_s
    assert send_timeout_for_entry(entry) == DEFAULT_SEND_TIMEOUT_S


def test_send_timeout_from_dimensions_when_size_missing():
    entry = SimpleNamespace(data={"width": 800, "height": 480})
    assert send_timeout_for_entry(entry) == FRAME_TYPES["7.3"].send_timeout_s


def test_send_timeout_default_when_unknown():
    entry = SimpleNamespace(data={})
    assert send_timeout_for_entry(entry) == DEFAULT_SEND_TIMEOUT_S


def test_das2_frames_are_their_own_vendor_not_fraimic():
    """DAS2 Frames (spectra-frames firmware) are community hardware: origin clone
    (so HA sends BLE wakes), vendor DAS2, named for the vendor."""
    from custom_components.digital_frames.frame_types import ORIGIN_CLONE, VENDOR_DAS2

    das2 = frame_types_for_vendor(VENDOR_DAS2)
    assert {ft.id for ft in das2} == {"7.3", "13.3_das2"}
    for ft in das2:
        assert ft.origin == ORIGIN_CLONE
        assert ft.display_name.startswith("DAS2 Frames")
    # The official 13.3" and the Pi Zero clone are not DAS2.
    assert FRAME_TYPES["13.3"].vendor is None
    assert FRAME_TYPES["13.3_clone"].vendor is None


def test_das2_13_3_shares_the_official_split_half_codec():
    ft = FRAME_TYPES["13.3_das2"]
    assert ft.codec_id == CODEC_SPECTRA6_SPLIT_HALF
    assert ft.resolution == FRAME_TYPES["13.3"].resolution
    assert ft.platform == "ESP32-S3"
