"""Support for ActronAir Neo climate devices."""
from __future__ import annotations

from typing import Any
import logging

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import (
    FAN_LOW,
    FAN_MEDIUM,
    FAN_HIGH,
    FAN_AUTO,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
    MIN_TEMP,
    MAX_TEMP,
)
from .coordinator import ActronDataCoordinator

_LOGGER = logging.getLogger(__name__)

HVAC_MODES = [HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT, HVACMode.FAN_ONLY, HVACMode.AUTO]
FAN_MODES = [FAN_LOW, FAN_MEDIUM, FAN_HIGH, FAN_AUTO]

FAN_MODE_MAP = {
    FAN_LOW: "LOW",
    FAN_MEDIUM: "MED",
    FAN_HIGH: "HIGH",
    FAN_AUTO: "AUTO",
}

REVERSE_FAN_MODE_MAP = {v: k for k, v in FAN_MODE_MAP.items()}

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ActronAir Neo climate device from a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = [ActronClimate(coordinator)]

    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(entity_registry, config_entry.entry_id)

    if coordinator.enable_zone_control:
        for zone_id, zone_data in coordinator.data['zones'].items():
            entities.append(ActronZoneClimate(coordinator, zone_id))
    else:
        # Remove any existing zone climate entities
        for entry in entries:
            if entry.unique_id.startswith(f"{coordinator.device_id}_zone_"):
                entity_registry.async_remove(entry.entity_id)

    async_add_entities(entities, update_before_add=True)


class ActronClimate(CoordinatorEntity, ClimateEntity):
    """Representation of an ActronAir Neo climate device."""

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the climate device."""
        super().__init__(coordinator)
        self._attr_name = "ActronAir Neo"
        self._attr_unique_id = f"{coordinator.device_id}_climate"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_modes = HVAC_MODES
        self._attr_fan_modes = FAN_MODES
        self._attr_min_temp = MIN_TEMP
        self._attr_max_temp = MAX_TEMP
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.coordinator.data["main"]["indoor_temp"]

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        if self.hvac_mode == HVACMode.COOL:
            return self.coordinator.data["main"]["temp_setpoint_cool"]
        elif self.hvac_mode == HVACMode.HEAT:
            return self.coordinator.data["main"]["temp_setpoint_heat"]
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return hvac operation ie. heat, cool mode."""
        if not self.coordinator.data["main"]["is_on"]:
            return HVACMode.OFF
        mode = self.coordinator.data["main"]["mode"]
        return self._actron_to_ha_hvac_mode(mode)

    @property
    def fan_mode(self) -> str | None:
        """Return the fan setting."""
        actron_fan_mode = self.coordinator.data["main"]["fan_mode"]
        return REVERSE_FAN_MODE_MAP.get(actron_fan_mode.split('-')[0], FAN_LOW)  # Default to FAN_LOW if not found

    @property
    def current_humidity(self) -> int | None:
        """Return the current humidity."""
        return self.coordinator.data["main"]["indoor_humidity"]

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        is_cooling = self.hvac_mode in [HVACMode.COOL, HVACMode.AUTO]
        await self.coordinator.set_temperature(temperature, is_cooling)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == self.hvac_mode:
            return  # No change needed

        if hvac_mode == HVACMode.OFF:
            command = self.coordinator.api.create_command("OFF")
        else:
            actron_mode = self._ha_to_actron_hvac_mode(hvac_mode)
            command = self.coordinator.api.create_command("CLIMATE_MODE", mode=actron_mode)
        
        await self.coordinator.api.send_command(self.coordinator.device_id, command)
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        actron_fan_mode = FAN_MODE_MAP.get(fan_mode, "LOW")  # Default to LOW if not found
        current_fan_mode = self.coordinator.data["main"]["fan_mode"]
        continuous = current_fan_mode.endswith("-CONT")
        await self.coordinator.set_fan_mode(actron_fan_mode, continuous)

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        if self.hvac_mode != HVACMode.OFF:
            return  # Already on

        command = self.coordinator.api.create_command("ON")
        await self.coordinator.api.send_command(self.coordinator.device_id, command)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        if self.hvac_mode == HVACMode.OFF:
            return  # Already off

        command = self.coordinator.api.create_command("OFF")
        await self.coordinator.api.send_command(self.coordinator.device_id, command)
        await self.coordinator.async_request_refresh()

    def _actron_to_ha_hvac_mode(self, mode: str) -> HVACMode:
        """Convert Actron HVAC mode to HA HVAC mode."""
        mode_map = {
            "AUTO": HVACMode.AUTO,
            "HEAT": HVACMode.HEAT,
            "COOL": HVACMode.COOL,
            "FAN": HVACMode.FAN_ONLY,
            "OFF": HVACMode.OFF,
        }
        return mode_map.get(mode.upper(), HVACMode.OFF)

    def _ha_to_actron_hvac_mode(self, mode: HVACMode) -> str:
        """Convert HA HVAC mode to Actron HVAC mode."""
        mode_map = {
            HVACMode.AUTO: "AUTO",
            HVACMode.HEAT: "HEAT",
            HVACMode.COOL: "COOL",
            HVACMode.FAN_ONLY: "FAN",
            HVACMode.OFF: "OFF",
        }
        return mode_map.get(mode, "OFF")

    @property
    def device_info(self):
        """Return device information about this entity."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.device_id)},
            "name": self.name,
            "manufacturer": "ActronAir",
            "model": self.coordinator.data["main"]["model"],
            "sw_version": self.coordinator.data["main"]["firmware_version"],
        }

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {
            "away_mode": self.coordinator.data["main"]["away_mode"],
            "quiet_mode": self.coordinator.data["main"]["quiet_mode"],
            "continuous_fan": self.coordinator.data["main"]["fan_mode"].endswith("-CONT"),
        }
    
class ActronZoneClimate(CoordinatorEntity, ClimateEntity):
    """Representation of an ActronAir Neo Zone climate device."""

    def __init__(self, coordinator: ActronDataCoordinator, zone_id: str) -> None:
        """Initialize the zone climate device."""
        super().__init__(coordinator)
        self.zone_id = zone_id
        
        # Validate required data is available
        if not coordinator.data.get('zones', {}).get(zone_id):
            raise ValueError(f"Zone {zone_id} data not available")

        # Get zone info from RemoteZoneInfo array to check capabilities
        zone_info = next((
            zone for zone in coordinator.data["raw_data"].get("lastKnownState", {})
            .get(f"<{coordinator.device_id.upper()}>", {}).get("RemoteZoneInfo", [])
            if zone.get("NV_Title") == coordinator.data['zones'][zone_id]['name']
        ), {})
        
        # Check if zone supports temperature control
        self._has_temp_control = (
            zone_info.get("NV_VAV", False) 
            and zone_info.get("NV_ITC", False)
        )

        if not self._has_temp_control:
            _LOGGER.debug(
                "Zone %s (%s) does not support individual temperature control",
                zone_id,
                coordinator.data['zones'][zone_id]['name']
            )
            
        self._attr_name = f"ActronAir Neo Zone {coordinator.data['zones'][zone_id]['name']}"
        self._attr_unique_id = f"{coordinator.device_id}_zone_{zone_id}"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.HEAT, HVACMode.AUTO]
        self._attr_min_temp = MIN_TEMP
        self._attr_max_temp = MAX_TEMP
        
        # Base features all zones support
        features = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF

        # Only add temperature control if supported
        if self._has_temp_control:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
            
        self._attr_supported_features = features

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            super().available 
            and self.coordinator.enable_zone_control
            and self.coordinator.data.get('zones', {}).get(self.zone_id) is not None
        )

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.coordinator.data['zones'][self.zone_id]['temp']

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        # Return None if zone doesn't support temperature control
        if not self._has_temp_control:
            return None

        try:
            if not self.coordinator.enable_zone_control:
                return None
                
            zone_data = self.coordinator.data['zones'][self.zone_id]
            main_mode = self.coordinator.data["main"]["mode"]
            
            if main_mode == "COOL":
                return zone_data.get('temp_setpoint_cool', None)
            elif main_mode == "HEAT":  
                return zone_data.get('temp_setpoint_heat', None)
            elif main_mode == "AUTO":
                # In auto mode, return based on current compressor state
                compressor_state = self.coordinator.data["main"]["compressor_state"]
                if compressor_state == "COOL":
                    return zone_data.get('temp_setpoint_cool', None)
                elif compressor_state == "HEAT":
                    return zone_data.get('temp_setpoint_heat', None)
            return None
            
        except (KeyError, TypeError) as err:
            _LOGGER.debug(f"Error getting target temperature for zone {self.zone_id}: {err}")
            return None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return hvac operation ie. heat, cool mode."""
        # Return OFF if zone is disabled
        if not self.coordinator.data['zones'][self.zone_id]['is_enabled']:
            return HVACMode.OFF
        
        # Otherwise use main unit's mode
        mode = self.coordinator.data["main"]["mode"]
        return self._actron_to_ha_hvac_mode(mode)

    @property
    def current_humidity(self) -> int | None:
        """Return the current humidity."""
        return self.coordinator.data['zones'][self.zone_id]['humidity']

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if not self._has_temp_control:
            _LOGGER.warning(
                "Zone %s does not support temperature control", 
                self.coordinator.data['zones'][self.zone_id]['name']
            )
            return

        if not self.coordinator.enable_zone_control:
            _LOGGER.warning("Cannot set temperature: Zone control is disabled")
            return

        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
            
        if not (MIN_TEMP <= temperature <= MAX_TEMP):
            _LOGGER.warning(f"Requested temperature {temperature} outside valid range")
            return

        try:
            main_mode = self.coordinator.data["main"]["mode"]
            
            # Handle different modes appropriately
            if main_mode == "AUTO":
                # In auto mode, update both setpoints
                await self.coordinator.set_zone_temperature(self.zone_id, temperature, "TemperatureSetpoint_Cool_oC")
                await self.coordinator.set_zone_temperature(self.zone_id, temperature, "TemperatureSetpoint_Heat_oC")
            elif main_mode == "COOL":
                await self.coordinator.set_zone_temperature(self.zone_id, temperature, "TemperatureSetpoint_Cool_oC")
            elif main_mode == "HEAT":
                await self.coordinator.set_zone_temperature(self.zone_id, temperature, "TemperatureSetpoint_Heat_oC")
                
        except Exception as err:
            _LOGGER.error(f"Failed to set temperature for zone {self.zone_id}: {err}")
            raise

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if not self.coordinator.enable_zone_control:
            _LOGGER.warning("Cannot set HVAC mode: Zone control is disabled")
            return

        try:
            if hvac_mode == HVACMode.OFF:
                await self.coordinator.set_zone_state(self.zone_id, False)
            else:
                await self.coordinator.set_zone_state(self.zone_id, True)
                actron_mode = self._ha_to_actron_hvac_mode(hvac_mode)
                await self.coordinator.set_climate_mode(actron_mode)
        except Exception as err:
            _LOGGER.error(f"Failed to set HVAC mode for zone {self.zone_id}: {err}")
            raise

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        if not self.coordinator.enable_zone_control:
            _LOGGER.warning("Cannot turn on: Zone control is disabled")
            return

        try:
            await self.coordinator.set_zone_state(self.zone_id, True)
        except Exception as err:
            _LOGGER.error(f"Failed to turn on zone {self.zone_id}: {err}")
            raise

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        if not self.coordinator.enable_zone_control:
            _LOGGER.warning("Cannot turn off: Zone control is disabled")
            return

        try:
            await self.coordinator.set_zone_state(self.zone_id, False)
        except Exception as err:
            _LOGGER.error(f"Failed to turn off zone {self.zone_id}: {err}")
            raise

    def _actron_to_ha_hvac_mode(self, mode: str) -> HVACMode:
        """Convert Actron HVAC mode to HA HVAC mode."""
        mode_map = {
            "AUTO": HVACMode.AUTO,
            "HEAT": HVACMode.HEAT,
            "COOL": HVACMode.COOL,
            "FAN": HVACMode.FAN_ONLY,
            "OFF": HVACMode.OFF,
        }
        return mode_map.get(mode.upper(), HVACMode.OFF)

    def _ha_to_actron_hvac_mode(self, mode: HVACMode) -> str:
        """Convert HA HVAC mode to Actron HVAC mode."""
        mode_map = {
            HVACMode.AUTO: "AUTO",
            HVACMode.HEAT: "HEAT",
            HVACMode.COOL: "COOL",
            HVACMode.FAN_ONLY: "FAN",
            HVACMode.OFF: "OFF",
        }
        return mode_map.get(mode, "OFF")

    @property
    def device_info(self):
        """Return device information about this entity."""
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.device_id}_zone_{self.zone_id}")},
            "name": self.name,
            "manufacturer": "ActronAir",
            "model": f"{self.coordinator.data['main']['model']} Zone",
            "sw_version": self.coordinator.data["main"]["firmware_version"],
            "via_device": (DOMAIN, self.coordinator.device_id),
        }

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {
            "zone_name": self.coordinator.data['zones'][self.zone_id]['name'],
            "supports_temperature_control": self._has_temp_control,
        }