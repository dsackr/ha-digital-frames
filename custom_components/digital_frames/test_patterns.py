"""Built-in Spectra 6 diagnostic patterns for the image library.

Seeds a six-box color test (black / white / yellow / red / blue / green)
using the same real-world RGB targets as image_converter so quantization
is exact on Spectra E6 panels.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .image_converter import SPECTRA6_REAL_WORLD_RGB

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .library import LibraryManager

_LOGGER = logging.getLogger(__name__)

# Stable identity so we re-seed at most once per library (not every restart).
COLOR_TEST_TAG = "spectra6_color_test"
COLOR_TEST_VOICE_NAME = "color test"
COLOR_TEST_ALBUM = "Test Patterns"
COLOR_TEST_FILENAME = "spectra6_color_test.png"

# Order matches SPECTRA6_REAL_WORLD_RGB / SPECTRA6_NIBBLE_VALUES.
COLOR_TEST_LABELS = ("Black", "White", "Yellow", "Red", "Blue", "Green")

_ASSETS_DIR = Path(__file__).with_name("assets")


def color_test_asset_path() -> Path:
    return _ASSETS_DIR / COLOR_TEST_FILENAME


def build_spectra6_color_test_png(
    width: int = 1800, height: int = 1200
) -> bytes:
    """Build a 3×2 grid of the six Spectra E6 palette colours as PNG bytes.

    Pixel fills use :data:`SPECTRA6_REAL_WORLD_RGB` exactly so the image
    converter maps each box to a single nibble with no dithering surprise.
    """
    from io import BytesIO

    from PIL import Image, ImageDraw, ImageFont

    if width < 60 or height < 40:
        raise ValueError("color test image too small")

    cols, rows = 3, 2
    img = Image.new("RGB", (width, height), SPECTRA6_REAL_WORLD_RGB[0])
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(
            "/System/Library/Fonts/Helvetica.ttc", max(24, width // 28)
        )
    except OSError:
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                max(24, width // 28),
            )
        except OSError:
            font = ImageFont.load_default()

    bw, bh = width // cols, height // rows
    for i, (rgb, name) in enumerate(
        zip(SPECTRA6_REAL_WORLD_RGB, COLOR_TEST_LABELS, strict=True)
    ):
        row, col = divmod(i, cols)
        x0, y0 = col * bw, row * bh
        x1, y1 = x0 + bw - 1, y0 + bh - 1
        draw.rectangle([x0, y0, x1, y1], fill=rgb)
        draw.rectangle([x0, y0, x1, y1], outline=(0, 0, 0), width=max(2, width // 400))
        lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        ink = (255, 255, 255) if lum < 140 else (0, 0, 0)
        label = f"{name}\n{rgb[0]}, {rgb[1]}, {rgb[2]}"
        bbox = draw.multiline_textbbox((0, 0), label, font=font, align="center")
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = x0 + (bw - tw) // 2
        ty = y0 + (bh - th) // 2
        draw.multiline_text((tx, ty), label, fill=ink, font=font, align="center")

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _load_or_build_color_test_png() -> bytes:
    path = color_test_asset_path()
    if path.is_file():
        return path.read_bytes()
    return build_spectra6_color_test_png()


async def async_seed_spectra6_color_test(
    hass: "HomeAssistant", library: "LibraryManager"
) -> dict[str, Any] | None:
    """Ensure the Spectra 6 color test image is in the library once.

    Idempotent: if an image already carries the ``spectra6_color_test`` tag
    (or the dedicated voice name), returns that record without re-uploading.
    """
    try:
        images = await library._backend.async_list_images()
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not list library to seed color test: %s", err)
        return None

    for img in images:
        tags = getattr(img, "tags", None) or []
        is_seed = (
            COLOR_TEST_TAG in tags
            or getattr(img, "voice_name", None) in (
                COLOR_TEST_VOICE_NAME,
                "Spectra 6 Color Test",  # legacy voice name
            )
            or getattr(img, "filename", None) == COLOR_TEST_FILENAME
        )
        if not is_seed:
            continue
        # Keep voice name in sync if we renamed it after an earlier seed.
        if (
            getattr(img, "voice_name", None) != COLOR_TEST_VOICE_NAME
            and getattr(img, "image_id", None)
        ):
            try:
                await library.async_set_image_voice_name(
                    img.image_id, COLOR_TEST_VOICE_NAME
                )
                img.voice_name = COLOR_TEST_VOICE_NAME
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Could not rename color test voice name: %s", err)
        return img.to_dict() if hasattr(img, "to_dict") else None

    try:
        png_bytes = await hass.async_add_executor_job(_load_or_build_color_test_png)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not build Spectra 6 color test image: %s", err)
        return None

    try:
        record = await library.async_upload(
            COLOR_TEST_FILENAME,
            png_bytes,
            albums=[COLOR_TEST_ALBUM],
        )
        image_id = record.get("image_id")
        if image_id:
            await library.async_set_image_voice_name(image_id, COLOR_TEST_VOICE_NAME)
            await library.async_set_image_tags(image_id, [COLOR_TEST_TAG, "test"])
        _LOGGER.info(
            "Seeded Spectra 6 color test image into library album '%s'",
            COLOR_TEST_ALBUM,
        )
        return record
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not seed Spectra 6 color test image: %s", err)
        return None
