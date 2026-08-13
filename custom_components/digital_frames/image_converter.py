"""
Spectra 6 image converter for Fraimic e-ink frames.

Converts arbitrary images (any format Pillow supports) to the raw binary format
expected by the target panel. All Fraimic-supported panels share the same 4bpp
Spectra 6 palette, but NOT the same byte layout -- see "Binary format
specification" below. Getting this wrong doesn't error, it silently produces a
garbled/duplicated image on the physical frame (confirmed the hard way: see
the 7.3" panel investigation that led to declaring byte_layout explicitly
per frame type in frame_types.py).

Binary format specification
----------------------------
Common to every panel:
- 4 bits per pixel (one nibble)
- 2 pixels packed per byte: high nibble = first pixel of the pair, low
  nibble = second
- Pixels are scanned in normal row-major order: y from top to bottom, x from
  left to right
- Nibble values map to Spectra 6 colors (note: value 4 is unused by the hardware):
    0 = Black
    1 = White
    2 = Yellow
    3 = Red
    5 = Blue
    6 = Green

Byte ordering differs by physical panel construction, declared per frame
type in frame_types.py (FrameType.byte_layout) rather than inferred:

- **Split-half** (confirmed against Fraimic's own reference converter,
  github.com/Fraimic/fraimic_bin_converter, EL133UF1 / Spectra 6 13.3"):
  each row is split into a LEFT half (columns 0 .. width//2 - 1) and a RIGHT
  half (columns width//2 .. width - 1). ALL left-half bytes for the entire
  image come first (every row, top to bottom), followed by ALL right-half
  bytes (every row, top to bottom) -- matching a panel physically built from
  two side-by-side half-width e-ink halves, each driven from its own
  contiguous block of the buffer. Used by the 13.3" (EL133UF1) panels.
- **Sequential** (confirmed against Waveshare's own epd7in3e.py reference
  driver for the 7.3" E6 panel): one single contiguous buffer, pixel pairs
  packed in plain left-to-right, top-to-bottom order with no half-split.
  Used by the 7.3" panel.
- **Split 8 bands / vertical chunks** (31.5" EL315, reverse-engineered on
  glass 2026-08-04 -- no public reference converter exists): panel is
  portrait-native 1440x2560. The wire payload is a fixed 2,304,000 bytes,
  NOT width*height/2 (1,843,200): eight 288,000-byte blocks, block 0 =
  BOTTOM band of the glass, block 7 = top. Gate-line heights bottom-up are
  400,400,400,80,400,400,400,80 -- the two 80-line bands (blocks 3 and 7,
  one per gate-driver half of the panel) still carry a full 400 bytes per
  chunk on the wire; their last 320 bytes are padding the panel discards.
  Each block is the LEFT half (720 columns) then the RIGHT half. Each half
  is 360 vertical chunks of 400 bytes; chunk q covers columns (2q, 2q+1)
  left to right, and byte p within a chunk is gate line p counting UP from
  the band's bottom edge (a 90-degree transpose of ordinary raster order).

Conversion pipeline
--------------------
1. Open image (any format Pillow supports)
2. Handle a landscape/portrait mismatch between image and target:
   - default (unlocked, the Fraimic way): rotate the image 90 degrees so it
     fills the frame sideways at full size
   - locked=True (frame has an orientation lock): keep the image upright
     and let step 3's centered cover-crop trim it to the target shape
3. Scale to cover the target dimensions (preserving aspect ratio) and
   center -- overflow is cropped
4. Optionally rotate the finished canvas (90/180/270) -- used for frames
   physically hung in their non-native orientation and/or upside down
5. Quantize to the 6 Spectra 6 real-world colors using Floyd-Steinberg
   dithering (this module's own default when color_pipeline is omitted) --
   or the "vivid" pipeline (CONF_COLOR_PIPELINE="vivid", the default for
   every configured Fraimic frame unless a frame opts back to "fast"): see
   "Vivid color pipeline" below and docs/KEY_PRODUCT_FLOWS.md KPF 7.
6. Pack pixels into the nibble format described above, using the byte
   ordering that matches the final resolution's physical panel
"""

from __future__ import annotations

import io
import math
from typing import Any, Tuple

try:
    from PIL import Image, ImageEnhance, ImageFilter
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Pillow is required for image conversion. "
        "Install it with: pip install Pillow"
    ) from exc

try:  # Optional: makes the "fast" packer fully vectorized. Not required.
    import numpy as _np
except ImportError:  # pragma: no cover
    _np = None

from .frame_types import (
    LAYOUT_SPLIT_8_BANDS_VCHUNKS,
    LAYOUT_SPLIT_HALF,
    LAYOUT_SPLIT_TOP_BOTTOM,
    frame_type_for_resolution,
)


# ---------------------------------------------------------------------------
# Palette constants
# ---------------------------------------------------------------------------

# Real-world RGB values measured from an actual Spectra 6 display under D65
# lighting (from the epdoptimize project). These are used as the quantization
# target so that dithering error diffusion is computed in perceptually accurate
# colour space rather than against idealised primaries.
SPECTRA6_REAL_WORLD_RGB: Tuple[Tuple[int, int, int], ...] = (
    (25, 30, 33),     # Black   → nibble 0
    (232, 232, 232),  # White   → nibble 1
    (239, 222, 68),   # Yellow  → nibble 2
    (178, 19, 24),    # Red     → nibble 3
    (33, 87, 186),    # Blue    → nibble 5
    (18, 95, 32),     # Green   → nibble 6
)

# Raw nibble values that the Spectra 6 hardware expects for each palette entry.
# Note that value 4 is intentionally skipped (unused by the hardware).
SPECTRA6_NIBBLE_VALUES: Tuple[int, ...] = (0, 1, 2, 3, 5, 6)

# Sanity check: palette and nibble tables must stay in sync.
assert len(SPECTRA6_REAL_WORLD_RGB) == len(SPECTRA6_NIBBLE_VALUES)

# Color pipeline selector values (mirrors const.CONF_COLOR_PIPELINE's
# choices; duplicated here rather than imported to avoid a dependency on HA
# config plumbing from this module, which is also used standalone/in tests).
COLOR_PIPELINE_FAST = "fast"
COLOR_PIPELINE_VIVID = "vivid"

# Bumped whenever the FAST pipeline's output bytes change, so library.py's
# .bin cache path can include it and old bins miss + regenerate instead of
# serving stale colors forever (mirrors the historical COLOR_PIPELINE_ID
# mechanism from the reverted cp2/cp3 experiment -- see KPF 7). "1" was the
# original Floyd-Steinberg-only pipeline (no enhance chain); "2"
# (2026-08-09) folded in the Fraimic enhance chain (_enhance_for_panel).
# Bump again if the fast pipeline's output changes in the future.
FAST_PIPELINE_CACHE_VERSION = "2"

# ---------------------------------------------------------------------------
# Fraimic-aligned enhance chain + "Vivid" opt-in dithering
# (github.com/Fraimic/fraimic_bin_converter; see CONF_COLOR_PIPELINE / const.py)
#
# Their reference converter's pre-quantize step is a brightness/contrast/
# saturation/sharpen enhance chain; their color-matching step is Atkinson
# dither against idealized 6-color primaries with a tuned RGB+luma distance
# metric (Section 6 of the EL315 spec explicitly leaves both to "tool
# authors"). These two pieces have very different costs, so they're split:
#
# - The enhance chain (_enhance_for_panel) is near-free (~0.1-0.15s even at
#   31.5" resolution) and applies to BOTH pipelines below -- it's just part
#   of the default pipeline now, no opt-in needed.
# - The idealized-primary Atkinson dither (_quantize_vivid_p) is roughly two
#   orders of magnitude slower than Floyd-Steinberg (seconds, not
#   milliseconds, per image -- worse on weaker hardware and during a
#   library-wide backfill), so it's selected per-frame via
#   CONF_COLOR_PIPELINE (const.DEFAULT_COLOR_PIPELINE) rather than forced on
#   every panel regardless of hardware. As of 2026-08-12 it IS the default
#   for every configured Fraimic frame (a deliberate product decision,
#   revisiting the "never the default" stance below) -- a frame on weak
#   hardware can still opt back to "fast" in its options.
#
# 2026-07-30 history: an earlier attempt (commits 9679ec5/24367e1, "cp2"/
# "cp3") shipped a very similar Atkinson port as the new *default* pipeline
# without benchmarking it at real panel resolution first -- a naive
# per-pixel loop took 20-40+ seconds per image on the 31.5" panel and got
# reverted the same day (see docs/KEY_PRODUCT_FLOWS.md KPF 7). This version
# is LUT-accelerated (~5-10x faster: a precomputed nearest-color lookup
# replaces the per-pixel 6-way distance calculation), and -- unlike cp2/cp3
# -- only the genuinely expensive part is gated behind opt-in; the cheap
# enhance chain was benchmarked separately and folded into the default path.
# ---------------------------------------------------------------------------

# Fraimic CLI defaults (convert_to_bin_spectra6.py --brightness/--contrast/--saturation).
_ENHANCE_BRIGHTNESS = 1.1
_ENHANCE_CONTRAST = 1.2
_ENHANCE_SATURATION = 1.2

# Idealized 6-color primaries (PALETTE_COLORS in Fraimic's script) used only
# as the vivid pipeline's internal dither *target*. Packed nibbles and the
# preview/output image still map through SPECTRA6_REAL_WORLD_RGB above --
# that's what the panel actually renders for a given nibble regardless of
# which colors the matching math aimed for while choosing it.
SPECTRA6_VIVID_TARGET_RGB: Tuple[Tuple[int, int, int], ...] = (
    (0, 0, 0),        # Black
    (255, 255, 255),  # White
    (255, 255, 0),    # Yellow
    (255, 0, 0),      # Red
    (0, 0, 255),      # Blue
    (0, 255, 0),      # Green
)
assert len(SPECTRA6_VIVID_TARGET_RGB) == len(SPECTRA6_NIBBLE_VALUES)

# Grid step (out of 256) for the precomputed nearest-vivid-color LUT. Built
# once per process and cached; smaller steps are more accurate but slower
# to build and use more memory (step=4 -> 64^3 = 262,144 entries).
_VIVID_LUT_STEP = 4

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_palette_image() -> "Image.Image":
    """
    Build a single-pixel palette image used by Pillow's quantize() method.

    The palette must be padded to 256 entries (768 bytes); unused slots are
    filled with the first colour (black) so that any accidental match maps to
    a valid colour rather than an arbitrary one.
    """
    pal_image = Image.new("P", (1, 1))
    flat_palette = tuple(v for rgb in SPECTRA6_REAL_WORLD_RGB for v in rgb)
    # Pad to 256 colours × 3 channels = 768 bytes.
    padding_colour = SPECTRA6_REAL_WORLD_RGB[0]  # black
    padding = padding_colour * (256 - len(SPECTRA6_REAL_WORLD_RGB))
    pal_image.putpalette(flat_palette + padding)
    return pal_image


def _resize_cover_centered(
    image: "Image.Image",
    target_width: int,
    target_height: int,
) -> "Image.Image":
    """
    Scale *image* (preserving aspect ratio) so it fully covers
    *target_width* × *target_height*, then center it on the canvas. Whatever
    overflows the canvas is cropped away -- i.e. a centered "cover" crop, not
    a letterbox. (Historically misnamed: this function has always used
    max-scaling, so it has always cropped rather than padded.)
    """
    orig_w, orig_h = image.size

    # Scale so that the image covers the entire target area. Round up
    # (not int()'s truncate-toward-zero): floating-point error routinely
    # lands scale a hair under the exact target, and int() truncation then
    # leaves the resized image 1px short on the governing axis -- a stray
    # unfilled white row/column at the edge of the canvas below. Any 1px
    # overage from rounding up is trimmed by the centered crop below, so
    # this can only shrink or eliminate the gap, never introduce one.
    scale = max(target_width / orig_w, target_height / orig_h)
    scaled_w = math.ceil(orig_w * scale)
    scaled_h = math.ceil(orig_h * scale)

    resized = image.resize((scaled_w, scaled_h), Image.LANCZOS)

    canvas = Image.new("RGB", (target_width, target_height), (255, 255, 255))
    left = (target_width - scaled_w) // 2
    top = (target_height - scaled_h) // 2
    canvas.paste(resized, (left, top))
    return canvas


def _crop_to_box(
    image: "Image.Image",
    crop_box: "Tuple[float, float, float, float]",
) -> "Image.Image":
    """
    Crop *image* to the normalized rectangle *crop_box* = (x0, y0, x1, y1),
    where each value is a fraction (0.0-1.0) of the source image's full
    width/height. Used by the manual-crop path (as opposed to the automatic
    letterbox path above) -- the caller is responsible for choosing a box
    whose aspect ratio already matches the eventual target width/height, so
    no padding or distortion is introduced by the subsequent resize.

    Coordinates are clamped to [0, 1] and reordered/widened as needed so the
    result is always a valid, non-empty box within the image bounds.
    """
    orig_w, orig_h = image.size
    x0, y0, x1, y1 = crop_box

    x0, x1 = sorted((min(max(x0, 0.0), 1.0), min(max(x1, 0.0), 1.0)))
    y0, y1 = sorted((min(max(y0, 0.0), 1.0), min(max(y1, 0.0), 1.0)))

    left = int(round(x0 * orig_w))
    top = int(round(y0 * orig_h))
    right = int(round(x1 * orig_w))
    bottom = int(round(y1 * orig_h))

    # Guarantee at least a 1px box even if rounding collapsed it to nothing.
    right = max(right, left + 1)
    bottom = max(bottom, top + 1)
    right = min(right, orig_w)
    bottom = min(bottom, orig_h)
    left = min(left, right - 1)
    top = min(top, bottom - 1)

    return image.crop((left, top, right, bottom))


def default_cover_crop_box(
    orig_width: int, orig_height: int, target_width: int, target_height: int
) -> "Tuple[float, float, float, float]":
    """
    Compute a centred crop rectangle (normalized 0-1 coordinates against the
    original image) whose aspect ratio exactly matches
    *target_width* : *target_height*, sized as large as possible without
    exceeding the original image -- i.e. the same centred "cover" framing
    _resize_with_letterbox would produce if it cropped instead of padding.

    This is the starting point the crop editor shows for an image that
    doesn't have a saved crop yet for the chosen frame, and exactly the
    framing the automatic (no-saved-crop) locked-orientation path produces.
    """
    target_ratio = target_width / target_height
    orig_ratio = orig_width / orig_height

    if orig_ratio > target_ratio:
        # Original is relatively wider than the target -- crop the sides.
        crop_w = orig_height * target_ratio
        crop_h = float(orig_height)
    else:
        # Original is relatively taller than the target -- crop top/bottom.
        crop_w = float(orig_width)
        crop_h = orig_width / target_ratio

    x0 = (orig_width - crop_w) / 2 / orig_width
    y0 = (orig_height - crop_h) / 2 / orig_height
    return (x0, y0, 1 - x0, 1 - y0)


def _auto_rotate(
    image: "Image.Image",
    target_width: int,
    target_height: int,
) -> "Image.Image":
    """
    Rotate *image* by 90° if its landscape/portrait orientation does not match
    the target dimensions, so that the image fills the frame as well as
    possible without unnecessary black bars.

    The rotation direction (90° vs 270°) is chosen to match the reference
    implementation default (270°, i.e. clockwise 90°).
    """
    img_w, img_h = image.size
    img_is_landscape = img_w > img_h
    tgt_is_landscape = target_width > target_height

    if img_is_landscape != tgt_is_landscape:
        # Rotate 270° clockwise (= 90° counter-clockwise) with expand so the
        # canvas resizes to match the new orientation.
        image = image.rotate(270, expand=True)

    return image


def _quantize_to_spectra6(image: "Image.Image") -> "Image.Image":
    """
    Quantize *image* (must be RGB) to the 6 Spectra 6 real-world colours using
    Floyd-Steinberg error-diffusion dithering.

    Returns an RGB image where every pixel is one of the six palette entries in
    :data:`SPECTRA6_REAL_WORLD_RGB`.
    """
    pal_image = _build_palette_image()
    # quantize() returns a palette-mode image; convert back to RGB so that
    # pixel values are plain (r, g, b) tuples for the packing step.
    return image.quantize(
        dither=Image.Dither.FLOYDSTEINBERG,
        palette=pal_image,
    ).convert("RGB")


def _nibble_for_pixel(quantized_image: "Image.Image", x: int, y: int) -> int:
    """Look up the Spectra 6 nibble value for the pixel at (x, y)."""
    r, g, b = quantized_image.load()[x, y]
    try:
        index = SPECTRA6_REAL_WORLD_RGB.index((r, g, b))
    except ValueError:
        raise ValueError(
            f"Unexpected pixel colour ({r}, {g}, {b}) at ({x}, {y}). "
            "Quantization should have constrained all pixels to the "
            "Spectra 6 palette."
        )
    return SPECTRA6_NIBBLE_VALUES[index]


def _pack_row_half(
    quantized_image: "Image.Image", y: int, start_x: int, end_x: int
) -> bytes:
    """Pack columns [start_x, end_x) of row *y* into bytes (ascending pairs)."""
    out = bytearray()
    width = quantized_image.width
    for x in range(start_x, end_x, 2):
        high_nibble = _nibble_for_pixel(quantized_image, x, y)
        odd_x = x + 1
        if odd_x < end_x and odd_x < width:
            low_nibble = _nibble_for_pixel(quantized_image, odd_x, y)
        else:
            # Odd-width half — pad the missing partner pixel with white.
            low_nibble = SPECTRA6_NIBBLE_VALUES[
                SPECTRA6_REAL_WORLD_RGB.index((232, 232, 232))
            ]
        out.append((high_nibble << 4) | low_nibble)
    return bytes(out)


def _pack_to_spectra6_bin(quantized_image: "Image.Image") -> bytes:
    """
    Pack a quantized RGB image into the raw Spectra 6 binary format, using
    the PanelCodec declared for a registered frame type at this image's
    resolution (see frame_types.py / panel_codec.py and the module docstring).

    :param quantized_image: RGB image whose pixels are restricted to the six
        entries of :data:`SPECTRA6_REAL_WORLD_RGB`.
    :returns: Raw bytes ready to be sent as a ``.bin`` file.
    :raises ValueError: If a pixel colour does not match any palette entry
        (indicates a bug in the quantization step), or if no registered
        frame type has this image's resolution.
    """
    # Codec selection: resolution → FrameType → byte_layout (split_half for
    # official panels, sequential for 7.3"). Callers that only have geometry
    # land here; library paths should prefer panel_codec.encode_for_panel so
    # the seam is obvious at the call site.
    layout = frame_type_for_resolution(
        quantized_image.width, quantized_image.height
    ).byte_layout
    if layout == LAYOUT_SPLIT_HALF:
        return _pack_split_halves(quantized_image)
    if layout == LAYOUT_SPLIT_TOP_BOTTOM:
        return _pack_split_top_bottom(quantized_image)
    if layout == LAYOUT_SPLIT_8_BANDS_VCHUNKS:
        return _pack_split_8_bands_vchunks(quantized_image)
    return _pack_sequential(quantized_image)


# 31.5" EL315 band geometry: gate-line height of each of the 8 wire blocks,
# block 0 (first on the wire) = BOTTOM band of the glass. Blocks 3 and 7 are
# the thin 80-line bands (one per gate-driver half: 3*400 + 80 = 1280 lines
# per half, 2560 total). Every block still carries CHUNK bytes per chunk on
# the wire; a thin block's bytes beyond its height are padding.
_VCHUNK_BAND_GATES: Tuple[int, ...] = (400, 400, 400, 80, 400, 400, 400, 80)
_VCHUNK_CHUNK_BYTES = 400
_VCHUNK_HEIGHT = 2560  # sum of _VCHUNK_BAND_GATES


def split_8_bands_vchunks_wire_size(width: int) -> int:
    """Wire payload size for the banded vertical-chunk layout: every block
    carries 8 * 400 = 3200 gate-lines' worth of bytes for *width* pixels,
    including the discarded padding lines (2,304,000 bytes at 1440 wide)."""
    return 8 * _VCHUNK_CHUNK_BYTES * width // 2


def wire_size_for_layout(layout: str, width: int, height: int) -> int:
    """Expected .bin byte length for *layout* at *width* x *height*. All
    layouts are plain 4bpp (width*height/2) except the 31.5" banded layout,
    whose wire carries 25% padding."""
    if layout == LAYOUT_SPLIT_8_BANDS_VCHUNKS:
        return split_8_bands_vchunks_wire_size(width)
    return (width * height) // 2


def _pack_split_8_bands_vchunks(quantized_image: "Image.Image") -> bytes:
    """
    Pack a quantized image for the 31.5" EL315 panel (1440x2560 portrait
    native) -- see the module docstring "Split 8 bands / vertical chunks"
    for the wire format, reverse-engineered on glass 2026-08-04.

    Per-pixel reference implementation; byte-identity with the fast path is
    asserted by scripts/verify_packing.py and tests/python/unit.
    """
    width = quantized_image.width
    height = quantized_image.height
    if (width, height) != (1440, _VCHUNK_HEIGHT):
        raise ValueError(
            f"split_8_bands_vchunks expects a 1440x{_VCHUNK_HEIGHT} portrait "
            f"canvas, got {width}x{height}"
        )
    half_w = width // 2
    out = bytearray()
    base = 0
    for band_gates in _VCHUNK_BAND_GATES:
        for x0 in (0, half_w):
            for q in range(half_w // 2):
                x = x0 + 2 * q
                for p in range(_VCHUNK_CHUNK_BYTES):
                    if p < band_gates:
                        # Gate p counts up from the band bottom; image rows
                        # count down from the top.
                        y = height - 1 - (base + p)
                        high = _nibble_for_pixel(quantized_image, x, y)
                        low = _nibble_for_pixel(quantized_image, x + 1, y)
                        out.append((high << 4) | low)
                    else:
                        # Padding lines of a thin band -- discarded by the
                        # panel; white keeps them harmless.
                        out.append((_WHITE_NIBBLE << 4) | _WHITE_NIBBLE)
        base += band_gates
    return bytes(out)


def _pack_split_top_bottom(quantized_image: "Image.Image") -> bytes:
    """
    Pack a quantized image for a panel where the bottom half rows come first
    in the binary file, followed by the top half rows.
    """
    width = quantized_image.width
    height = quantized_image.height
    half = height // 2
    out = bytearray()
    for y in range(half, height):
        out.extend(_pack_row_half(quantized_image, y, 0, width))
    for y in range(0, half):
        out.extend(_pack_row_half(quantized_image, y, 0, width))
    return bytes(out)


def _pack_split_halves(quantized_image: "Image.Image") -> bytes:
    """
    Pack a quantized image for a panel built from two independent
    half-width e-ink halves (confirmed against Fraimic's own reference
    converter for the EL133UF1 / 13.3" and 31.5" panels): rows are
    visited top to bottom, columns left to right within each half. Each row
    is split at the midpoint into a left half and a right half. All
    left-half bytes for the whole image are emitted first (row by row, top
    to bottom), followed by all right-half bytes (row by row, top to
    bottom) — matching each half's own contiguous block of the buffer.
    """
    width = quantized_image.width
    height = quantized_image.height
    half = width // 2

    left_bytes = bytearray()
    right_bytes = bytearray()

    for y in range(height):
        left_bytes.extend(_pack_row_half(quantized_image, y, 0, half))
        right_bytes.extend(_pack_row_half(quantized_image, y, half, width))

    return bytes(left_bytes) + bytes(right_bytes)


def _pack_sequential(quantized_image: "Image.Image") -> bytes:
    """
    Pack a quantized image for a panel with a single contiguous buffer
    (confirmed against Waveshare's own epd7in3e.py reference driver for the
    7.3" E6 panel): plain row-major order, no half-split.
    """
    width = quantized_image.width
    height = quantized_image.height
    out = bytearray()
    for y in range(height):
        out.extend(_pack_row_half(quantized_image, y, 0, width))
    return bytes(out)


# ---------------------------------------------------------------------------
# Fast packing path (pack_method="fast")
#
# Same output bytes as the legacy per-pixel path above, produced from
# quantize()'s palette-index image directly instead of the RGB round-trip:
# bytes.translate() maps palette indices to hardware nibbles in C, and pair
# packing is vectorized (numpy when available, a slicing zip loop otherwise).
# The legacy path does ~10M Python-level operations for a 1200x1600 panel
# (a .load()[x, y] call plus a linear tuple .index() per pixel); this path
# does a handful. Byte-identity between the two is asserted by
# scripts/verify_packing.py -- run it after touching either path.
# ---------------------------------------------------------------------------

# P-mode palette index → hardware nibble. quantize() indices 0-5 are the six
# colours in SPECTRA6_REAL_WORLD_RGB order; indices 6-255 are the black
# padding entries from _build_palette_image, which the legacy RGB round-trip
# collapses to black (tuple.index returns the first match), so they map to
# black's nibble here too.
_P_INDEX_TO_NIBBLE = bytes(
    list(SPECTRA6_NIBBLE_VALUES)
    + [SPECTRA6_NIBBLE_VALUES[0]] * (256 - len(SPECTRA6_NIBBLE_VALUES))
)

# White pads the missing partner pixel of an odd-width (half-)row -- mirrors
# the hardcoded (232, 232, 232) lookup in _pack_row_half.
_WHITE_NIBBLE = SPECTRA6_NIBBLE_VALUES[SPECTRA6_REAL_WORLD_RGB.index((232, 232, 232))]


def _pack_nibble_pairs(nibbles: bytes) -> bytes:
    """Pack an even-length sequence of nibble values two-per-byte
    (high nibble = first of the pair)."""
    if _np is not None:
        arr = _np.frombuffer(nibbles, dtype=_np.uint8)
        return ((arr[0::2] << 4) | arr[1::2]).tobytes()
    return bytes(
        (nibbles[i] << 4) | nibbles[i + 1] for i in range(0, len(nibbles), 2)
    )


def _pack_segments_fast(
    nibbles: bytes,
    width: int,
    height: int,
    start_x: int,
    end_x: int,
    start_y: int = 0,
    end_y: int | None = None,
) -> bytes:
    """Fast equivalent of running _pack_row_half over every row for columns
    [start_x, end_x): rows are sliced out of the row-major nibble buffer,
    odd-width segments padded with white, then pair-packed in one pass."""
    if end_y is None:
        end_y = height
    seg_w = end_x - start_x
    if seg_w == width and seg_w % 2 == 0 and start_y == 0 and end_y == height:
        # Full-width, full-height, even: the buffer is already one contiguous even run.
        return _pack_nibble_pairs(nibbles)
    pad = bytes([_WHITE_NIBBLE]) if seg_w % 2 else b""
    rows = [
        nibbles[y * width + start_x : y * width + end_x] + pad
        for y in range(start_y, end_y)
    ]
    return _pack_nibble_pairs(b"".join(rows))


def _pack_p_image_fast(p_image: "Image.Image") -> bytes:
    """Pack a P-mode quantized image (palette indices, straight from
    quantize()) into the Spectra 6 binary format. Layout dispatch mirrors
    _pack_to_spectra6_bin."""
    width, height = p_image.size
    nibbles = p_image.tobytes().translate(_P_INDEX_TO_NIBBLE)
    layout = frame_type_for_resolution(width, height).byte_layout
    if layout == LAYOUT_SPLIT_HALF:
        half = width // 2
        return (
            _pack_segments_fast(nibbles, width, height, 0, half)
            + _pack_segments_fast(nibbles, width, height, half, width)
        )
    if layout == LAYOUT_SPLIT_TOP_BOTTOM:
        half_h = height // 2
        bot_bytes = _pack_segments_fast(
            nibbles, width, height, 0, width, start_y=half_h, end_y=height
        )
        top_bytes = _pack_segments_fast(
            nibbles, width, height, 0, width, start_y=0, end_y=half_h
        )
        return bot_bytes + top_bytes
    if layout == LAYOUT_SPLIT_8_BANDS_VCHUNKS:
        return _pack_split_8_bands_vchunks_fast(nibbles, width, height)
    return _pack_segments_fast(nibbles, width, height, 0, width)


def _pack_split_8_bands_vchunks_fast(nibbles: bytes, width: int, height: int) -> bytes:
    """Fast equivalent of _pack_split_8_bands_vchunks, from the row-major
    nibble buffer. Numpy path builds each half-block as a (chunk_bytes x
    half_w) gate-major matrix, pairs columns into bytes, and transposes to
    chunk-major order; the fallback assembles chunks via strided slices."""
    if (width, height) != (1440, _VCHUNK_HEIGHT):
        raise ValueError(
            f"split_8_bands_vchunks expects a 1440x{_VCHUNK_HEIGHT} portrait "
            f"canvas, got {width}x{height}"
        )
    half_w = width // 2
    out = bytearray()
    base = 0
    if _np is not None:
        arr = _np.frombuffer(nibbles, dtype=_np.uint8).reshape(height, width)
        for band_gates in _VCHUNK_BAND_GATES:
            for x0 in (0, half_w):
                m = _np.full(
                    (_VCHUNK_CHUNK_BYTES, half_w), _WHITE_NIBBLE, dtype=_np.uint8
                )
                # Row p of m = gate line p of this band (up from the bottom)
                # = image row height-1-(base+p): a reversed row slice.
                m[:band_gates] = arr[
                    height - base - band_gates : height - base, x0 : x0 + half_w
                ][::-1]
                out += ((m[:, 0::2] << 4) | m[:, 1::2]).T.tobytes()
            base += band_gates
        return bytes(out)
    for band_gates in _VCHUNK_BAND_GATES:
        pad = bytes([(_WHITE_NIBBLE << 4) | _WHITE_NIBBLE]) * (
            _VCHUNK_CHUNK_BYTES - band_gates
        )
        for x0 in (0, half_w):
            for q in range(half_w // 2):
                x = x0 + 2 * q
                chunk = bytearray()
                for p in range(band_gates):
                    row_off = (height - 1 - (base + p)) * width
                    chunk.append(
                        (nibbles[row_off + x] << 4) | nibbles[row_off + x + 1]
                    )
                out += chunk + pad
        base += band_gates
    return bytes(out)


def _quantize_to_spectra6_p(image: "Image.Image") -> "Image.Image":
    """Identical quantization to _quantize_to_spectra6 but returns the
    P-mode (palette-index) image the fast packer consumes, instead of
    converting back to RGB."""
    return image.quantize(
        dither=Image.Dither.FLOYDSTEINBERG,
        palette=_build_palette_image(),
    )


def _enhance_for_panel(image: "Image.Image") -> "Image.Image":
    """Fraimic bin-converter's pre-quantize enhance chain: brightness ->
    contrast -> saturation -> edge-enhance -> smooth -> sharpen, at their
    CLI's default strengths. Applied unconditionally, before either
    quantizer (fast or vivid) -- cheap (~0.1-0.15s even at 31.5"
    resolution), unlike the vivid dither this chain is not opt-in."""
    image = ImageEnhance.Brightness(image).enhance(_ENHANCE_BRIGHTNESS)
    image = ImageEnhance.Contrast(image).enhance(_ENHANCE_CONTRAST)
    image = ImageEnhance.Color(image).enhance(_ENHANCE_SATURATION)
    image = image.filter(ImageFilter.EDGE_ENHANCE)
    image = image.filter(ImageFilter.SMOOTH)
    image = image.filter(ImageFilter.SHARPEN)
    return image


_vivid_lut_cache: "Tuple[Any, int] | None" = None


def _build_vivid_lut(step: int) -> "Any":
    """Precompute the nearest SPECTRA6_VIVID_TARGET_RGB index for a coarse
    RGB grid using Fraimic's tuned RGB+luma distance metric (port of
    convert_to_bin_spectra6.closest_palette_color), so the dither loop below
    does an O(1) array lookup per pixel instead of a 6-way distance
    calculation -- the main cost cut versus a naive per-pixel port."""
    n = 256 // step
    palette = _np.array(SPECTRA6_VIVID_TARGET_RGB, dtype=_np.float32)
    luma_table = _np.array(
        [r * 250 + g * 350 + b * 400 for (r, g, b) in SPECTRA6_VIVID_TARGET_RGB],
        dtype=_np.float32,
    ) / (255.0 * 1000)

    axis = _np.arange(n, dtype=_np.float32) * step
    rr, gg, bb = _np.meshgrid(axis, axis, axis, indexing="ij")
    luma = (rr * 250 + gg * 350 + bb * 400) / (255.0 * 1000)

    best_idx = _np.zeros(rr.shape, dtype=_np.uint8)
    best_dist = None
    for i in range(len(SPECTRA6_VIVID_TARGET_RGB)):
        pr, pg, pb = palette[i]
        dr, dg, db = rr - pr, gg - pg, bb - pb
        # boost blue, reduce green a bit and red a little more (Fraimic
        # closest_palette_color tuning for e-ink/eye sensitivity).
        rgb_dist = (dr * dr * 0.250 + dg * dg * 0.350 + db * db * 0.400) * 0.75 / (
            255.0 * 255.0
        )
        luma_diff = luma - luma_table[i]
        total = 1.5 * rgb_dist + 0.60 * luma_diff * luma_diff
        if best_dist is None:
            best_dist = total
        else:
            better = total < best_dist
            best_idx = _np.where(better, i, best_idx).astype(_np.uint8)
            best_dist = _np.where(better, total, best_dist)
    return best_idx


def _vivid_lut() -> "Tuple[Any, int]":
    """Lazily build and cache the nearest-vivid-color LUT for the process
    lifetime -- built once, reused by every subsequent vivid-pipeline image."""
    global _vivid_lut_cache
    if _vivid_lut_cache is None:
        _vivid_lut_cache = (_build_vivid_lut(_VIVID_LUT_STEP), _VIVID_LUT_STEP)
    return _vivid_lut_cache


def _quantize_vivid_p(image: "Image.Image") -> "Image.Image":
    """"Vivid" pipeline: Atkinson dither against idealized primaries using
    the tuned RGB+luma metric (LUT-accelerated — see _build_vivid_lut and
    the module docstring above). Expects *image* to already have gone
    through _enhance_for_panel (both pipelines share that step -- see
    _process/_process_cropped). Returns a P-mode image whose *embedded*
    palette is still SPECTRA6_REAL_WORLD_RGB, so downstream packing/preview
    code is identical to the default pipeline; only which index gets chosen
    per pixel differs.

    Pure-Python pixel loop: Atkinson's error diffusion (each pixel's target
    depends on accumulated error from pixels already processed) is
    inherently sequential and can't be fully vectorized. Plain Python lists
    are used for the working buffer rather than numpy scalar indexing, which
    profiles significantly slower for millions of individual element
    accesses.
    """
    if image.mode != "RGB":
        image = image.convert("RGB")
    width, height = image.size

    if _np is None:  # pragma: no cover -- numpy ships with this integration
        return _quantize_to_spectra6_p(image)

    lut, step = _vivid_lut()
    n = lut.shape[0]
    working = _np.asarray(image, dtype=_np.float32).tolist()
    palette = [list(rgb) for rgb in SPECTRA6_VIVID_TARGET_RGB]
    indices = bytearray(width * height)

    for y in range(height):
        row = working[y]
        next_row = working[y + 1] if y + 1 < height else None
        row_off = y * width
        for x in range(width):
            r, g, b = row[x]
            if r < 0.0:
                r = 0.0
            elif r > 255.0:
                r = 255.0
            if g < 0.0:
                g = 0.0
            elif g > 255.0:
                g = 255.0
            if b < 0.0:
                b = 0.0
            elif b > 255.0:
                b = 255.0
            ri = int(r) // step
            gi = int(g) // step
            bi = int(b) // step
            if ri >= n:
                ri = n - 1
            if gi >= n:
                gi = n - 1
            if bi >= n:
                bi = n - 1
            idx = int(lut[ri, gi, bi])
            indices[row_off + x] = idx

            pr, pg, pb = palette[idx]
            er = r - pr
            eg = g - pg
            eb = b - pb
            if x + 1 < width:
                nx = row[x + 1]
                nx[0] += er * 0.125
                nx[1] += eg * 0.125
                nx[2] += eb * 0.125
            if next_row is not None:
                if x - 1 >= 0:
                    nl = next_row[x - 1]
                    nl[0] += er * 0.125
                    nl[1] += eg * 0.125
                    nl[2] += eb * 0.125
                nc = next_row[x]
                nc[0] += er * 0.25
                nc[1] += eg * 0.25
                nc[2] += eb * 0.25
                if x + 1 < width:
                    nr = next_row[x + 1]
                    nr[0] += er * 0.125
                    nr[1] += eg * 0.125
                    nr[2] += eb * 0.125

    out = Image.frombytes("P", (width, height), bytes(indices))
    out.putpalette(_build_palette_image().getpalette())
    return out


def _open_as_rgb(source: "str | bytes") -> "Image.Image":
    """
    Open an image from a file path or raw bytes and return it in RGB mode.

    Handles palette, grayscale, and RGBA modes transparently by compositing
    onto a white background before converting.
    """
    if isinstance(source, (bytes, bytearray, memoryview)):
        image = Image.open(io.BytesIO(source))
    else:
        image = Image.open(source)

    # Apply EXIF orientation before anything else so that auto-rotate works on
    # the visual orientation rather than the encoded orientation.
    try:
        from PIL import ImageOps
        image = ImageOps.exif_transpose(image)
    except Exception:
        pass  # Older Pillow versions or images without EXIF; proceed anyway.

    # Composite RGBA onto white so transparency becomes the background colour.
    if image.mode in ("RGBA", "LA"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        mask = image.split()[-1]  # alpha channel
        background.paste(image.convert("RGB"), mask=mask)
        return background

    return image.convert("RGB")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def convert_image(
    image_path: str,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
) -> bytes:
    """
    Convert an image file to the raw Spectra 6 binary format.

    The full conversion pipeline is:

    1. Open the image (any format Pillow supports; EXIF orientation applied).
    2. If the image and target orientations mismatch: rotate the image
       sideways (default) or, with *locked*, keep it upright and rely on the
       cover-crop in step 3.
    3. Scale-to-cover *width* × *height*, centered (overflow cropped).
    4. Apply *rotation* (canvas rotation, e.g. 90/180/270 for frames hung
       rotated / upside down).
    5. Quantize to the 6 Spectra 6 palette colours with Floyd-Steinberg
       dithering.
    6. Pack pixels into 4-bit nibbles (see module docstring).

    :param image_path: Path to the source image file.
    :param width: Composition width in pixels (the frame's effective width).
    :param height: Composition height in pixels.
    :param rotation: Canvas rotation in degrees CCW (0/90/180/270), applied
        after composition. The packed output dimensions are the post-rotation
        dimensions, which must be a registered panel resolution.
    :param locked: True when the target frame has an orientation lock --
        mismatched-orientation images are auto-cropped upright instead of
        being rotated sideways.
    :returns: Raw bytes in Spectra 6 ``.bin`` format, ready for the Fraimic
        API. The length is the layout's wire size -- ``(width * height) // 2``
        for plain 4bpp layouts; the 31.5" banded layout carries 25% padding
        (see :func:`wire_size_for_layout`).
    :raises FileNotFoundError: If *image_path* does not exist.
    :raises ImportError: If Pillow is not installed.
    """
    image = _open_as_rgb(image_path)
    bin_bytes, _quantized = _process(image, width, height, rotation, locked)
    return bin_bytes


def convert_image_with_preview(
    image_path: str,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
) -> "Tuple[bytes, bytes]":
    """
    Like :func:`convert_image`, but also returns a small PNG preview of the
    final quantized image (see :func:`_encode_preview_png`) for callers that
    need a UI thumbnail of what was sent -- currently the generic
    ``send_image`` service, which resolves an arbitrary ``media_content_id``
    rather than a Library image_id and so can't reuse the Library's
    original-image thumbnail endpoint.

    :returns: ``(bin_bytes, preview_png_bytes)``.
    """
    image = _open_as_rgb(image_path)
    bin_bytes, quantized = _process(image, width, height, rotation, locked)
    return bin_bytes, _encode_preview_png(quantized)


def convert_image_bytes(
    image_data: bytes,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
    pack_method: str = "fast",
    color_pipeline: str = COLOR_PIPELINE_FAST,
) -> bytes:
    """
    Convert raw image bytes to the raw Spectra 6 binary format.

    Accepts any image format that Pillow can decode (JPEG, PNG, WebP, GIF,
    BMP, TIFF, …). See :func:`convert_image` for parameter details and
    :func:`_process` for *pack_method* / *color_pipeline*.
    """
    image = _open_as_rgb(image_data)
    bin_bytes, _quantized = _process(
        image, width, height, rotation, locked, pack_method, color_pipeline
    )
    return bin_bytes


def convert_image_bytes_with_preview(
    image_data: bytes,
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
    color_pipeline: str = COLOR_PIPELINE_FAST,
) -> "Tuple[bytes, bytes]":
    """
    Like :func:`convert_image_bytes`, but also returns a small PNG preview of
    the final quantized image. See :func:`convert_image_with_preview` for why
    this exists -- used here by the raw-upload HTTP view
    (DigitalFramesSendImageView), which also has no Library image_id to hand.

    :returns: ``(bin_bytes, preview_png_bytes)``.
    """
    image = _open_as_rgb(image_data)
    bin_bytes, quantized = _process(
        image, width, height, rotation, locked, color_pipeline=color_pipeline
    )
    return bin_bytes, _encode_preview_png(quantized)


def _encode_preview_png(image: "Image.Image") -> bytes:
    """
    Encode *image* (already quantized to the Spectra 6 palette) as a small PNG,
    downscaled to icon size. Used to give callers that don't have a Library
    image_id (e.g. the generic send_image service / media browser sends) a
    UI-viewable thumbnail of what actually went to the frame, without needing
    the original source file to still be reachable later.
    """
    preview = image.copy()
    preview.thumbnail((240, 240), Image.LANCZOS)
    buf = io.BytesIO()
    preview.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def make_thumbnail(raw_bytes: bytes, edge: int, quality: int = 82) -> bytes:
    """
    Downscale an original image to at most *edge* px on its longest side and
    encode it as JPEG. Serves the panel's grid/picker tiles (see
    DigitalFramesLibraryImageView's ?thumb= handling) so they never have to download
    and decode multi-MB originals client-side.
    """
    image = _open_as_rgb(raw_bytes)
    image.thumbnail((edge, edge), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _process(
    image: "Image.Image",
    width: int,
    height: int,
    rotation: int = 0,
    locked: bool = False,
    pack_method: str = "fast",
    color_pipeline: str = COLOR_PIPELINE_FAST,
) -> "Tuple[bytes, Image.Image]":
    """Shared implementation used by both public entry points. Returns the
    packed bytes alongside the final quantized image so preview-generating
    callers can reuse it without re-running the pipeline.

    pack_method="fast" (the default) packs through the vectorized path;
    "legacy" is the historical per-pixel path, kept temporarily as an
    escape hatch (reachable via the panel's ?packer=legacy override). The
    two produce identical bytes -- proven by scripts/verify_packing.py and
    confirmed pixel-identical on real frames (2026-07) -- so legacy plus
    the A/B switches can be removed in a future release.

    color_pipeline selects the quantizer/dither: COLOR_PIPELINE_FAST
    (this function's own default when the arg is omitted --
    Floyd-Steinberg against measured real-world panel colors) or
    COLOR_PIPELINE_VIVID (idealized-primary Atkinson dither -- see the
    module docstring above _quantize_vivid_p, meaningfully slower; callers
    resolving a configured frame's choice use const.DEFAULT_COLOR_PIPELINE,
    which is "vivid" as of 2026-08-12, not this parameter's own default).
    Both pipelines share the same pre-quantize enhance chain
    (_enhance_for_panel) -- it's cheap enough to always run."""
    if not locked:
        # The Fraimic way: a mismatched image lies sideways at full size.
        image = _auto_rotate(image, width, height)
    # Locked: no source rotation -- the centered cover-crop below trims a
    # mismatched image to the target shape while keeping it upright.
    image = _resize_cover_centered(image, width, height)
    if rotation:
        image = image.rotate(rotation, expand=True)
    image = _enhance_for_panel(image)
    if color_pipeline == COLOR_PIPELINE_VIVID:
        p_image = _quantize_vivid_p(image)
        return _pack_p_image_fast(p_image), p_image.convert("RGB")
    if pack_method == "fast":
        p_image = _quantize_to_spectra6_p(image)
        return _pack_p_image_fast(p_image), p_image.convert("RGB")
    image = _quantize_to_spectra6(image)
    return _pack_to_spectra6_bin(image), image


# ---------------------------------------------------------------------------
# Unpacking (bin → preview) -- the reverse of the packers above, used to give
# send paths that only ever see packed bytes (the xOTD/skill text renderer,
# whose pinned subprocess emits xotd.bin directly) a UI preview of what went
# to the frame. Without this, a text-skill send has neither a library
# image_id nor a thumbnail, and the frame's "last image" state goes blank.
# ---------------------------------------------------------------------------

# hardware nibble value → palette index (SPECTRA6_NIBBLE_VALUES inverted).
# Unknown nibbles (4, 7-15) map to white so a corrupt byte degrades visibly
# but harmlessly instead of raising.
_NIBBLE_TO_INDEX = bytes(
    SPECTRA6_NIBBLE_VALUES.index(n) if n in SPECTRA6_NIBBLE_VALUES else 1
    for n in range(16)
)
# byte → palette index of its high/low nibble, for bytes.translate (C speed).
_HI_NIBBLE_INDEX = bytes(_NIBBLE_TO_INDEX[b >> 4] for b in range(256))
_LO_NIBBLE_INDEX = bytes(_NIBBLE_TO_INDEX[b & 0xF] for b in range(256))


def _unpack_nibble_pairs(packed: bytes) -> bytes:
    """Expand nibble-packed bytes into one palette-index byte per pixel."""
    out = bytearray(len(packed) * 2)
    out[0::2] = packed.translate(_HI_NIBBLE_INDEX)
    out[1::2] = packed.translate(_LO_NIBBLE_INDEX)
    return bytes(out)


def unpack_spectra6_bin(bin_bytes: bytes, width: int, height: int) -> "Image.Image":
    """
    Decode a packed Spectra 6 ``.bin`` back into an RGB image -- the inverse
    of :func:`_pack_to_spectra6_bin` for a *width* × *height* panel. The byte
    layout is looked up like the packers do; an unregistered resolution
    falls back to split-half, matching the renderer fallback in
    skills.SkillManager._async_render_text.

    :raises ValueError: If *bin_bytes* isn't exactly the layout's wire size
        (``width*height//2`` for plain 4bpp layouts; the 31.5" banded layout
        carries 25% padding -- see :func:`wire_size_for_layout`).
    """
    try:
        layout = frame_type_for_resolution(width, height).byte_layout
    except ValueError:
        layout = LAYOUT_SPLIT_HALF

    expected = wire_size_for_layout(layout, width, height)
    if len(bin_bytes) != expected:
        raise ValueError(
            f"bin is {len(bin_bytes)} bytes, expected {expected} for {width}x{height}"
        )

    indices = _unpack_nibble_pairs(bin_bytes)

    if layout == LAYOUT_SPLIT_HALF:
        # left-half rows first, then right-half rows -- re-interleave.
        half = width // 2
        left = indices[: half * height]
        right = indices[half * height :]
        rows = bytearray(width * height)
        for y in range(height):
            rows[y * width : y * width + half] = left[y * half : (y + 1) * half]
            rows[y * width + half : (y + 1) * width] = right[y * half : (y + 1) * half]
        indices = bytes(rows)
    elif layout == LAYOUT_SPLIT_8_BANDS_VCHUNKS:
        # Inverse of _pack_split_8_bands_vchunks: walk blocks bottom-up and
        # reassemble each display row from strided chunk slices. `indices`
        # here is one palette-index byte per WIRE nibble, i.e. per half it is
        # chunk-major: chunk q's pixels sit at [q*2*CB + 2p, q*2*CB + 2p + 1].
        half = width // 2
        cb = _VCHUNK_CHUNK_BYTES
        half_px = half // 2 * cb * 2  # pixels per half-block on the wire
        rows = bytearray(width * height)
        base = 0
        block_px = 2 * half_px
        for b, band_gates in enumerate(_VCHUNK_BAND_GATES):
            for h_i, x0 in enumerate((0, half)):
                off = b * block_px + h_i * half_px
                for p in range(band_gates):
                    y = height - 1 - (base + p)
                    # Pixel pair of chunk q at gate p: wire pixel offsets
                    # off+q*2*cb+2p and +1 -> strided slices across chunks.
                    rows[y * width + x0 : y * width + x0 + half : 2] = indices[
                        off + 2 * p : off + half_px : 2 * cb
                    ]
                    rows[y * width + x0 + 1 : y * width + x0 + half : 2] = indices[
                        off + 2 * p + 1 : off + half_px : 2 * cb
                    ]
            base += band_gates
        indices = bytes(rows)

    image = Image.frombytes("P", (width, height), indices)
    image.putpalette(_build_palette_image().getpalette())
    return image.convert("RGB")


def preview_png_from_bin(bin_bytes: bytes, width: int, height: int) -> bytes:
    """Small PNG preview of a packed ``.bin`` (see :func:`unpack_spectra6_bin`
    and :func:`_encode_preview_png`)."""
    return _encode_preview_png(unpack_spectra6_bin(bin_bytes, width, height))


def convert_image_cropped(
    image_path: str,
    width: int,
    height: int,
    crop_box: "Tuple[float, float, float, float]",
    rotation: int = 0,
) -> bytes:
    """
    Convert an image file to Spectra 6 binary using a manually-chosen crop
    rectangle instead of the automatic letterbox path.

    :param image_path: Path to the source image file.
    :param width: Target display width in pixels.
    :param height: Target display height in pixels.
    :param crop_box: (x0, y0, x1, y1), normalized 0.0-1.0 against the
        source image's full dimensions (post EXIF-orientation). The caller
        (the crop editor UI) is responsible for keeping this box's aspect
        ratio matched to width:height.
    :param rotation: Optional extra rotation in degrees (e.g. 180).
    :returns: Raw bytes in Spectra 6 ``.bin`` format.
    """
    image = _open_as_rgb(image_path)
    bin_bytes, _quantized = _process_cropped(image, width, height, crop_box, rotation)
    return bin_bytes


def convert_image_bytes_cropped(
    image_data: bytes,
    width: int,
    height: int,
    crop_box: "Tuple[float, float, float, float]",
    rotation: int = 0,
    pack_method: str = "fast",
    color_pipeline: str = COLOR_PIPELINE_FAST,
    dest_box: "Tuple[float, float, float, float] | None" = None,
) -> bytes:
    """
    Convert raw image bytes to Spectra 6 binary using a manually-chosen crop
    rectangle instead of the automatic letterbox path. See
    :func:`convert_image_cropped` for parameter details and :func:`_process`
    for *pack_method* / *color_pipeline*. *dest_box* -- see
    :func:`_process_cropped`.
    """
    image = _open_as_rgb(image_data)
    bin_bytes, _quantized = _process_cropped(
        image, width, height, crop_box, rotation, pack_method, color_pipeline, dest_box
    )
    return bin_bytes


def convert_image_bytes_cropped_with_preview(
    image_data: bytes,
    width: int,
    height: int,
    crop_box: "Tuple[float, float, float, float]",
    rotation: int = 0,
    pack_method: str = "fast",
    color_pipeline: str = COLOR_PIPELINE_FAST,
    dest_box: "Tuple[float, float, float, float] | None" = None,
) -> "Tuple[bytes, bytes]":
    """
    Like :func:`convert_image_bytes_cropped`, but also returns a small PNG
    preview of the final quantized image -- see
    :func:`convert_image_bytes_with_preview` for why this exists (callers
    with no Library image_id to hand, e.g. a wall-banner message crop, still
    need a UI-viewable thumbnail of what actually went to the frame).

    :returns: ``(bin_bytes, preview_png_bytes)``.
    """
    image = _open_as_rgb(image_data)
    bin_bytes, quantized = _process_cropped(
        image, width, height, crop_box, rotation, pack_method, color_pipeline, dest_box
    )
    return bin_bytes, _encode_preview_png(quantized)


def _dest_pixel_box(
    dest_box: "Tuple[float, float, float, float] | None",
    width: int,
    height: int,
) -> "Tuple[int, int, int, int] | None":
    """Pixel rect within a *width*x*height* canvas that cropped content
    should be placed at, or None when *dest_box* is absent/covers the whole
    canvas -- the signal callers use to skip windowed placement entirely and
    keep the plain crop-and-fill-the-canvas behavior. Guaranteed non-empty
    and within bounds, like :func:`_crop_to_box`."""
    if dest_box is None:
        return None
    dx0, dy0, dx1, dy1 = (float(v) for v in dest_box)
    dx0, dx1 = sorted((min(max(dx0, 0.0), 1.0), min(max(dx1, 0.0), 1.0)))
    dy0, dy1 = sorted((min(max(dy0, 0.0), 1.0), min(max(dy1, 0.0), 1.0)))
    if dx0 <= 1e-9 and dy0 <= 1e-9 and dx1 >= 1.0 - 1e-9 and dy1 >= 1.0 - 1e-9:
        return None  # full coverage -- nothing to window

    left = int(round(dx0 * width))
    top = int(round(dy0 * height))
    right = int(round(dx1 * width))
    bottom = int(round(dy1 * height))
    right = max(right, left + 1)
    bottom = max(bottom, top + 1)
    right = min(right, width)
    bottom = min(bottom, height)
    left = min(left, right - 1)
    top = min(top, bottom - 1)
    return (left, top, right, bottom)


def _paste_windowed(
    cropped: "Image.Image",
    dest_px: "Tuple[int, int, int, int]",
    width: int,
    height: int,
    fill: "Tuple[int, int, int]" = (0, 0, 0),
) -> "Image.Image":
    """Resize *cropped* to exactly fill *dest_px* and paste it into an
    otherwise *fill*-colored *width*x*height* canvas. Used when a frame only
    partially overlaps a wallpaper's image rect (KPF 36): the part of the
    frame with no image behind it renders as *fill* instead of stretching
    the partial slice to cover the whole frame."""
    dx0, dy0, dx1, dy1 = dest_px
    resized = cropped.resize((dx1 - dx0, dy1 - dy0), Image.LANCZOS)
    canvas = Image.new("RGB", (width, height), fill)
    canvas.paste(resized, (dx0, dy0))
    return canvas


def _process_cropped(
    image: "Image.Image",
    width: int,
    height: int,
    crop_box: "Tuple[float, float, float, float]",
    rotation: int = 0,
    pack_method: str = "fast",
    color_pipeline: str = COLOR_PIPELINE_FAST,
    dest_box: "Tuple[float, float, float, float] | None" = None,
) -> "Tuple[bytes, Image.Image]":
    """*dest_box*, when given, places the crop within only that fraction of
    the (width, height) canvas and fills the rest black, instead of
    stretching the crop to cover the whole canvas -- see
    wall_geometry.compute_wallpaper_crop_boxes for where this comes from and
    why (a frame that only partly overlaps a wallpaper's image rect)."""
    dest_px = _dest_pixel_box(dest_box, width, height)

    if dest_px is not None:
        # Windowed placement: an exact pixel crop, no aspect-ratio
        # refitting -- the caller (wallpaper mode) has already decided
        # exactly what's behind this frame and where it goes; refitting the
        # crop's aspect ratio here (like the branch below does) would throw
        # that placement away.
        image = _crop_to_box(image, crop_box)
        image = _paste_windowed(image, dest_px, width, height)
    else:
        img_w, img_h = image.width, image.height
        x0, y0, x1, y1 = crop_box
        w = x1 - x0
        h = y1 - y0
        if w > 0 and h > 0:
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            # Target aspect ratio in normalized coordinates:
            # nw / nh = (width * img_h) / (height * img_w)
            target_ar_norm = (width * img_h) / (height * img_w)

            if w / h > target_ar_norm:
                # Crop box is too wide, trim the width
                nh = h
                nw = h * target_ar_norm
            else:
                # Crop box is too tall, trim the height
                nw = w
                nh = w / target_ar_norm

            x0 = max(0.0, min(cx - nw / 2.0, 1.0))
            x1 = max(0.0, min(cx + nw / 2.0, 1.0))
            y0 = max(0.0, min(cy - nh / 2.0, 1.0))
            y1 = max(0.0, min(cy + nh / 2.0, 1.0))
            crop_box = (x0, y0, x1, y1)

        image = _crop_to_box(image, crop_box)
        image = image.resize((width, height), Image.LANCZOS)

    if rotation:
        image = image.rotate(rotation, expand=True)
    image = _enhance_for_panel(image)
    if color_pipeline == COLOR_PIPELINE_VIVID:
        p_image = _quantize_vivid_p(image)
        return _pack_p_image_fast(p_image), p_image.convert("RGB")
    if pack_method == "fast":
        p_image = _quantize_to_spectra6_p(image)
        return _pack_p_image_fast(p_image), p_image.convert("RGB")
    image = _quantize_to_spectra6(image)
    return _pack_to_spectra6_bin(image), image
