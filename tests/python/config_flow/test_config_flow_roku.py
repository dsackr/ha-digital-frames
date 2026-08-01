"""Add a Roku TV frame (KPF 36) — entity picker over HA core's `roku`
media_player, no discovery/probe of our own.

If this silently breaks: users can't add a Roku frame at all, or an
already-configured Roku media_player is offered again (duplicate entries
targeting the same physical TV).
"""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.digital_frames.const import (
    CONF_DEVICE_KEY,
    CONF_DRIVER,
    CONF_HEIGHT,
    CONF_NAME,
    CONF_ROKU_ENTITY_ID,
    CONF_SIZE,
    CONF_WIDTH,
    DOMAIN,
    DRIVER_ROKU,
    ROKU_DEFAULT_HEIGHT,
    ROKU_DEFAULT_WIDTH,
    ROKU_SIZE_LABEL,
)


def _register_roku_media_player(hass, unique_id: str, object_id: str) -> str:
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "media_player",
        "roku",
        unique_id,
        suggested_object_id=object_id,
    )
    return entry.entity_id


async def test_menu_offers_add_roku(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.MENU
    assert "add_roku" in result["menu_options"]


async def test_add_roku_no_media_players_aborts(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "add_roku"}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_roku_media_players"


async def test_add_roku_creates_entry(hass):
    entity_id = _register_roku_media_player(hass, "ROKU123", "living_room_roku")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "add_roku"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "add_roku"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_ROKU_ENTITY_ID: entity_id,
            CONF_NAME: "Living Room Roku",
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DRIVER] == DRIVER_ROKU
    assert result["data"][CONF_ROKU_ENTITY_ID] == entity_id
    assert result["data"][CONF_SIZE] == ROKU_SIZE_LABEL
    assert result["data"][CONF_WIDTH] == ROKU_DEFAULT_WIDTH
    assert result["data"][CONF_HEIGHT] == ROKU_DEFAULT_HEIGHT
    assert result["data"][CONF_DEVICE_KEY] == f"roku:{entity_id}"


async def test_add_roku_excludes_already_configured_entity(hass):
    entity_id = _register_roku_media_player(hass, "ROKU456", "bedroom_roku")

    MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"roku:{entity_id}",
        data={
            CONF_DRIVER: DRIVER_ROKU,
            CONF_ROKU_ENTITY_ID: entity_id,
            CONF_NAME: "Bedroom Roku",
            CONF_WIDTH: ROKU_DEFAULT_WIDTH,
            CONF_HEIGHT: ROKU_DEFAULT_HEIGHT,
            CONF_SIZE: ROKU_SIZE_LABEL,
            CONF_DEVICE_KEY: f"roku:{entity_id}",
        },
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "add_roku"}
    )
    # The only registered Roku media_player is already configured here.
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_roku_media_players"


async def test_add_roku_ignores_non_roku_media_players(hass):
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "media_player", "cast", "CAST1", suggested_object_id="living_room_tv"
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "add_roku"}
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_roku_media_players"
