import logging
from typing import Any, Dict, Optional

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import (
    DOMAIN, ATTR_INDOOR_TEMPERATURE, ATTR_OUTDOOR_TEMPERATURE,
    HVAC_MODE_OFF, HVAC_MODE_AUTO, HVAC_MODE_COOL, HVAC_MODE_HEAT, HVAC_MODE_FAN_ONLY,
    FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH,
    API_KEY_USER_AIRCON_SETTINGS, API_KEY_IS_ON, API_KEY_MODE, API_KEY_FAN_MODE,
    API_KEY_TEMP_SETPOINT_COOL, API_KEY_TEMP_SETPOINT_HEAT,
    CMD_SET_SETTINGS
)

_LOGGER = logging.getLogger(__name__)

HVAC_MODES = {
    HVAC_MODE_OFF: HVACMode.OFF,
    HVAC_MODE_AUTO: HVACMode.AUTO,
    HVAC_MODE_COOL: HVACMode.COOL,
    HVAC_MODE_HEAT: HVACMode.HEAT,
    HVAC_MODE_FAN_ONLY: HVACMode.FAN_ONLY,
}

FAN_MODES = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]

async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([ActronClimate(coordinator)], True)

class ActronClimate(CoordinatorEntity, ClimateEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Actron Air Neo"
        self._attr_unique_id = f"{DOMAIN}_climate"
        self._attr_hvac_modes = list(HVAC_MODES.values())
        self._attr_fan_modes = FAN_MODES
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE |
            ClimateEntityFeature.FAN_MODE |
            ClimateEntityFeature.TARGET_TEMPERATURE_RANGE |
            ClimateEntityFeature.TURN_ON |
            ClimateEntityFeature.TURN_OFF
        )

    @property
    def current_temperature(self) -> Optional[float]:
        return self.coordinator.data.get(ATTR_INDOOR_TEMPERATURE)

    @property
    def target_temperature(self) -> Optional[float]:
        if self.hvac_mode == HVACMode.COOL:
            return self.coordinator.data.get('temperatureSetpointCool')
        elif self.hvac_mode == HVACMode.HEAT:
            return self.coordinator.data.get('temperatureSetpointHeat')
        return None

    @property
    def target_temperature_high(self) -> Optional[float]:
        if self.hvac_mode == HVACMode.AUTO:
            return self.coordinator.data.get('temperatureSetpointCool')
        return None

    @property
    def target_temperature_low(self) -> Optional[float]:
        if self.hvac_mode == HVACMode.AUTO:
            return self.coordinator.data.get('temperatureSetpointHeat')
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        is_on = self.coordinator.data.get('isOn', False)
        if not is_on:
            return HVACMode.OFF
        mode = self.coordinator.data.get('mode')
        return HVAC_MODES.get(mode, HVACMode.OFF)

    @property
    def fan_mode(self) -> Optional[str]:
        return self.coordinator.data.get('fanMode')

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {
            ATTR_OUTDOOR_TEMPERATURE: self.coordinator.data.get(ATTR_OUTDOOR_TEMPERATURE)
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if ATTR_TEMPERATURE in kwargs:
            temp = kwargs[ATTR_TEMPERATURE]
            if self.hvac_mode == HVACMode.COOL:
                await self._send_command({API_KEY_TEMP_SETPOINT_COOL: temp})
            elif self.hvac_mode == HVACMode.HEAT:
                await self._send_command({API_KEY_TEMP_SETPOINT_HEAT: temp})
        elif "target_temp_high" in kwargs and "target_temp_low" in kwargs:
            await self._send_command({
                API_KEY_TEMP_SETPOINT_COOL: kwargs["target_temp_high"],
                API_KEY_TEMP_SETPOINT_HEAT: kwargs["target_temp_low"]
            })

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._send_command({API_KEY_IS_ON: False})
        else:
            command = {API_KEY_IS_ON: True, API_KEY_MODE: hvac_mode.upper()}
            await self._send_command(command)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._send_command({API_KEY_FAN_MODE: fan_mode})

    async def async_turn_on(self) -> None:
        await self._send_command({API_KEY_IS_ON: True})

    async def async_turn_off(self) -> None:
        await self._send_command({API_KEY_IS_ON: False})

    async def _send_command(self, command: Dict[str, Any]) -> None:
        full_command = {f"{API_KEY_USER_AIRCON_SETTINGS}.{key}": value for key, value in command.items()}
        full_command["type"] = CMD_SET_SETTINGS
        await self.coordinator.api.send_command(self.coordinator.device_id, full_command)
        await self.coordinator.async_request_refresh()