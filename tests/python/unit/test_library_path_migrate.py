"""Local library path rename (fraimic_library → digital_frames_library)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from custom_components.digital_frames.const import (
    LEGACY_LIBRARY_DIRNAME,
    LIBRARY_DIRNAME,
)
from custom_components.digital_frames.library import _migrate_local_dirname


def _hass_with_config(tmp_path: Path):
    return SimpleNamespace(config=SimpleNamespace(path=lambda *parts: str(tmp_path.joinpath(*parts))))


def test_migrate_renames_legacy_library_dir(tmp_path: Path):
    hass = _hass_with_config(tmp_path)
    legacy = tmp_path / LEGACY_LIBRARY_DIRNAME
    legacy.mkdir()
    (legacy / "manifest.json").write_text(
        json.dumps({"images": [{"image_id": "a", "albums": ["Family"]}]}),
        encoding="utf-8",
    )

    result = _migrate_local_dirname(
        hass, new=LIBRARY_DIRNAME, legacy=LEGACY_LIBRARY_DIRNAME
    )

    new_path = tmp_path / LIBRARY_DIRNAME
    assert result == str(new_path)
    assert new_path.is_dir()
    assert not legacy.exists()
    data = json.loads((new_path / "manifest.json").read_text(encoding="utf-8"))
    assert data["images"][0]["albums"] == ["Family"]


def test_migrate_prefers_existing_new_dir(tmp_path: Path):
    hass = _hass_with_config(tmp_path)
    new = tmp_path / LIBRARY_DIRNAME
    legacy = tmp_path / LEGACY_LIBRARY_DIRNAME
    new.mkdir()
    legacy.mkdir()
    (new / "marker").write_text("new", encoding="utf-8")
    (legacy / "marker").write_text("old", encoding="utf-8")

    result = _migrate_local_dirname(
        hass, new=LIBRARY_DIRNAME, legacy=LEGACY_LIBRARY_DIRNAME
    )

    assert result == str(new)
    assert (new / "marker").read_text(encoding="utf-8") == "new"
    assert legacy.exists()  # left alone when new already present


def test_migrate_creates_nothing_when_neither_exists(tmp_path: Path):
    hass = _hass_with_config(tmp_path)
    result = _migrate_local_dirname(
        hass, new=LIBRARY_DIRNAME, legacy=LEGACY_LIBRARY_DIRNAME
    )
    assert result == str(tmp_path / LIBRARY_DIRNAME)
    assert not os.path.isdir(result)
