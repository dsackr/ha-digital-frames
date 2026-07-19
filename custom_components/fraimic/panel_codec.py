"""PanelCodec: explicit encode boundary for local Spectra frames.

Phase 1 FramePort seam (see docs/FRAME_PORT.md):

- **Core** decides which image goes to which frame and at what geometry.
- **PanelCodec** turns source pixels into wire payload bytes (Spectra 6
  split-half vs sequential today).
- **Transport** (coordinator) delivers those bytes and applies sleep-queue /
  timeout policy from the panel profile.

The 7.3" community panel is the worked example of multi-codec under one
driver: same ``POST /api/image`` family as official Fraimic, different
``codec_id`` (``spectra6_sequential``) and packing path.

Library backfill and on-demand send encoding should call
:func:`encode_for_panel` rather than importing ``image_converter`` directly,
so there is one named place where codec selection is owned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .frame_types import (
    CODEC_SPECTRA6_SEQUENTIAL,
    CODEC_SPECTRA6_SPLIT_HALF,
    FRAME_TYPES,
    LAYOUT_SEQUENTIAL,
    LAYOUT_SPLIT_HALF,
    codec_id_for_resolution,
    frame_type_for_resolution,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


@dataclass(frozen=True)
class PanelCodec:
    """How pixels become wire bytes for one panel family."""

    id: str
    byte_layout: str  # LAYOUT_* — what packers and external render scripts use
    color_mode: str = "spectra6"
    preferred_payload: str = "spectra6_bin"


# Registry of codecs this integration can produce. FrameType.codec_id must
# resolve into this map.
CODECS: dict[str, PanelCodec] = {
    CODEC_SPECTRA6_SPLIT_HALF: PanelCodec(
        id=CODEC_SPECTRA6_SPLIT_HALF,
        byte_layout=LAYOUT_SPLIT_HALF,
    ),
    CODEC_SPECTRA6_SEQUENTIAL: PanelCodec(
        id=CODEC_SPECTRA6_SEQUENTIAL,
        byte_layout=LAYOUT_SEQUENTIAL,
    ),
}


def panel_codec_for_id(codec_id: str) -> PanelCodec:
    """Look up a codec by stable id."""
    try:
        return CODECS[codec_id]
    except KeyError as err:
        raise ValueError(f"Unknown panel codec id {codec_id!r}") from err


def panel_codec_for_resolution(width: int, height: int) -> PanelCodec:
    """Resolve codec from panel resolution (orientation-agnostic)."""
    return panel_codec_for_id(codec_id_for_resolution(width, height))


def panel_codec_for_frame_type_id(size: str) -> PanelCodec:
    """Resolve codec from CONF_SIZE / FRAME_TYPES id (e.g. \"7.3\")."""
    try:
        frame_type = FRAME_TYPES[size]
    except KeyError as err:
        raise ValueError(f"Unknown frame type id {size!r}") from err
    return panel_codec_for_id(frame_type.codec_id)


def panel_codec_for_entry(entry: "ConfigEntry") -> PanelCodec:
    """Resolve codec for a config entry (size first, then width/height)."""
    size = entry.data.get("size")
    if isinstance(size, str) and size in FRAME_TYPES:
        return panel_codec_for_frame_type_id(size)

    width = entry.data.get("width")
    height = entry.data.get("height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        return panel_codec_for_resolution(width, height)

    raise ValueError(
        f"Config entry {entry.entry_id} has no size or dimensions to resolve a panel codec"
    )


def byte_layout_for_codec(codec: PanelCodec | str) -> str:
    """Layout name for packers / skill renderer config.json."""
    if isinstance(codec, PanelCodec):
        return codec.byte_layout
    return panel_codec_for_id(codec).byte_layout


def encode_for_panel(
    source_bytes: bytes,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
    pack_method: str = "fast",
    crop_box: tuple[float, float, float, float] | list[float] | None = None,
) -> bytes:
    """Encode a source image into wire payload for the panel at *width*×*height*.

    Codec selection is by resolution via the frame-type registry (split-half
    for official 13.3"/31.5" and 13.1" community; sequential for 7.3").
    Callers must not special-case 7.3" themselves.

    This is the single high-level encode entry point for library send and
    backfill. Packing still lives in image_converter; this module owns
    *which* codec runs for a given panel geometry.

    Positional-friendly signature so callers can pass this to
    ``hass.async_add_executor_job`` without kwargs.
    """
    # Touch the registry so an unregistered resolution fails *here* with a
    # codec-oriented error before the packer runs.
    _ = frame_type_for_resolution(width, height)

    from .image_converter import (  # noqa: PLC0415 — avoid import cycle at load
        convert_image_bytes,
        convert_image_bytes_cropped,
    )

    if crop_box is not None:
        return convert_image_bytes_cropped(
            source_bytes,
            width,
            height,
            tuple(crop_box),
            rotation,
            pack_method,
        )
    return convert_image_bytes(
        source_bytes,
        width,
        height,
        rotation,
        locked,
        pack_method,
    )


def encode_for_panel_with_preview(
    source_bytes: bytes,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
) -> tuple[bytes, bytes]:
    """Like :func:`encode_for_panel`, plus a small PNG of the quantized image.

    Used by raw-upload / media-service paths that have no library image_id
    for a thumbnail.
    """
    _ = frame_type_for_resolution(width, height)
    from .image_converter import convert_image_bytes_with_preview  # noqa: PLC0415

    return convert_image_bytes_with_preview(
        source_bytes, width, height, rotation, locked
    )


def encode_path_for_panel_with_preview(
    image_path: str,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
) -> tuple[bytes, bytes]:
    """Encode a filesystem path for the panel, with preview PNG."""
    _ = frame_type_for_resolution(width, height)
    from .image_converter import convert_image_with_preview  # noqa: PLC0415

    return convert_image_with_preview(image_path, width, height, rotation, locked)
