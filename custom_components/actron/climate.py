"""Platform for Actron Air Neo climate integration."""

import logging
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVACMode,
    ClimateEntityFeature,
)
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Actron Neo climate entities from a config entry."""
    _LOGGER.info("Setting up Actron Neo climate platform")

    api = hass.data["actron_air_neo"]["api"]
    zones = hass.data["actron_air_neo"]["zones"]
    entities = [ActronNeoClimate(api, zone["id"], zone["name"]) for zone in zones]
    async_add_entities(entities)

class ActronNeoClimate(ClimateEntity):
    """Representation of an Actron Neo climate entity."""

    def __init__(self, api, zone_id, zone_name):
        """Initialize the climate entity."""
        self._api = api
        self._zone_id = zone_id
        self._name = f"Actron Neo Zone {zone_name}"
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_target_temperature = None
        self._attr_current_temperature = None
        self._zone_enabled = None

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return ClimateEntityFeature.TARGET_TEMPERATURE

    @property
    def hvac_modes(self):
        """Return the list of available HVAC modes."""
        return [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL]

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._attr_current_temperature

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._attr_target_temperature

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        if ATTR_TEMPERATURE in kwargs:
            self._attr_target_temperature = kwargs[ATTR_TEMPERATURE]
            await self._api.set_temperature(self._zone_id, self._attr_target_temperature)

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        self._attr_hvac_mode = hvac_mode
        await self._api.set_hvac_mode(self._zone_id, self._attr_hvac_mode)

    @property
    def is_on(self):
        """Return true if the zone is enabled."""
        return self._zone_enabled

    async def async_turn_on(self):
        """Turn the zone on."""
        await self._api.set_zone_state(self._zone_id, True)
        self._zone_enabled = True

    async def async_turn_off(self):
        """Turn the zone off."""
        await self._api.set_zone_state(self._zone_id, False)
        self._zone_enabled = False
