"""Options flow: sleep/always-on, scan interval, size, orientation (KPF 2 / 4b).

If this silently breaks: battery-frame sleep settings don't stick, always-on
missing from UI schema, or orientation lock resets when saving unrelated fields.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType

from custom_components.digital_frames.const import (
    CONF_COLOR_PIPELINE,
    CONF_DRIVER,
    CONF_FAST_POLL_WHEN_QUEUED,
    CONF_FRAME_ALWAYS_ON,
    CONF_FRAME_SLEEP_MINUTES,
    CONF_ORIENTATION,
    CONF_ROTATE_LANDSCAPE_180,
    CONF_ROTATION_EDGE,
    CONF_SIZE,
    DRIVER_SAMSUNG,
    EDGE_RIGHT,
    ORIENTATION_PORTRAIT,
)


async def test_default_form_reflects_current_options(hass, make_frame_entry):
    entry = make_frame_entry(
        size="13.3",
        options={
            "scan_interval": 120,
            CONF_FRAME_SLEEP_MINUTES: 45,
            CONF_FRAME_ALWAYS_ON: True,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
    schema = result["data_schema"].schema
    defaults = {
        str(k): k.default() for k in schema if getattr(k, "default", None) is not None
    }
    assert defaults["scan_interval"] == 120
    assert defaults[CONF_FRAME_SLEEP_MINUTES] == 45
    assert defaults[CONF_FRAME_ALWAYS_ON] is True
    assert defaults[CONF_FAST_POLL_WHEN_QUEUED] is False
    # Schema must expose both power controls for the UI / panel.
    field_names = {str(k) for k in schema}
    assert CONF_FRAME_SLEEP_MINUTES in field_names
    assert CONF_FRAME_ALWAYS_ON in field_names
    assert CONF_FAST_POLL_WHEN_QUEUED in field_names
    # Frame Type is fixed at add time — not re-offered when size is already set.
    assert "resolution" not in field_names


async def test_official_fraimic_sizes_default_landscape_flip_on(hass, make_frame_entry):
    """13.3"/31.5" are portrait-native; unlocked landscape images land
    upside down unless flipped, so the option defaults on without the user
    ever having saved it (options dict starts empty at add time)."""
    entry = make_frame_entry(size="13.3")
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    defaults = {
        str(k): k.default() for k in schema if getattr(k, "default", None) is not None
    }
    assert defaults[CONF_ROTATE_LANDSCAPE_180] is True


async def test_clone_size_does_not_default_landscape_flip_on(hass, make_frame_entry):
    entry = make_frame_entry(size="13.3_clone")
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    defaults = {
        str(k): k.default() for k in schema if getattr(k, "default", None) is not None
    }
    assert defaults[CONF_ROTATE_LANDSCAPE_180] is False


async def test_color_pipeline_field_defaults_to_fast_for_spectra_frame(
    hass, make_frame_entry
):
    """CONF_COLOR_PIPELINE (KPF 7's opt-in Fraimic-style Atkinson pipeline)
    must be offered for a plain Spectra frame and default to "fast" when
    never saved -- omitting the option must never silently opt a frame into
    the slower pipeline."""
    entry = make_frame_entry(size="13.3")
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    field_names = {str(k) for k in schema}
    assert CONF_COLOR_PIPELINE in field_names
    defaults = {
        str(k): k.default() for k in schema if getattr(k, "default", None) is not None
    }
    assert defaults[CONF_COLOR_PIPELINE] == "fast"


async def test_color_pipeline_field_reflects_saved_vivid_choice(hass, make_frame_entry):
    entry = make_frame_entry(size="31.5", options={CONF_COLOR_PIPELINE: "vivid"})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    defaults = {
        str(k): k.default() for k in schema if getattr(k, "default", None) is not None
    }
    assert defaults[CONF_COLOR_PIPELINE] == "vivid"


async def test_color_pipeline_field_hidden_for_samsung(hass):
    """Samsung (PNG codec) never dithers -- the field would be meaningless
    and misleading there, so it must not appear on that driver's form."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.digital_frames.const import DOMAIN, SAMSUNG_SIZE_LABEL

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DRIVER: DRIVER_SAMSUNG,
            "host": "192.168.1.60",
            "name": "Samsung Display",
            "width": 2560,
            "height": 1440,
            "size": SAMSUNG_SIZE_LABEL,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    field_names = {str(k) for k in schema}
    assert CONF_COLOR_PIPELINE not in field_names


async def test_official_form_defaults_use_detected_keep_awake(
    hass, make_frame_entry
):
    """Official panels: form defaults show scraped actuals, not stale options."""
    from types import SimpleNamespace

    from custom_components.digital_frames.const import DOMAIN

    entry = make_frame_entry(
        size="13.3",  # official profile
        mac="3cdc75737330",  # official OUI
        options={
            CONF_FRAME_SLEEP_MINUTES: 15,
            CONF_FRAME_ALWAYS_ON: False,  # option says off…
        },
    )
    entry.add_to_hass(hass)
    # …but the device reports always-on + 25m (as scraped from /info).
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = SimpleNamespace(
        data={"keep_awake_actual": True, "sleep_minutes_actual": 25}
    )

    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    defaults = {
        str(k): k.default() for k in schema if getattr(k, "default", None) is not None
    }
    assert defaults[CONF_FRAME_ALWAYS_ON] is True
    assert defaults[CONF_FRAME_SLEEP_MINUTES] == 25


async def test_size_unset_leaves_unset_option_available(hass, make_frame_entry):
    entry = make_frame_entry(size="")
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    # Legacy entries without a type still get a Frame Type (resolution) field.
    resolution_key = next(k for k in schema if str(k) == "resolution")
    assert "" in schema[resolution_key].container


async def test_save_backfills_size_into_entry_data(hass, make_frame_entry):
    entry = make_frame_entry(size="")
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "scan_interval": 300,
            CONF_FAST_POLL_WHEN_QUEUED: False,
            CONF_FRAME_SLEEP_MINUTES: 15,
            CONF_FRAME_ALWAYS_ON: False,
            "resolution": "13.3",
            CONF_ROTATION_EDGE: "left",
            "rotate_portrait_180": False,
            "rotate_landscape_180": False,
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_SIZE] == "13.3"
    assert result["data"][CONF_FRAME_SLEEP_MINUTES] == 15
    assert result["data"][CONF_FRAME_ALWAYS_ON] is False
    assert result["data"][CONF_FAST_POLL_WHEN_QUEUED] is False


async def test_orientation_lock_carried_through_unrelated_save(hass, make_frame_entry):
    entry = make_frame_entry(options={CONF_ORIENTATION: ORIENTATION_PORTRAIT})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "scan_interval": 600,
            CONF_FAST_POLL_WHEN_QUEUED: True,
            CONF_FRAME_SLEEP_MINUTES: 20,
            CONF_FRAME_ALWAYS_ON: True,
            CONF_ROTATION_EDGE: EDGE_RIGHT,
            "rotate_portrait_180": False,
            "rotate_landscape_180": True,
        },
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ORIENTATION] == ORIENTATION_PORTRAIT
    assert result["data"][CONF_ROTATION_EDGE] == EDGE_RIGHT
    assert result["data"][CONF_ROTATE_LANDSCAPE_180] is True
    assert result["data"][CONF_FRAME_ALWAYS_ON] is True
    assert result["data"][CONF_FRAME_SLEEP_MINUTES] == 20
    assert result["data"][CONF_FAST_POLL_WHEN_QUEUED] is True


async def test_scan_interval_below_minimum_rejected(hass, make_frame_entry):
    entry = make_frame_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"]

    import pytest

    with pytest.raises(vol.Invalid):
        schema({"scan_interval": 10})


async def test_frame_sleep_minutes_below_minimum_rejected(hass, make_frame_entry):
    entry = make_frame_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"]

    import pytest

    with pytest.raises(vol.Invalid):
        schema({CONF_FRAME_SLEEP_MINUTES: 0})
