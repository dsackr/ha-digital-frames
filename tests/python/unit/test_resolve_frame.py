"""resolve_frame_by_entity: Meural IP sensors + Fraimic battery (KPF 32/5)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.fraimic.const import DOMAIN
from custom_components.fraimic.http_api import resolve_frame_by_entity


def test_resolve_prefers_entity_config_entry_id():
    """Meural path: entity has config_entry_id even if device links are empty."""
    hass = MagicMock()
    coord = MagicMock()
    coord.async_send_image_or_queue = MagicMock()
    coord.host = "192.168.1.32"
    entry = SimpleNamespace(entry_id="meural_entry", title="Kitchen Meural")
    hass.data = {DOMAIN: {"meural_entry": coord, "_library": object()}}
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)

    entity_entry = SimpleNamespace(
        config_entry_id="meural_entry",
        device_id=None,
    )
    ent_reg = MagicMock()
    ent_reg.async_get = MagicMock(return_value=entity_entry)

    with patch(
        "custom_components.fraimic.http_api.er.async_get", return_value=ent_reg
    ):
        got_coord, got_entry = resolve_frame_by_entity(hass, "sensor.kitchen_meural_ip")

    assert got_coord is coord
    assert got_entry is entry


def test_resolve_skips_non_coordinator_domain_keys():
    """Device config_entries must not match domain helper keys."""
    hass = MagicMock()
    coord = MagicMock()
    coord.async_send_image_or_queue = MagicMock()
    coord.host = "192.168.1.1"
    entry = SimpleNamespace(entry_id="frame_entry")
    hass.data = {DOMAIN: {"frame_entry": coord, "_library": object()}}
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)

    entity_entry = SimpleNamespace(
        config_entry_id=None,
        device_id="dev1",
    )
    ent_reg = MagicMock()
    ent_reg.async_get = MagicMock(return_value=entity_entry)
    device_entry = SimpleNamespace(config_entries=["_library", "frame_entry"])
    dev_reg = MagicMock()
    dev_reg.async_get = MagicMock(return_value=device_entry)

    with (
        patch("custom_components.fraimic.http_api.er.async_get", return_value=ent_reg),
        patch("custom_components.fraimic.http_api.dr.async_get", return_value=dev_reg),
    ):
        got_coord, got_entry = resolve_frame_by_entity(hass, "sensor.frame_battery")

    assert got_coord is coord
    assert got_entry is entry


def test_resolve_missing_entity_raises():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    ent_reg = MagicMock()
    ent_reg.async_get = MagicMock(return_value=None)
    with patch(
        "custom_components.fraimic.http_api.er.async_get", return_value=ent_reg
    ):
        with pytest.raises(ValueError, match="not found"):
            resolve_frame_by_entity(hass, "sensor.missing")


def test_resolve_no_coordinator_raises_clear_message():
    hass = MagicMock()
    hass.data = {DOMAIN: {"_library": object()}}
    entity_entry = SimpleNamespace(config_entry_id="gone", device_id=None)
    ent_reg = MagicMock()
    ent_reg.async_get = MagicMock(return_value=entity_entry)
    hass.config_entries.async_get_entry = MagicMock(return_value=None)
    with patch(
        "custom_components.fraimic.http_api.er.async_get", return_value=ent_reg
    ):
        with pytest.raises(ValueError, match="No frame coordinator"):
            resolve_frame_by_entity(hass, "sensor.meural_ip")
