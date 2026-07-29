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
