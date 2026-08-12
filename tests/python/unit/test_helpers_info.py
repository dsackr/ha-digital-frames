"""Test the /info page helper parsers."""

from __future__ import annotations

from custom_components.digital_frames.helpers import (
    parse_keep_awake_from_html,
    parse_sleep_minutes_from_html,
)


def test_parse_keep_awake_from_html():
    # Keep Awake matches
    assert parse_keep_awake_from_html(
        "<span class='info-label'>Keep Awake</span><span class='info-value'>Yes</span>"
    ) is True
    assert parse_keep_awake_from_html(
        "<span class=\"info-label\">Keep Awake</span><span class=\"info-value\">No</span>"
    ) is False
    assert parse_keep_awake_from_html(
        "<span class='info-label'>always_on</span><span class='info-value'>1</span>"
    ) is True
    assert parse_keep_awake_from_html(
        "<span class='info-label'>Always On</span><span class='info-value'>Disabled</span>"
    ) is False

    # Formatting quirks / spaces
    assert parse_keep_awake_from_html(
        "<span>Keep  Awake</span> <span class='info-value'>\n true\t</span>"
    ) is True

    # No match
    assert parse_keep_awake_from_html(
        "<span class='info-label'>Device Type</span><span class='info-value'>13.3\" E-Ink</span>"
    ) is None


def test_origin_for_fraimic_entry_ignores_mac():
    """Origin comes from the registered frame type, never from MAC OUI.

    GH #22: a genuine Fraimic Canvas 31.5" was reported as origin=clone
    solely because its MAC prefix wasn't in the known-official set --
    OUI identifies the Wi-Fi module vendor/batch, not the assembled
    frame's provenance, so it must never override the declared size's
    registry origin.
    """
    from types import SimpleNamespace

    from custom_components.digital_frames.const import CONF_MAC, CONF_SIZE
    from custom_components.digital_frames.helpers import origin_for_fraimic_entry
    from custom_components.digital_frames.frame_types import ORIGIN_CLONE, ORIGIN_OFFICIAL

    official_known_mac = SimpleNamespace(data={CONF_SIZE: "13.3", CONF_MAC: "3cdc75737330"})
    assert origin_for_fraimic_entry(official_known_mac) == ORIGIN_OFFICIAL

    # Official size, unrecognized MAC (GH #22 evidence: official frames
    # have shipped with multiple, not-fully-known Espressif OUIs).
    official_unknown_mac = SimpleNamespace(
        data={CONF_SIZE: "31.5", CONF_MAC: "94a99012ab34"}
    )
    assert origin_for_fraimic_entry(official_unknown_mac) == ORIGIN_OFFICIAL

    clone_size = SimpleNamespace(data={CONF_SIZE: "13.3_clone", CONF_MAC: ""})
    assert origin_for_fraimic_entry(clone_size) == ORIGIN_CLONE

    unknown_size = SimpleNamespace(data={CONF_SIZE: "not_a_real_size", CONF_MAC: ""})
    assert origin_for_fraimic_entry(unknown_size) is None


def test_detect_frame_type_from_info_unambiguous_cases_ignore_mac():
    """Unique device_type/resolution matches resolve regardless of MAC."""
    from custom_components.digital_frames.helpers import detect_frame_type_from_info

    unknown_mac = {"wifi": {"mac": "94:a9:90:12:ab:34"}}  # not a known-official OUI

    # device_type text names a size with only one registry entry (31.5"
    # has no clone counterpart).
    info = {**unknown_mac, "display": {"device_type": '31.5" E-Ink'}}
    assert detect_frame_type_from_info(info) == "31.5"

    # Resolution matches only one registry entry (7.3" 800x480 is unique).
    info = {**unknown_mac, "width": 800, "height": 480}
    assert detect_frame_type_from_info(info) == "7.3"

    # No device_type text and no dimensions at all -> unknown.
    assert detect_frame_type_from_info(unknown_mac) is None


def test_detect_frame_type_from_info_ambiguous_size_returns_unknown():
    """13.3" official vs clone share both label and resolution (1200x1600).

    GH #22: this must resolve to unknown rather than guess from MAC OUI,
    even when the MAC looks like a known-official or known-non-official
    prefix -- config_flow falls back to asking the user in this case.
    """
    from custom_components.digital_frames.helpers import detect_frame_type_from_info

    known_official_mac = {"wifi": {"mac": "3c:dc:75:73:73:30"}}
    unknown_mac = {"wifi": {"mac": "94:a9:90:12:ab:34"}}

    for mac_info in (known_official_mac, unknown_mac):
        by_text = {**mac_info, "display": {"device_type": '13.3" E-Ink'}}
        assert detect_frame_type_from_info(by_text) is None

        by_dims = {**mac_info, "width": 1200, "height": 1600}
        assert detect_frame_type_from_info(by_dims) is None


def test_parse_sleep_minutes_from_html():
    # Sleep matches
    assert parse_sleep_minutes_from_html(
        "<span class='info-label'>Sleep Minutes</span><span class='info-value'>15</span>"
    ) == 15
    assert parse_sleep_minutes_from_html(
        "<span class=\"info-label\">Sleep Duration</span><span class=\"info-value\">20 minutes</span>"
    ) == 20
    assert parse_sleep_minutes_from_html(
        "<span class='info-label'>Sleep</span><span class='info-value'>30m</span>"
    ) == 30

    # No match or no number
    assert parse_sleep_minutes_from_html(
        "<span class='info-label'>Sleep Minutes</span><span class='info-value'>unknown</span>"
    ) is None
    assert parse_sleep_minutes_from_html(
        "<span class='info-label'>Device Type</span><span class='info-value'>13.3\" E-Ink</span>"
    ) is None
