"""Support for Actron Air Neo sensors."""
from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ActronDataCoordinator

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Actron Air Neo sensors."""
    coordinator: ActronDataCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    # Main system sensors
    entities.extend([
        ActronTemperatureSensor(coordinator, "main", "indoor"),
        ActronTemperatureSensor(coordinator, "main", "outdoor"),
        ActronHumiditySensor(coordinator, "main"),
        ActronModeSensor(coordinator),
        ActronFanModeSensor(coordinator),
        ActronAwayModeSensor(coordinator),
        ActronQuietModeSensor(coordinator),
    ])

    # Zone sensors
    for zone_id in coordinator.data["zones"]:
        entities.extend([
            ActronZoneTemperatureSensor(coordinator, zone_id),
            ActronZoneHumiditySensor(coordinator, zone_id),
        ])

    async_add_entities(entities)

class ActronSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Actron Air Neo sensors."""

    def __init__(
        self,
        coordinator: ActronDataCoordinator,
        sensor_id: str,
        name: str,
        device_class: SensorDeviceClass | None,
        state_class: SensorStateClass | str | None,
        native_unit_of_measurement: str | None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_id = sensor_id
        self._attr_name = f"Actron Air Neo {sensor_id} {name}"
        self._attr_unique_id = f"{DOMAIN}_{coordinator.device_id}_{sensor_id}_{name.lower().replace(' ', '_')}"
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_native_unit_of_measurement = native_unit_of_measurement

    @property
    def device_info(self) -> dict[str, Any]:
        """Return device information about this entity."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.device_id)},
            "name": "Actron Air Neo",
            "manufacturer": "Actron Air",
            "model": "Neo",
        }

class ActronTemperatureSensor(ActronSensorBase):
    """Representation of an Actron Air Neo temperature sensor."""

    def __init__(
        self,
        coordinator: ActronDataCoordinator,
        sensor_id: str,
        sensor_type: str,
    ) -> None:
        """Initialize the temperature sensor."""
        super().__init__(
            coordinator,
            sensor_id,
            f"{sensor_type.capitalize()} Temperature",
            SensorDeviceClass.TEMPERATURE,
            SensorStateClass.MEASUREMENT,
            UnitOfTemperature.CELSIUS,
        )
        self._sensor_type = sensor_type

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        try:
            if self._sensor_type == "indoor":
                return self.coordinator.data['main']['indoor_temp']
            elif self._sensor_type == "outdoor":
                return self.coordinator.data['main']['outdoor_temp']
        except KeyError:
            _LOGGER.error(f"Failed to get temperature for {self._sensor_id} ({self._sensor_type})")
        return None

class ActronHumiditySensor(ActronSensorBase):
    """Representation of an Actron Air Neo humidity sensor."""

    def __init__(
        self,
        coordinator: ActronDataCoordinator,
        sensor_id: str,
    ) -> None:
        """Initialize the humidity sensor."""
        super().__init__(
            coordinator,
            sensor_id,
            "Humidity",
            SensorDeviceClass.HUMIDITY,
            SensorStateClass.MEASUREMENT,
            PERCENTAGE,
        )

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        try:
            if self._sensor_id == "main":
                return self.coordinator.data['main']['indoor_humidity']
        except KeyError:
            _LOGGER.error(f"Failed to get humidity for {self._sensor_id}")
        return None

class ActronModeSensor(ActronSensorBase):
    """Representation of an Actron Air Neo mode sensor."""

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the mode sensor."""
        super().__init__(
            coordinator,
            "main",
            "Mode",
            None,
            None,
            None,
        )

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        try:
            return self.coordinator.data["main"]["mode"]
        except KeyError:
            _LOGGER.error("Failed to get mode")
        return None

class ActronFanModeSensor(ActronSensorBase):
    """Representation of an Actron Air Neo fan mode sensor."""

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the fan mode sensor."""
        super().__init__(
            coordinator,
            "main",
            "Fan Mode",
            None,
            None,
            None,
        )

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        try:
            return self.coordinator.data["main"]["fan_mode"]
        except KeyError:
            _LOGGER.error("Failed to get fan mode")
        return None

class ActronAwayModeSensor(ActronSensorBase):
    """Representation of an Actron Air Neo away mode sensor."""

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the away mode sensor."""
        super().__init__(
            coordinator,
            "main",
            "Away Mode",
            SensorDeviceClass.ENUM,
            None,
            None,
        )

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        try:
            return "On" if self.coordinator.data["main"]["away_mode"] else "Off"
        except KeyError:
            _LOGGER.error("Failed to get away mode status")
        return None

    @property
    def options(self) -> list[str]:
        """Return the list of available options."""
        return ["On", "Off"]

class ActronQuietModeSensor(ActronSensorBase):
    """Representation of an Actron Air Neo quiet mode sensor."""

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the quiet mode sensor."""
        super().__init__(
            coordinator,
            "main",
            "Quiet Mode",
            SensorDeviceClass.ENUM,
            None,
            None,
        )

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        try:
            return "On" if self.coordinator.data["main"]["quiet_mode"] else "Off"
        except KeyError:
            _LOGGER.error("Failed to get quiet mode status")
        return None

    @property
    def options(self) -> list[str]:
        """Return the list of available options."""
        return ["On", "Off"]

class ActronZoneTemperatureSensor(ActronSensorBase):
    """Representation of an Actron Air Neo zone temperature sensor."""

    def __init__(self, coordinator: ActronDataCoordinator, zone_id: str):
        super().__init__(
            coordinator,
            f"zone_{zone_id}",
            f"Zone {zone_id} Temperature",
            SensorDeviceClass.TEMPERATURE,
            SensorStateClass.MEASUREMENT,
            UnitOfTemperature.CELSIUS,
        )
        self._zone_id = zone_id

    @property
    def native_value(self) -> StateType:
        return self.coordinator.data['zones'][self._zone_id]['temp']

class ActronZoneHumiditySensor(ActronSensorBase):
    """Representation of an Actron Air Neo zone humidity sensor."""

    def __init__(self, coordinator: ActronDataCoordinator, zone_id: str):
        super().__init__(
            coordinator,
            f"zone_{zone_id}",
            f"Zone {zone_id} Humidity",
            SensorDeviceClass.HUMIDITY,
            SensorStateClass.MEASUREMENT,
            PERCENTAGE,
        )
        self._zone_id = zone_id

    @property
    def native_value(self) -> StateType:
        return self.coordinator.data['zones'][self._zone_id]['humidity']