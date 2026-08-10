"""Wall canvas geometry: compute a shared banner canvas and each member
frame's exact crop slice out of it, for a "message" split across a wall.

v1 is deliberately scoped to a single row or column of same-resolution
frames -- text is seam-sensitive in a way photos aren't, and an uneven/2D
wall layout gives the message renderer no way to know where a bezel gap
falls. Restricting to a uniform line keeps every seam at an exact i/N
fraction, so no scale-factor math or center-of-mass guessing is needed; a
layout this repo can't render safely is rejected with a clear error
instead of producing a silently ugly banner.

walls.Wall.placements supplies each member frame's *position* only -- its
*size* is resolved fresh via helpers.render_spec_for_hass_entry, not
walls.tile_dims (a static, preview-canvas-only snapshot that can disagree
with a follow-device frame's live gsensor orientation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry  # noqa: F401
    from homeassistant.core import HomeAssistant

    from .walls import Wall

# Placement coordinates come from the panel's drag UI (walls.py's _GRID =
# 20 snap) -- a few pixels of jitter between frames meant to share a row or
# column is normal drag imprecision, not a layout mistake.
_COLINEAR_TOLERANCE = 30.0


class WallGeometryError(Exception):
    """Raised when a wall's member frames can't be composed into one shared
    banner canvas -- mismatched resolutions, frames not placed on the wall,
    or not arranged in a single row/column."""


@dataclass(frozen=True)
class WallCanvasGeometry:
    """One shared banner canvas size, and each member frame's fractional
    crop box (x0, y0, x1, y1) into it -- ready to hand straight to
    panel_codec.encode_for_panel[_with_preview]'s crop_box param."""

    canvas_width: int
    canvas_height: int
    crop_boxes: dict[str, tuple[float, float, float, float]]


def compute_wall_canvas_geometry(
    hass: "HomeAssistant", wall: "Wall", member_entry_ids: list[str]
) -> WallCanvasGeometry:
    """Compute a shared banner canvas + per-frame crop slices for *wall*'s
    given member frames.

    Raises WallGeometryError if:
    - member_entry_ids is empty
    - any entry_id isn't placed on this wall, or its config entry is gone
    - member frames don't all share the same effective (width, height)
      (post orientation-lock -- see helpers.render_spec_for_hass_entry)
    - more than one frame is given and they aren't colinear (all sharing
      one x -> a column, or one y -> a row)
    """
    from .helpers import render_spec_for_hass_entry  # noqa: PLC0415

    if not member_entry_ids:
        raise WallGeometryError("No frames given to compose a wall banner for")

    sizes: set[tuple[int, int]] = set()
    positions: dict[str, tuple[float, float]] = {}
    for entry_id in member_entry_ids:
        placement = wall.placements.get(entry_id)
        if placement is None:
            raise WallGeometryError(
                f"Frame '{entry_id}' is not placed on wall '{wall.wall_id}'"
            )
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            raise WallGeometryError(f"Frame '{entry_id}' is no longer configured")
        spec = render_spec_for_hass_entry(hass, entry)
        sizes.add((spec.width, spec.height))
        positions[entry_id] = (float(placement["x"]), float(placement["y"]))

    if len(sizes) > 1:
        raise WallGeometryError(
            "Wall banner messages require every target frame to share the "
            f"same resolution; got {sorted(sizes)}"
        )
    frame_w, frame_h = next(iter(sizes))

    xs = [pos[0] for pos in positions.values()]
    ys = [pos[1] for pos in positions.values()]
    is_row = (max(ys) - min(ys)) <= _COLINEAR_TOLERANCE
    is_column = (max(xs) - min(xs)) <= _COLINEAR_TOLERANCE
    if len(member_entry_ids) > 1 and not (is_row or is_column):
        raise WallGeometryError(
            "Wall banner messages require target frames arranged in a "
            "single row or column"
        )

    # A lone frame is trivially both a "row" and a "column" of one -- pick
    # row arbitrarily; it degenerates to the same (0,0,1,1) crop box either
    # way.
    axis = "row" if (is_row or len(member_entry_ids) == 1) else "column"
    if axis == "row":
        ordered = sorted(member_entry_ids, key=lambda eid: positions[eid][0])
    else:
        ordered = sorted(member_entry_ids, key=lambda eid: positions[eid][1])

    n = len(ordered)
    canvas_width = frame_w * n if axis == "row" else frame_w
    canvas_height = frame_h if axis == "row" else frame_h * n

    crop_boxes: dict[str, tuple[float, float, float, float]] = {}
    for i, entry_id in enumerate(ordered):
        if axis == "row":
            crop_boxes[entry_id] = (i / n, 0.0, (i + 1) / n, 1.0)
        else:
            crop_boxes[entry_id] = (0.0, i / n, 1.0, (i + 1) / n)

    return WallCanvasGeometry(
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        crop_boxes=crop_boxes,
    )


def compute_wallpaper_crop_boxes(
    hass: "HomeAssistant",
    wall: "Wall",
    image_rect: dict[str, float],
    member_entry_ids: list[str] | None = None,
) -> dict[str, tuple[float, float, float, float] | None]:
    """Each target frame's crop_box (x0, y0, x1, y1) as a fraction of the
    wallpaper *image's own rect* -- not of the frames' bounding box.

    *image_rect* (``{"x", "y", "width", "height"}``) is the background
    image's position/size in the same wall-canvas-px coordinate space as
    ``Wall.placements`` -- entirely independent of where any frame sits.
    That independence is the point: dragging a frame only changes which
    part of this fixed rect its window reveals; it never changes the
    rect's own position, size, or aspect ratio (an earlier version of this
    function stretched a shared canvas to exactly fit the frames' bounding
    box, which made the "image" resize/distort every time a frame moved --
    a real bug once users could reposition frames after placing the
    wallpaper). Scaling the image (the user's "zoom") is a deliberate,
    separate action that changes *image_rect* directly, never a side
    effect of frame placement.

    A frame that doesn't overlap image_rect at all gets `None` (nothing of
    the image falls behind it -- the caller should exclude it from the
    resulting scene's mappings, not send it a degenerate/empty crop). A
    partial overlap (the frame hangs off an edge of the image) is clamped
    to [0, 1] per edge -- exactly what's actually behind the frame, with
    no stretching to cover the rest of it.
    """
    from .walls import tile_dims  # noqa: PLC0415

    target_ids = (
        list(member_entry_ids)
        if member_entry_ids is not None
        else list(wall.placements.keys())
    )
    if not target_ids:
        raise WallGeometryError("No frames given to compute wallpaper crop boxes for")

    try:
        img_x = float(image_rect["x"])
        img_y = float(image_rect["y"])
        img_w = float(image_rect["width"])
        img_h = float(image_rect["height"])
    except (KeyError, TypeError, ValueError) as err:
        raise WallGeometryError(f"Invalid wallpaper image_rect: {image_rect!r}") from err
    if img_w <= 0 or img_h <= 0:
        raise WallGeometryError("Wallpaper image_rect must have positive width/height")

    crop_boxes: dict[str, tuple[float, float, float, float] | None] = {}
    for entry_id in target_ids:
        placement = wall.placements.get(entry_id)
        if placement is None:
            raise WallGeometryError(
                f"Frame '{entry_id}' is not placed on wall '{wall.wall_id}'"
            )
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            raise WallGeometryError(f"Frame '{entry_id}' is no longer configured")

        t_w, t_h = tile_dims(entry)
        fx = float(placement.get("x", 0.0))
        fy = float(placement.get("y", 0.0))

        x0 = (fx - img_x) / img_w
        y0 = (fy - img_y) / img_h
        x1 = (fx + t_w - img_x) / img_w
        y1 = (fy + t_h - img_y) / img_h

        if x1 <= 0.0 or y1 <= 0.0 or x0 >= 1.0 or y0 >= 1.0:
            crop_boxes[entry_id] = None
            continue

        crop_boxes[entry_id] = (
            max(0.0, min(1.0, x0)),
            max(0.0, min(1.0, y0)),
            max(0.0, min(1.0, x1)),
            max(0.0, min(1.0, y1)),
        )

    return crop_boxes

