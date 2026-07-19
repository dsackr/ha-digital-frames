"""Product branding as Digital Frames (KPF 34)."""

from __future__ import annotations

import json
from pathlib import Path

from custom_components.fraimic.const import DOMAIN, PRODUCT_NAME

ROOT = Path(__file__).resolve().parents[3]


def test_product_name_constant():
    assert PRODUCT_NAME == "Digital Frames"
    # Domain stays technical until an explicit migration.
    assert DOMAIN == "fraimic"


def test_manifest_display_name():
    data = json.loads((ROOT / "custom_components/fraimic/manifest.json").read_text())
    assert data["name"] == "Digital Frames"
    assert data["domain"] == "fraimic"


def test_hacs_display_name():
    data = json.loads((ROOT / "hacs.json").read_text())
    assert data["name"] == "Digital Frames"
