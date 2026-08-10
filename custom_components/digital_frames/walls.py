"""Walls: a virtual layout of a subset of the user's frames, positioned the
way they're physically hung (e.g. 4 frames on the living room wall).

A wall only stores where each frame sits on a free-form canvas -- it never
stores which images are assigned. Loading a scene onto a wall and saving the
result back is entirely a panel-side operation against the existing scenes
API; walls themselves are pure layout state, never referenced by
automations, voice control, or any entity platform.
"""

from __future__ import annotations

import math
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import (
    CONF_HEIGHT,
    CONF_ORIENTATION,
    CONF_SIZE,
    CONF_WIDTH,
    DOMAIN,
    KIND_SCENES_HUB,
    MEURAL_SIZE_LABEL,
    ORIENTATION_LANDSCAPE,
    ORIENTATION_PORTRAIT,
    SAMSUNG_SIZE_LABEL,
    SIGNAL_WALLS_UPDATED,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_STORAGE_KEY = f"{DOMAIN}_walls"
_STORAGE_VERSION = 1

# The default wall: a real Wall record with a fixed sentinel id, guaranteed
# to exist and to hold a placement for every configured frame. Non-deletable
# and non-renamable; otherwise behaves exactly like a custom wall.
DEFAULT_WALL_ID = "default"
DEFAULT_WALL_NAME = "All Frames"
KIND_DEFAULT = "default"
KIND_CUSTOM = "custom"

# Mirror of digital-frames-panel.js's _wallTileDims normalization and GRID snap --
# auto-appended placements must use the same tile geometry the canvas
# renders with, or a new tile could land overlapping an existing one.
# Keep these in sync with the panel.
_TILE_TARGET_LONGEST = 140
_GRID = 20

# Auto-layout-only geometry for the default wall (custom walls have no such
# limit -- users free-place those). A tile's longest edge is always scaled
# to _TILE_TARGET_LONGEST regardless of orientation, so this cell size fits
# any tile without vertical collisions between rows.
_MAX_FRAMES_PER_ROW = 4
_CELL = _TILE_TARGET_LONGEST + _GRID
# Two rows/columns of empty breathing room above and left of the first
# auto-placed tile, instead of starting flush in the corner.
_MARGIN_LEFT = _CELL * 2
_MARGIN_TOP = _CELL * 2


_SIZE_LEADING_NUMBER_RE = re.compile(r"^([\d.]+)")

# Calibration reference: an official 13.3" panel (1200x1600) is the most
# common frame in the wild, so tile_dims() is pinned to reproduce its exact
# pre-existing on-canvas size (105x140) -- every other physical size scales
# relative to that reference instead of getting independently renormalized.
_REFERENCE_DIAGONAL_IN = 13.3
_REFERENCE_RESOLUTION = (1200, 1600)

# Meural/Samsung store a driver label in CONF_SIZE, not an inch figure --
# but each of those drivers only ever targets one real physical size today,
# so the label itself implies a known diagonal: every commercially released
# Meural Canvas (original, II, III) is a 27" panel, and DRIVER_SAMSUNG only
# targets the EM32DX (32" class, per its own model number). Reported by a
# user whose 27" Meural Canvas II rendered the same on-canvas size as an
# unrelated 13.3" Fraimic panel before this map existed.
_KNOWN_DRIVER_DIAGONALS_IN: dict[str, float] = {
    MEURAL_SIZE_LABEL: 27.0,
    SAMSUNG_SIZE_LABEL: 32.0,
}


def _parse_diagonal_inches(size_label: Any) -> float | None:
    """Diagonal inches from a CONF_SIZE label -- a numeric figure (e.g.
    "31.5", "13.3_clone"), or a known driver label (e.g. "meural", see
    _KNOWN_DRIVER_DIAGONALS_IN). None if neither matches."""
    if not isinstance(size_label, str):
        return None
    if size_label in _KNOWN_DRIVER_DIAGONALS_IN:
        return _KNOWN_DRIVER_DIAGONALS_IN[size_label]
    match = _SIZE_LEADING_NUMBER_RE.match(size_label.strip())
    return float(match.group(1)) if match else None


def _physical_dims_inches(
    diagonal_in: float, width_px: int, height_px: int
) -> tuple[float, float]:
    """A panel's physical (width, height) in inches from its diagonal size
    and pixel aspect ratio -- diagonal^2 = w^2 + h^2 with w/h fixed by the
    resolution."""
    aspect = width_px / height_px if height_px else 1.0
    height_in = diagonal_in / math.sqrt(aspect * aspect + 1)
    return height_in * aspect, height_in


def _reference_px_per_inch() -> float:
    ref_w_in, ref_h_in = _physical_dims_inches(_REFERENCE_DIAGONAL_IN, *_REFERENCE_RESOLUTION)
    return _TILE_TARGET_LONGEST / max(ref_w_in, ref_h_in)


# Computed once at import: pixels-per-inch that makes the reference 13.3"
# panel's longest physical edge equal _TILE_TARGET_LONGEST px. Applying this
# same constant to every frame's own physical size (rather than
# renormalizing each frame's longest *pixel* edge independently) is what
# keeps a 31.5" panel visibly larger on canvas than a 13.3" one.
_PX_PER_INCH = _reference_px_per_inch()


def tile_dims(entry: "ConfigEntry") -> tuple[int, int]:
    """A frame's on-canvas tile size (px), aspect-correct, orientation-aware,
    and scaled to the panel's true physical size -- the backend twin of the
    panel's _wallTileDims.

    Two panels with different pixel resolutions but the same diagonal size
    (or vice versa) must render at their correct *relative* size on a wall
    that mixes frame types -- scaling each tile independently to a common
    longest-*pixel*-edge target (the pre-KPF behavior) made a 31.5" panel
    look the same size as a 13.3" one. CONF_SIZE's diagonal-inch label plus
    the resolution's aspect ratio gives true physical width/height; Meural/
    Samsung store a driver label there instead (e.g. "meural"), which maps
    to a known diagonal via _KNOWN_DRIVER_DIAGONALS_IN since each of those
    drivers only ever targets one real physical panel size today. Only a
    truly unrecognized/missing size (a malformed or pre-CONF_SIZE legacy
    entry) falls back to the original longest-pixel-edge formula as-is.
    """
    width = entry.data.get(CONF_WIDTH) or 1200
    height = entry.data.get(CONF_HEIGHT) or 1600
    orientation = entry.options.get(CONF_ORIENTATION)
    if orientation == ORIENTATION_PORTRAIT and width > height:
        width, height = height, width
    if orientation == ORIENTATION_LANDSCAPE and height > width:
        width, height = height, width

    diagonal_in = _parse_diagonal_inches(entry.data.get(CONF_SIZE))
    if diagonal_in is None:
        # Genuinely no diagonal to go on (a malformed entry, or one from
        # before CONF_SIZE existed) -- physical scale is undefined, so fall
        # back to the original longest-pixel-edge normalization exactly
        # rather than guessing.
        scale = _TILE_TARGET_LONGEST / max(width, height)
        return round(width * scale), round(height * scale)

    width_in, height_in = _physical_dims_inches(diagonal_in, width, height)
    return round(width_in * _PX_PER_INCH), round(height_in * _PX_PER_INCH)


class WallError(Exception):
    """Raised for invalid wall operations (bad name, not found)."""


@dataclass
class Wall:
    """A named set of (frame entry_id -> canvas position) placements."""

    wall_id: str
    name: str
    # entry_id -> {"x": .., "y": ..}. Free-form canvas position, not a fixed
    # N×M cell grid -- frames come in different physical sizes/orientations
    # and real gallery walls aren't always a strict matrix. Snapping to a
    # grid unit is purely a client-side drag convenience.
    placements: dict[str, dict[str, float]] = field(default_factory=dict)
    created_at: float = 0.0
    # KIND_DEFAULT for the auto-synced default wall, KIND_CUSTOM otherwise.
    # Walls stored before this field existed deserialize as custom.
    kind: str = KIND_CUSTOM
    # Entry_ids the user deliberately removed from the default wall.
    # Without this tombstone list, the auto-sync would resurrect every
    # removed frame at the next restart. Meaningless on custom walls
    # (absence from placements already says everything there).
    excluded: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wall_id": self.wall_id,
            "name": self.name,
            "placements": self.placements,
            "created_at": self.created_at,
            "kind": self.kind,
            "excluded": self.excluded,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Wall":
        return cls(
            wall_id=data["wall_id"],
            name=data["name"],
            placements=dict(data.get("placements") or {}),
            created_at=data.get("created_at", 0.0),
            kind=data.get("kind") or KIND_CUSTOM,
            excluded=list(data.get("excluded") or []),
        )


class WallManager:
    """Owns the set of user-defined wall layouts."""

    def __init__(self, hass: "HomeAssistant") -> None:
        self.hass = hass
        self._store: Store = Store(hass, _STORAGE_VERSION, _STORAGE_KEY)
        self._walls: dict[str, Wall] = {}

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        for data in (stored or {}).get("walls", []):
            wall = Wall.from_dict(data)
            self._walls[wall.wall_id] = wall

    async def _async_persist(self) -> None:
        await self._store.async_save(
            {"walls": [wall.to_dict() for wall in self._walls.values()]}
        )

    def _frame_entries(self) -> list["ConfigEntry"]:
        return [
            entry
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get("kind") != KIND_SCENES_HUB
        ]

    def _append_placement(self, wall: Wall, entry: "ConfigEntry") -> None:
        """Place *entry* in the next open grid slot: rows of up to
        _MAX_FRAMES_PER_ROW tiles, filled left-to-right and wrapping onto a
        new row underneath, starting _MARGIN_LEFT/_MARGIN_TOP in from the
        canvas edges rather than flush in the corner. Deterministic and
        collision-free by construction; the user drags it wherever they
        want afterwards. This shape is specific to auto-populating the
        default wall -- custom walls have no such row limit.

        The target row always scans for its *actual* current occupants
        rather than trusting `len(wall.placements) % _MAX_FRAMES_PER_ROW ==
        0` to mean "this row is empty" -- after a frame is removed from a
        full row and a new one is added, that count can land back on a
        multiple of _MAX_FRAMES_PER_ROW while the row still holds tiles,
        which used to place the new tile directly on top of a survivor."""
        row = len(wall.placements) // _MAX_FRAMES_PER_ROW
        y = _MARGIN_TOP + row * _CELL
        right_edge = _MARGIN_LEFT
        occupied = False
        for entry_id, pos in wall.placements.items():
            if pos["y"] != y:
                continue
            occupied = True
            placed = self.hass.config_entries.async_get_entry(entry_id)
            width = tile_dims(placed)[0] if placed else _TILE_TARGET_LONGEST
            right_edge = max(right_edge, pos["x"] + width)
        x = _MARGIN_LEFT if not occupied else math.ceil(right_edge / _GRID) * _GRID + _GRID
        wall.placements[entry.entry_id] = {"x": float(x), "y": float(y)}

    async def async_ensure_default_wall(self) -> None:
        """Create the default wall if missing, then reconcile its placements
        against the configured frame entries (add missing, prune stale).
        Called once from async_setup; safe to call repeatedly."""
        changed = False
        wall = self._walls.get(DEFAULT_WALL_ID)
        if wall is None:
            wall = Wall(
                wall_id=DEFAULT_WALL_ID,
                name=DEFAULT_WALL_NAME,
                kind=KIND_DEFAULT,
                created_at=time.time(),
            )
            self._walls[DEFAULT_WALL_ID] = wall
            changed = True

        entries = self._frame_entries()
        entry_ids = {entry.entry_id for entry in entries}
        for stale_id in [eid for eid in wall.placements if eid not in entry_ids]:
            del wall.placements[stale_id]
            changed = True
        if wall.excluded:
            wall.excluded = []
            changed = True
        for entry in entries:
            if entry.entry_id not in wall.placements:
                self._append_placement(wall, entry)
                changed = True

        if changed:
            await self._async_persist()
            async_dispatcher_send(self.hass, SIGNAL_WALLS_UPDATED)

    async def async_ensure_placement(self, entry: "ConfigEntry") -> None:
        """Guarantee *entry* has a spot on the default wall (unless the user
        deliberately removed it -- see Wall.excluded). Called from
        async_setup_entry, so it covers every way a frame arrives (embedded
        add, discovery flow, HA restart). Idempotent."""
        wall = self._walls.get(DEFAULT_WALL_ID)
        if wall is None:
            # async_setup creates the default wall before any entry sets up;
            # this is belt-and-braces for a reload racing that.
            await self.async_ensure_default_wall()
            return
        if entry.entry_id in wall.placements:
            return
        self._append_placement(wall, entry)
        if wall.excluded:
            wall.excluded = []
        await self._async_persist()
        async_dispatcher_send(self.hass, SIGNAL_WALLS_UPDATED)

    async def async_prune_entry(self, entry_id: str) -> None:
        """Drop *entry_id*'s placement from every wall (default and custom)
        when its config entry is removed -- otherwise deleted frames haunt
        wall layouts forever (CODE_REVIEW #28). Tombstones die with the
        entry too: a frame removed and re-added gets a fresh entry_id, so a
        stale exclusion could never match it anyway."""
        changed = False
        for wall in self._walls.values():
            if entry_id in wall.placements:
                del wall.placements[entry_id]
                changed = True
            if entry_id in wall.excluded:
                wall.excluded.remove(entry_id)
                changed = True
        if changed:
            await self._async_persist()
            async_dispatcher_send(self.hass, SIGNAL_WALLS_UPDATED)

    async def async_list_walls(self) -> list[dict[str, Any]]:
        return [wall.to_dict() for wall in self._walls.values()]

    async def async_get_wall(self, wall_id: str) -> Wall | None:
        return self._walls.get(wall_id)

    async def async_get_wall_by_name(self, name: str) -> Wall | None:
        name = (name or "").strip().lower()
        for wall in self._walls.values():
            if wall.name.strip().lower() == name:
                return wall
        return None

    async def async_save_wall(
        self,
        name: str,
        placements: dict[str, dict[str, float]],
        wall_id: str | None = None,
        excluded: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new wall (wall_id=None) or update an existing one.
        *excluded* of None means "leave the stored tombstones unchanged"."""
        name = (name or "").strip()
        if not name:
            raise WallError("Wall name can't be empty")

        placements = {
            entry_id: {"x": float(pos["x"]), "y": float(pos["y"])}
            for entry_id, pos in (placements or {}).items()
            if entry_id and isinstance(pos, dict) and "x" in pos and "y" in pos
        }

        if wall_id is not None and wall_id not in self._walls:
            # Updating a wall that's gone (e.g. deleted from another tab
            # since this edit was opened) must fail, not silently resurrect
            # it under its old id with whatever's in this stale form.
            raise WallError(f"Wall '{wall_id}' not found")

        existing_by_name = await self.async_get_wall_by_name(name)
        if existing_by_name is not None and existing_by_name.wall_id != wall_id:
            raise WallError(f"A wall named '{name}' already exists")

        if wall_id is not None:
            wall = self._walls[wall_id]
            if wall.kind == KIND_DEFAULT:
                # The default wall accepts layout changes but keeps its
                # identity. We must keep all configured frames on the wall.
                # If a frame was omitted (e.g. pulled off in UI), we preserve its last known placement.
                updated_placements = {}
                entries = self._frame_entries()
                for entry in entries:
                    eid = entry.entry_id
                    if eid in placements:
                        updated_placements[eid] = placements[eid]
                    elif eid in wall.placements:
                        updated_placements[eid] = wall.placements[eid]
                wall.placements = updated_placements
                # In case any new frames were added and somehow missed placements, let's run append_placement.
                for entry in entries:
                    if entry.entry_id not in wall.placements:
                        self._append_placement(wall, entry)
                wall.excluded = []
            else:
                wall.name = name
                wall.placements = placements
                if excluded is not None:
                    wall.excluded = [
                        e for e in excluded if isinstance(e, str) and e
                    ]
        else:
            wall = Wall(
                wall_id=uuid.uuid4().hex[:12],
                name=name,
                placements=placements,
                created_at=time.time(),
            )
            self._walls[wall.wall_id] = wall

        await self._async_persist()
        async_dispatcher_send(self.hass, SIGNAL_WALLS_UPDATED)
        return wall.to_dict()

    async def async_delete_wall(self, wall_id: str) -> None:
        wall = self._walls.get(wall_id)
        if wall is None:
            return
        if wall.kind == KIND_DEFAULT:
            raise WallError("The default wall can't be deleted")
        del self._walls[wall_id]
        await self._async_persist()
        async_dispatcher_send(self.hass, SIGNAL_WALLS_UPDATED)
