from __future__ import annotations

import pytest

from custom_components.digital_frames.helpers import RenderSpec
from custom_components.digital_frames.library import LibraryBackendError, LibraryManager


@pytest.fixture
async def library_manager(hass):
    manager = LibraryManager(hass)
    await manager.async_load()
    return manager


async def test_crop_saves_and_clears_aspect_ratio_keys(library_manager, sample_image_bytes):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(2000, 2000))
    image_id = record["image_id"]

    # Save crop for 1200x1600 (ratio = 0.75)
    updated = await library_manager.async_set_crop(image_id, 1200, 1600, [0.1, 0.2, 0.8, 0.9])
    assert updated["crops"]["ratio:0.7500"] == [0.1, 0.2, 0.8, 0.9]

    # Clear crop clears it
    cleared = await library_manager.async_clear_crop(image_id, 1200, 1600)
    assert "ratio:0.7500" not in cleared["crops"]


async def test_crop_resolves_by_exact_and_epsilon_aspect_ratio(library_manager, sample_image_bytes):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(2000, 2000))
    image_id = record["image_id"]

    # Save crop for 1200x1600 (ratio = 0.75)
    await library_manager.async_set_crop(image_id, 1200, 1600, [0.1, 0.2, 0.8, 0.9])

    # 1. Exact ratio key lookup for different resolution with same ratio: 900x1200
    spec_exact = RenderSpec(width=900, height=1200, rotation=0, locked=True)
    # This should succeed and not raise
    await library_manager.async_get_bin_for_send(image_id, spec_exact, codec_id="jpeg_q90")

    # 2. Epsilon lookup for slightly off resolution: 901x1200 (ratio = 0.7508)
    spec_epsilon = RenderSpec(width=901, height=1200, rotation=0, locked=True)
    await library_manager.async_get_bin_for_send(image_id, spec_epsilon, codec_id="jpeg_q90")


async def test_orientation_lock_persists(library_manager, sample_image_bytes):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(100, 100))
    image_id = record["image_id"]

    # Defaults to unlocked
    assert record["orientation_lock"] == "unlocked"

    # Set to portrait
    updated = await library_manager.async_set_image_orientation_lock(image_id, "portrait")
    assert updated["orientation_lock"] == "portrait"

    # Invalid values raise LibraryBackendError
    with pytest.raises(LibraryBackendError, match="Invalid orientation lock"):
        await library_manager.async_set_image_orientation_lock(image_id, "invalid_value")


async def test_orientation_lock_blocks_incompatible_sends(library_manager, sample_image_bytes):
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(100, 100))
    image_id = record["image_id"]

    # Lock image to portrait
    await library_manager.async_set_image_orientation_lock(image_id, "portrait")

    # 1. Compatible: send to a portrait-locked frame (W < H)
    spec_port = RenderSpec(width=1200, height=1600, rotation=0, locked=True)
    await library_manager.async_get_bin_for_send(image_id, spec_port)  # should pass

    # 2. Incompatible: send to a landscape-locked frame (W >= H)
    spec_land = RenderSpec(width=1600, height=1200, rotation=0, locked=True)
    with pytest.raises(LibraryBackendError, match="Image is locked to portrait screens"):
        await library_manager.async_get_bin_for_send(image_id, spec_land)

    # 3. Auto frame (locked = False) is always compatible
    spec_auto = RenderSpec(width=1600, height=1200, rotation=0, locked=False)
    await library_manager.async_get_bin_for_send(image_id, spec_auto)  # should pass


async def test_unlocked_frame_natural_orientation_selection(hass, library_manager, sample_image_bytes):
    # 1. Image has crops for both orientations, landscape has larger area
    # Landscape crop: area = (0.9-0.1)*(0.9-0.1) = 0.64
    # Portrait crop: area = (0.5-0.1)*(0.5-0.1) = 0.16
    record = await library_manager.async_upload("photo.jpg", sample_image_bytes(2000, 2000))
    image_id = record["image_id"]
    await library_manager.async_set_crop(image_id, 1600, 1200, [0.1, 0.1, 0.9, 0.9]) # landscape
    await library_manager.async_set_crop(image_id, 1200, 1600, [0.1, 0.1, 0.5, 0.5]) # portrait

    # Send to unlocked frame with native portrait resolution (1200x1600)
    spec = RenderSpec(width=1200, height=1600, rotation=0, locked=False)
    # The image is naturally landscape (due to larger crop area).
    # Since frame is portrait, it should swap dimensions and rotate (90 deg) to match landscape natural orientation!
    bin_bytes = await library_manager.async_get_bin_for_send(image_id, spec)
    # Let's verify the bin was cached under the swapped resolution 1600x1200 (since natural orientation is landscape)
    from custom_components.digital_frames.frame_types import CODEC_SPECTRA6_SPLIT_HALF
    cached = await library_manager._backend.async_get_bin(
        image_id, 1600, 1200, "_r90_c", CODEC_SPECTRA6_SPLIT_HALF
    )
    assert cached is not None

    # 2. Image has no crops: native dimensions width 2000 > height 1000 (landscape)
    record2 = await library_manager.async_upload("landscape.jpg", sample_image_bytes(2000, 1000))
    image_id2 = record2["image_id"]
    # Send to unlocked portrait frame
    bin_bytes2 = await library_manager.async_get_bin_for_send(image_id2, spec)
    cached2 = await library_manager._backend.async_get_bin(
        image_id2, 1600, 1200, "_r90_c", CODEC_SPECTRA6_SPLIT_HALF
    )
    assert cached2 is not None
