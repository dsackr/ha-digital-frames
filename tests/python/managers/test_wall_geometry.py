"""Wall canvas geometry: compute a shared banner canvas + per-frame crop
slices for a wall-banner message (KPF: compose & send a styled message).

If this silently breaks: a wall banner's frames could show non-adjacent or
misaligned slices, or a stale/live orientation disagreement could shift a
follow-device frame's crop after it physically flips.
"""

from __future__ import annotations

import pytest

from custom_components.digital_frames.const import (
    CONF_DRIVER,
    CONF_ORIENTATION_FOLLOW_DEVICE,
    DOMAIN,
    DRIVER_MEURAL,
)
from custom_components.digital_frames.wall_geometry import (
    WallGeometryError,
    compute_wall_canvas_geometry,
)
from custom_components.digital_frames.walls import Wall


def _wall(placements: dict) -> Wall:
    return Wall(wall_id="wall-1", name="Test Wall", placements=placements)


async def test_single_frame_degenerates_to_full_crop(hass, make_frame_entry):
    entry = make_frame_entry(entry_id="entry-0", width=1200, height=1600)
    entry.add_to_hass(hass)
    wall = _wall({"entry-0": {"x": 100.0, "y": 100.0}})

    geometry = compute_wall_canvas_geometry(hass, wall, ["entry-0"])

    assert geometry.canvas_width == 1200
    assert geometry.canvas_height == 1600
    assert geometry.crop_boxes["entry-0"] == (0.0, 0.0, 1.0, 1.0)


async def test_row_of_frames_sorted_left_to_right(hass, make_frame_entry):
    entries = []
    for i, x in enumerate((300.0, 100.0, 200.0)):  # deliberately out of order
        entry = make_frame_entry(entry_id=f"entry-{i}", width=1200, height=1600)
        entry.add_to_hass(hass)
        entries.append((entry, x))
    placements = {entry.entry_id: {"x": x, "y": 50.0} for entry, x in entries}
    wall = _wall(placements)

    geometry = compute_wall_canvas_geometry(
        hass, wall, [e.entry_id for e, _ in entries]
    )

    assert geometry.canvas_width == 1200 * 3
    assert geometry.canvas_height == 1600
    # entries[1] has x=100 (leftmost) -> slice 0; entries[2] x=200 -> slice 1;
    # entries[0] x=300 -> slice 2.
    assert geometry.crop_boxes[entries[1][0].entry_id] == (0 / 3, 0.0, 1 / 3, 1.0)
    assert geometry.crop_boxes[entries[2][0].entry_id] == (1 / 3, 0.0, 2 / 3, 1.0)
    assert geometry.crop_boxes[entries[0][0].entry_id] == (2 / 3, 0.0, 1.0, 1.0)


async def test_column_of_frames_sorted_top_to_bottom(hass, make_frame_entry):
    e0 = make_frame_entry(entry_id="entry-0", width=1200, height=1600)
    e1 = make_frame_entry(entry_id="entry-1", width=1200, height=1600)
    e0.add_to_hass(hass)
    e1.add_to_hass(hass)
    wall = _wall(
        {
            "entry-0": {"x": 50.0, "y": 200.0},
            "entry-1": {"x": 50.0, "y": 50.0},
        }
    )

    geometry = compute_wall_canvas_geometry(hass, wall, ["entry-0", "entry-1"])

    assert geometry.canvas_width == 1200
    assert geometry.canvas_height == 1600 * 2
    assert geometry.crop_boxes["entry-1"] == (0.0, 0.0, 1.0, 0.5)  # y=50, topmost
    assert geometry.crop_boxes["entry-0"] == (0.0, 0.5, 1.0, 1.0)  # y=200


async def test_mismatched_resolution_rejected(hass, make_frame_entry):
    e0 = make_frame_entry(entry_id="entry-0", width=1200, height=1600)
    e1 = make_frame_entry(entry_id="entry-1", width=800, height=480)
    e0.add_to_hass(hass)
    e1.add_to_hass(hass)
    wall = _wall(
        {
            "entry-0": {"x": 0.0, "y": 0.0},
            "entry-1": {"x": 1200.0, "y": 0.0},
        }
    )

    with pytest.raises(WallGeometryError, match="same resolution"):
        compute_wall_canvas_geometry(hass, wall, ["entry-0", "entry-1"])


async def test_non_colinear_placements_rejected(hass, make_frame_entry):
    e0 = make_frame_entry(entry_id="entry-0", width=1200, height=1600)
    e1 = make_frame_entry(entry_id="entry-1", width=1200, height=1600)
    e0.add_to_hass(hass)
    e1.add_to_hass(hass)
    wall = _wall(
        {
            "entry-0": {"x": 0.0, "y": 0.0},
            "entry-1": {"x": 200.0, "y": 200.0},
        }
    )

    with pytest.raises(WallGeometryError, match="row or column"):
        compute_wall_canvas_geometry(hass, wall, ["entry-0", "entry-1"])


async def test_frame_not_placed_on_wall_rejected(hass, make_frame_entry):
    entry = make_frame_entry(entry_id="entry-0", width=1200, height=1600)
    entry.add_to_hass(hass)
    wall = _wall({})

    with pytest.raises(WallGeometryError, match="not placed"):
        compute_wall_canvas_geometry(hass, wall, ["entry-0"])


async def test_empty_member_list_rejected(hass):
    wall = _wall({})
    with pytest.raises(WallGeometryError, match="No frames"):
        compute_wall_canvas_geometry(hass, wall, [])


async def test_missing_config_entry_rejected(hass):
    wall = _wall({"gone-entry": {"x": 0.0, "y": 0.0}})
    with pytest.raises(WallGeometryError, match="no longer configured"):
        compute_wall_canvas_geometry(hass, wall, ["gone-entry"])


async def test_live_follow_device_orientation_wins_over_stale_option(
    hass, make_frame_entry
):
    """A Meural frame with follow-device on and a stale stored orientation
    option must use its live gsensor reading for sizing, not walls.
    tile_dims-style static data -- otherwise a frame that's physically
    flipped since the wall was last saved gets a crop computed against the
    wrong aspect ratio."""
    entry = make_frame_entry(
        entry_id="entry-0",
        width=1200,
        height=1600,
        options={
            CONF_ORIENTATION_FOLLOW_DEVICE: True,
        },
    )
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_DRIVER: DRIVER_MEURAL}
    )

    class _FakeCoordinator:
        data = {"device_orientation": "landscape"}

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = _FakeCoordinator()

    wall = _wall({"entry-0": {"x": 0.0, "y": 0.0}})
    geometry = compute_wall_canvas_geometry(hass, wall, ["entry-0"])

    # Locked landscape on a native-portrait (1200x1600) buffer swaps the
    # effective composition size to 1600x1200.
    assert geometry.canvas_width == 1600
    assert geometry.canvas_height == 1200


async def test_wallpaper_crop_boxes_independent_of_frame_bounding_box(hass, make_frame_entry):
    """The defining property: image_rect is whatever the caller says it is
    -- crop boxes are the frames' own overlap with it, never a canvas
    stretched/refit to the frames' bounding box (the bug this replaced:
    dragging a frame used to resize/distort the "image" to match)."""
    from custom_components.digital_frames.wall_geometry import compute_wallpaper_crop_boxes

    # Tile dims for 1200x1600 portrait tile: width=105, height=140
    placements = {
        "e1": {"x": 40.0, "y": 40.0},
        "e2": {"x": 200.0, "y": 40.0},
        "e3": {"x": 40.0, "y": 200.0},
        "e4": {"x": 200.0, "y": 200.0},
    }
    for eid in ("e1", "e2", "e3", "e4"):
        entry = make_frame_entry(entry_id=eid, width=1200, height=1600)
        entry.add_to_hass(hass)

    wall = _wall(placements)
    # A generously large image rect that fully contains every frame --
    # picked independently of the frames' own span (40..305, 40..340).
    image_rect = {"x": 0.0, "y": 0.0, "width": 1000.0, "height": 1000.0}
    crop_boxes = compute_wallpaper_crop_boxes(hass, wall, image_rect)

    assert set(crop_boxes.keys()) == {"e1", "e2", "e3", "e4"}
    # e1 at (40,40)-(145,180) within a 1000x1000 image.
    c_e1 = crop_boxes["e1"]
    assert c_e1[0] == pytest.approx(40 / 1000)
    assert c_e1[1] == pytest.approx(40 / 1000)
    assert c_e1[2] == pytest.approx(145 / 1000)
    assert c_e1[3] == pytest.approx(180 / 1000)

    # Moving e4 far away must not change e1's crop box at all -- unlike the
    # old bounding-box-stretch model, where every frame's crop shifted
    # whenever *any* frame moved.
    wall.placements["e4"] = {"x": 900.0, "y": 900.0}
    crop_boxes_after_move = compute_wallpaper_crop_boxes(hass, wall, image_rect)
    assert crop_boxes_after_move["e1"] == c_e1


async def test_wallpaper_crop_boxes_partial_overlap_clamped_not_stretched(hass, make_frame_entry):
    """A frame hanging off the image's edge shows exactly what overlaps,
    clamped to [0, 1] -- never stretched to cover the rest of the frame."""
    from custom_components.digital_frames.wall_geometry import compute_wallpaper_crop_boxes

    entry = make_frame_entry(entry_id="e1", width=1200, height=1600)
    entry.add_to_hass(hass)
    # Frame spans (40,40)-(145,180); image only covers up to x=100.
    wall = _wall({"e1": {"x": 40.0, "y": 40.0}})
    image_rect = {"x": 0.0, "y": 0.0, "width": 100.0, "height": 1000.0}

    crop_boxes = compute_wallpaper_crop_boxes(hass, wall, image_rect)

    c_e1 = crop_boxes["e1"]
    assert c_e1[0] == pytest.approx(40 / 100)
    assert c_e1[2] == 1.0  # clamped, not extrapolated past the image's edge


async def test_wallpaper_crop_boxes_no_overlap_is_none(hass, make_frame_entry):
    """A frame entirely outside the image rect gets None, not a degenerate
    or clamped-to-nothing crop box -- the caller should exclude it from
    the resulting scene's mappings rather than send it empty content."""
    from custom_components.digital_frames.wall_geometry import compute_wallpaper_crop_boxes

    entry = make_frame_entry(entry_id="e1", width=1200, height=1600)
    entry.add_to_hass(hass)
    wall = _wall({"e1": {"x": 500.0, "y": 500.0}})
    image_rect = {"x": 0.0, "y": 0.0, "width": 100.0, "height": 100.0}

    crop_boxes = compute_wallpaper_crop_boxes(hass, wall, image_rect)
    assert crop_boxes["e1"] is None


async def test_wallpaper_crop_boxes_unplaced_or_missing_entry_raises(hass, make_frame_entry):
    """Requesting an unplaced frame or missing entry raises WallGeometryError."""
    from custom_components.digital_frames.wall_geometry import compute_wallpaper_crop_boxes

    entry = make_frame_entry(entry_id="e1", width=1200, height=1600)
    entry.add_to_hass(hass)
    wall = _wall({"e1": {"x": 0.0, "y": 0.0}})
    image_rect = {"x": 0.0, "y": 0.0, "width": 1000.0, "height": 1000.0}

    with pytest.raises(WallGeometryError, match="not placed"):
        compute_wallpaper_crop_boxes(hass, wall, image_rect, ["e2"])

    with pytest.raises(WallGeometryError, match="no longer configured"):
        wall_missing = _wall({"e_gone": {"x": 0.0, "y": 0.0}})
        compute_wallpaper_crop_boxes(hass, wall_missing, image_rect, ["e_gone"])


async def test_wallpaper_crop_boxes_invalid_image_rect_raises(hass, make_frame_entry):
    from custom_components.digital_frames.wall_geometry import compute_wallpaper_crop_boxes

    entry = make_frame_entry(entry_id="e1", width=1200, height=1600)
    entry.add_to_hass(hass)
    wall = _wall({"e1": {"x": 0.0, "y": 0.0}})

    with pytest.raises(WallGeometryError, match="positive width/height"):
        compute_wallpaper_crop_boxes(hass, wall, {"x": 0, "y": 0, "width": 0, "height": 100})

    with pytest.raises(WallGeometryError, match="Invalid wallpaper image_rect"):
        compute_wallpaper_crop_boxes(hass, wall, {"x": 0, "y": 0})

