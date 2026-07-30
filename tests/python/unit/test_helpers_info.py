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


def test_origin_for_fraimic_entry_mac_tiebreak():
    """Community panels mis-tagged as size 13.3 must still report clone."""
    from types import SimpleNamespace

    from custom_components.digital_frames.const import CONF_MAC, CONF_SIZE
    from custom_components.digital_frames.helpers import origin_for_fraimic_entry
    from custom_components.digital_frames.frame_types import ORIGIN_CLONE, ORIGIN_OFFICIAL

    official = SimpleNamespace(data={CONF_SIZE: "13.3", CONF_MAC: "3cdc75737330"})
    assert origin_for_fraimic_entry(official) == ORIGIN_OFFICIAL

    community_wrong_size = SimpleNamespace(
        data={CONF_SIZE: "13.3", CONF_MAC: "90e5b1d6e09c"}  # non-Fraimic OUI
    )
    assert origin_for_fraimic_entry(community_wrong_size) == ORIGIN_CLONE

    clone_key = SimpleNamespace(data={CONF_SIZE: "13.3_clone", CONF_MAC: ""})
    assert origin_for_fraimic_entry(clone_key) == ORIGIN_CLONE


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
