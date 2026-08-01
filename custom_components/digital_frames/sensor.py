"""Sensor platform for the Fraimic integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfInformation,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import DigitalFramesCoordinator

from .const import CONF_NAME, CONF_SIZE, DOMAIN
from .frame_types import FRAME_TYPES, ORIGIN_OFFICIAL


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fraimic sensors from a config entry."""
    from .const import CONF_DRIVER, DRIVER_MEURAL  # noqa: PLC0415

    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Meural: no battery/charge/queue; local system sensors instead.
    if entry.data.get(CONF_DRIVER) == DRIVER_MEURAL:
        async_add_entities(
            [
                DigitalFramesFirmwareSensor(coordinator, entry),
                DigitalFramesIpAddressSensor(coordinator, entry),
                MeuralDeviceOrientationSensor(coordinator, entry),
                MeuralAmbientLightSensor(coordinator, entry),
                MeuralFreeSpaceSensor(coordinator, entry),
                MeuralWifiRssiSensor(coordinator, entry),
            ]
        )
        return

    # Samsung EM32DX (experimental): IP + MDC reachability for now.
    from .const import DRIVER_ROKU, DRIVER_SAMSUNG  # noqa: PLC0415

    if entry.data.get(CONF_DRIVER) == DRIVER_SAMSUNG:
        async_add_entities(
            [
                DigitalFramesIpAddressSensor(coordinator, entry),
                SamsungMdcReachableSensor(coordinator, entry),
            ]
        )
        return

    # Roku: no IP/battery of our own -- the linked media_player entity
    # already tracks its own state; just surface whether we could see it.
    if entry.data.get(CONF_DRIVER) == DRIVER_ROKU:
        async_add_entities([RokuReachableSensor(coordinator, entry)])
        return

    async_add_entities(
        [
            DigitalFramesBatterySensor(coordinator, entry),
            DigitalFramesWifiRssiSensor(coordinator, entry),
            DigitalFramesChargingSensor(coordinator, entry),
            DigitalFramesFirmwareSensor(coordinator, entry),
            DigitalFramesIpAddressSensor(coordinator, entry),
            DigitalFramesQueuedSendSensor(coordinator, entry),
        ]
    )


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


def frame_device_info(
    hass: HomeAssistant, coordinator: Any, entry: ConfigEntry
) -> DeviceInfo:
    """Device registry info for one frame -- shared by every entity platform
    (sensors, the orientation select) so they all land on the same device."""
    from .const import (  # noqa: PLC0415
        CONF_DRIVER,
        DRIVER_MEURAL,
        DRIVER_ROKU,
        DRIVER_SAMSUNG,
    )

    fw: str | None = None
    if coordinator.data:
        fw = coordinator.data.get("firmware_version")

    if entry.data.get(CONF_DRIVER) == DRIVER_MEURAL:
        manufacturer = "NETGEAR Meural"
        model = "Canvas (local)"
    elif entry.data.get(CONF_DRIVER) == DRIVER_SAMSUNG:
        manufacturer = "Samsung"
        model = "EM32DX (experimental)"
    elif entry.data.get(CONF_DRIVER) == DRIVER_ROKU:
        manufacturer = "Roku"
        model = "TV (cast via media_player)"
    else:
        frame_type = FRAME_TYPES.get(entry.data.get(CONF_SIZE))
        if frame_type is not None:
            manufacturer = (
                "Fraimic" if frame_type.origin == ORIGIN_OFFICIAL
                else "Community (Fraimic-compatible)"
            )
            model = frame_type.display_name
        else:
            manufacturer = "Fraimic"
            model = "E-Ink Canvas"

    info: dict[str, Any] = {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": entry.data[CONF_NAME],
        "manufacturer": manufacturer,
        "model": model,
        "sw_version": fw,
    }

    # configuration_url must be an absolute URL -- HA rejects relative
    # paths outright (and will fail entity setup entirely if it isn't
    # valid), so only add it when we actually have a base URL to anchor
    # to. Falls back to internal_url if no external_url is configured.
    base_url = hass.config.external_url or hass.config.internal_url
    if base_url:
        info["configuration_url"] = (
            f"{base_url.rstrip('/')}/fraimic?entry={entry.entry_id}"
        )

    return DeviceInfo(**info)


class DigitalFramesBaseSensor(CoordinatorEntity, SensorEntity):
    """Base class shared by all Fraimic sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DigitalFramesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise."""
        super().__init__(coordinator)
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        return frame_device_info(self.hass, self.coordinator, self._entry)

    def _frame_online(self) -> bool:
        """True when the last poll reached the frame (not retained-stale)."""
        data = self.coordinator.data
        if isinstance(data, dict) and "online" in data:
            return bool(data["online"])
        return bool(getattr(self.coordinator, "last_update_success", False))

    def _attrs_with_online(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Merge *extra* with ``online`` so UI can show last battery while asleep."""
        attrs: dict[str, Any] = {"online": self._frame_online()}
        if extra:
            attrs.update(extra)
        return attrs


# ---------------------------------------------------------------------------
# Individual sensors
# ---------------------------------------------------------------------------


class DigitalFramesBatterySensor(DigitalFramesBaseSensor):
    """Battery level sensor (%)."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    def __init__(
        self,
        coordinator: DigitalFramesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_battery"
        self._attr_name = "Battery"

    @property
    def native_value(self) -> float | None:
        """Return the battery percentage.

        Newer "eframe" firmware reports a flat ``battery_pct`` key instead
        of the nested ``battery.percent`` structure used by older frames.
        """
        if not self.coordinator.data:
            return None
        data = self.coordinator.data
        try:
            return float(data["battery"]["percent"])
        except (KeyError, TypeError, ValueError):
            pass
        try:
            return float(data["battery_pct"])
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Charging flag plus online/stale so panels keep last % while asleep."""
        extra: dict[str, Any] = {}
        data = self.coordinator.data
        if data:
            try:
                raw = data["battery"]["charging"]
                if isinstance(raw, bool):
                    extra["charging"] = raw
                else:
                    extra["charging"] = str(raw).lower() == "true"
            except (KeyError, TypeError):
                pass
        return self._attrs_with_online(extra or None)


class DigitalFramesWifiRssiSensor(DigitalFramesBaseSensor):
    """WiFi signal strength sensor (dBm)."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_registry_enabled_default = True

    def __init__(
        self,
        coordinator: DigitalFramesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_wifi_rssi"
        self._attr_name = "WiFi Signal"

    @property
    def native_value(self) -> int | None:
        """Return the RSSI value in dBm."""
        if not self.coordinator.data:
            return None
        try:
            return int(self.coordinator.data["wifi"]["rssi"])
        except (KeyError, TypeError, ValueError):
            return None


class DigitalFramesChargingSensor(DigitalFramesBaseSensor):
    """Charging state sensor (True / False)."""

    def __init__(
        self,
        coordinator: DigitalFramesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_charging"
        self._attr_name = "Charging"

    @property
    def native_value(self) -> str | None:
        """Return charging state as a string."""
        if not self.coordinator.data:
            return None
        try:
            raw = self.coordinator.data["battery"]["charging"]
        except (KeyError, TypeError):
            return None

        # The API may return a bool or a string "True"/"False".
        if isinstance(raw, bool):
            return str(raw)
        return str(raw).capitalize()


class DigitalFramesFirmwareSensor(DigitalFramesBaseSensor):
    """Firmware version diagnostic sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DigitalFramesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_firmware"
        self._attr_name = "Firmware"

    @property
    def native_value(self) -> str | None:
        """Return the firmware version string."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("firmware_version")


class DigitalFramesIpAddressSensor(DigitalFramesBaseSensor):
    """Current IP address diagnostic sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DigitalFramesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_ip"
        self._attr_name = "IP Address"

    @property
    def native_value(self) -> str | None:
        """Return the frame's current IP address.

        Newer "eframe" firmware reports a flat ``ip_address`` key instead
        of the nested ``wifi.ip`` structure used by older frames.
        """
        if not self.coordinator.data:
            return None
        data = self.coordinator.data
        try:
            return data["wifi"]["ip"]
        except (KeyError, TypeError):
            pass
        return data.get("ip_address")


class SamsungMdcReachableSensor(DigitalFramesBaseSensor):
    """Whether the Samsung MDC port answered on the last poll (often false while asleep)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DigitalFramesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_mdc_reachable"
        self._attr_name = "MDC reachable"

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        reachable = self.coordinator.data.get("reachable")
        if reachable is True:
            return "yes"
        if reachable is False:
            return "no"
        return None


class RokuReachableSensor(DigitalFramesBaseSensor):
    """Whether the linked Roku media_player entity was reachable on the last poll."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: DigitalFramesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_roku_reachable"
        self._attr_name = "Roku reachable"

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        reachable = self.coordinator.data.get("reachable")
        if reachable is True:
            return "yes"
        if reachable is False:
            return "no"
        return None


class MeuralDeviceOrientationSensor(DigitalFramesBaseSensor):
    """Physical hang orientation from the Meural gsensor (portrait/landscape).

    Read-only mirror of what the frame reports. The Orientation *select*
    (follow-device vs manual lock) is separate — see select.py.
    """

    def __init__(
        self,
        coordinator: DigitalFramesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_device_orientation"
        self._attr_name = "Device orientation"
        self._attr_icon = "mdi:phone-rotate-portrait"

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        value = self.coordinator.data.get("device_orientation")
        return value if isinstance(value, str) else None


class MeuralAmbientLightSensor(DigitalFramesBaseSensor):
    """Ambient light (lux) from the Meural ALS."""

    _attr_device_class = SensorDeviceClass.ILLUMINANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = LIGHT_LUX

    def __init__(
        self,
        coordinator: DigitalFramesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_ambient_light"
        self._attr_name = "Ambient light"

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.get("lux")
        try:
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None


class MeuralFreeSpaceSensor(DigitalFramesBaseSensor):
    """Free storage on the Canvas (MB), diagnostic."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES
    _attr_suggested_display_precision = 0

    def __init__(
        self,
        coordinator: DigitalFramesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_free_space"
        self._attr_name = "Free space"

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.get("free_space_mb")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None


class MeuralWifiRssiSensor(DigitalFramesBaseSensor):
    """WiFi signal (dBm) from Meural system wifi_status."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: DigitalFramesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_wifi_rssi"
        self._attr_name = "WiFi Signal"

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.get("wifi_rssi")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None


class DigitalFramesQueuedSendSensor(DigitalFramesBaseSensor):
    """Whether a send to this frame is queued awaiting delivery, because the
    frame was asleep/unreachable when it was sent -- see
    DigitalFramesCoordinator.pending_send.

    State is ``queued`` / ``idle``. Attributes expose what is on deck
    (``image_id``, ``queued_at``) so automations and the UI can identify
    the waiting image without polling the coordinator store.
    """

    def __init__(
        self,
        coordinator: DigitalFramesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_queued_send"
        self._attr_name = "Queued Image"

    @property
    def native_value(self) -> str:
        """Return "queued" while a send is waiting for the frame to wake,
        else "idle"."""
        return "queued" if self.coordinator.pending_send is not None else "idle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """On-deck payload identity while queued; empty when idle."""
        pending = self.coordinator.pending_send
        if not pending:
            return {}
        attrs: dict[str, Any] = {}
        image_id = pending.get("image_id")
        if image_id:
            attrs["image_id"] = image_id
        queued_at = pending.get("queued_at")
        if queued_at is not None:
            attrs["queued_at"] = queued_at
        return attrs
