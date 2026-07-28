"""Spectra 6 six-box color test pattern (hardware palette check)."""

from __future__ import annotations

from io import BytesIO

from PIL import Image

from custom_components.digital_frames.image_converter import SPECTRA6_REAL_WORLD_RGB
from custom_components.digital_frames.test_patterns import (
    COLOR_TEST_LABELS,
    COLOR_TEST_TAG,
    build_spectra6_color_test_png,
    color_test_asset_path,
)


def test_packaged_asset_exists():
    path = color_test_asset_path()
    assert path.is_file()
    assert path.stat().st_size > 1000


def test_build_six_boxes_exact_palette_centers():
    png = build_spectra6_color_test_png(900, 600)
    img = Image.open(BytesIO(png)).convert("RGB")
    assert img.size == (900, 600)
    cols, rows = 3, 2
    bw, bh = 900 // cols, 600 // rows
    px = img.load()
    for i, rgb in enumerate(SPECTRA6_REAL_WORLD_RGB):
        row, col = divmod(i, cols)
        cx = col * bw + bw // 2
        cy = row * bh + bh // 2
        # Allow a few pixels off pure fill if a border overlaps (should not
        # at true center).
        assert px[cx, cy] == rgb, (COLOR_TEST_LABELS[i], px[cx, cy], rgb)


def test_quantize_maps_each_box_to_single_palette_entry():
    """After Spectra quantize, centers stay on the intended palette entry."""
    from custom_components.digital_frames import image_converter as ic

    png = build_spectra6_color_test_png(600, 400)
    img = Image.open(BytesIO(png)).convert("RGB")
    q = ic._quantize_to_spectra6_p(img).convert("RGB")
    cols = 3
    bw, bh = 600 // cols, 400 // 2
    px = q.load()
    for i, rgb in enumerate(SPECTRA6_REAL_WORLD_RGB):
        row, col = divmod(i, cols)
        cx = col * bw + bw // 2
        cy = row * bh + bh // 2
        assert px[cx, cy] == rgb


def test_tag_constant_stable_for_seed_idempotency():
    assert COLOR_TEST_TAG == "spectra6_color_test"
