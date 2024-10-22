# ActronAir Neo Coordinator

from datetime import timedelta
from typing import Any, Dict, Optional, List
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.components.climate.const import HVACMode

from .api import ActronApi, AuthenticationError, ApiError
from .const import DOMAIN, MAX_ZONES

_LOGGER = logging.getLogger(__name__)

class ActronDataCoordinator(DataUpdateCoordinator):
    """Class to manage fetching ActronAir Neo data."""

    def __init__(self, hass: HomeAssistant, api: ActronApi, device_id: str, update_interval: int, enable_zone_control: bool):
        """Initialize the data coordinator.
        
        Args:
            hass: HomeAssistant instance
            api: ActronApi instance for API communication
            device_id: Unique identifier for the device
            update_interval: Update interval in seconds
            enable_zone_control: Whether zone control is enabled
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )
        self.api = api
        self.device_id = device_id
        self.enable_zone_control = enable_zone_control
        self.last_data = None

    async def set_enable_zone_control(self, enable: bool):
        """Update the enable_zone_control status."""
        self.enable_zone_control = enable
        await self.async_request_refresh()

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from API endpoint."""
        try:
            if not self.api.is_api_healthy():
                _LOGGER.warning("API is not healthy, using cached data")
                return self.last_data if self.last_data else {}

            _LOGGER.debug(f"Fetching data for device {self.device_id}")
            status = await self.api.get_ac_status(self.device_id)
            parsed_data = self._parse_data(status)
            self.last_data = parsed_data
            _LOGGER.debug(f"Parsed data: {parsed_data}")
            return parsed_data
        except AuthenticationError as err:
            _LOGGER.error(f"Authentication error: {err}")
            raise ConfigEntryAuthFailed from err
        except ApiError as err:
            _LOGGER.error(f"Error communicating with API: {err}")
            if self.last_data:
                _LOGGER.warning("Using cached data due to API error")
                return self.last_data
            raise UpdateFailed(f"Error communicating with API: {err}") from err
        except Exception as err:
            _LOGGER.error(f"Unexpected error occurred: {err}")
            if self.last_data:
                _LOGGER.warning("Using cached data due to unexpected error")
                return self.last_data
            raise UpdateFailed(f"Unexpected error: {err}") from err

    def _parse_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse the data from the API into a format suitable for the climate entity."""
        try:
            last_known_state = data.get("lastKnownState", {})
            user_aircon_settings = last_known_state.get("UserAirconSettings", {})
            master_info = last_known_state.get("MasterInfo", {})
            live_aircon = last_known_state.get("LiveAircon", {})
            aircon_system = last_known_state.get("AirconSystem", {})

            parsed_data = {
                "main": {
                    "is_on": user_aircon_settings.get("isOn", False),
                    "mode": user_aircon_settings.get("Mode", "OFF"),
                    "fan_mode": user_aircon_settings.get("FanMode", "LOW"),
                    "temp_setpoint_cool": user_aircon_settings.get("TemperatureSetpoint_Cool_oC"),
                    "temp_setpoint_heat": user_aircon_settings.get("TemperatureSetpoint_Heat_oC"),
                    "indoor_temp": master_info.get("LiveTemp_oC"),
                    "indoor_humidity": master_info.get("LiveHumidity_pc"),
                    "compressor_state": live_aircon.get("CompressorMode", "OFF"),
                    "EnabledZones": user_aircon_settings.get("EnabledZones", []),
                    "away_mode": user_aircon_settings.get("AwayMode", False),
                    "quiet_mode": user_aircon_settings.get("QuietMode", False),
                    "model": aircon_system.get("MasterWCModel"),
                    "serial_number": aircon_system.get("MasterSerial"),
                    "firmware_version": aircon_system.get("MasterWCFirmwareVersion"),
                },
                "zones": {}
            }

            # Parse zone data
            remote_zone_info = last_known_state.get("RemoteZoneInfo", [])
            for i, zone in enumerate(remote_zone_info):
                if i < MAX_ZONES and zone.get("NV_Exists", False):
                    zone_id = f"zone_{i+1}"
                    parsed_data["zones"][zone_id] = {
                        "name": zone.get("NV_Title", f"Zone {i+1}"),
                        "temp": zone.get("LiveTemp_oC"),
                        "humidity": zone.get("LiveHumidity_pc"),
                        "is_enabled": parsed_data["main"]["EnabledZones"][i] if i < len(parsed_data["main"]["EnabledZones"]) else False,
                    }

            return parsed_data

        except Exception as e:
            _LOGGER.error(f"Failed to parse API response: {e}")
            raise UpdateFailed(f"Failed to parse API response: {e}")

    async def set_hvac_mode(self, hvac_mode: str) -> None:
        """Set HVAC mode."""
        try:
            if hvac_mode == HVACMode.OFF:
                command = self.api.create_command("OFF")
            else:
                command = self.api.create_command("CLIMATE_MODE", mode=hvac_mode)
            await self.api.send_command(self.device_id, command)
            await self.async_request_refresh()
        except Exception as err:
            _LOGGER.error(f"Failed to set HVAC mode to {hvac_mode}: {err}")
            raise

    async def set_temperature(self, temperature: float, is_cooling: bool) -> None:
        """Set temperature."""
        try:
            command = self.api.create_command("SET_TEMP", temp=temperature, is_cool=is_cooling)
            await self.api.send_command(self.device_id, command)
            await self.async_request_refresh()
        except Exception as err:
            _LOGGER.error(f"Failed to set {'cooling' if is_cooling else 'heating'} temperature to {temperature}: {err}")
            raise

    async def set_fan_mode(self, fan_mode: str, continuous: bool = False) -> None:
        """Set fan mode."""
        try:
            await self.api.set_fan_mode(fan_mode, continuous)
            await self.async_request_refresh()
        except Exception as err:
            _LOGGER.error(f"Failed to set fan mode to {fan_mode} (continuous: {continuous}): {err}")
            raise

    async def set_zone_temperature(self, zone_id: str, temperature: float, temp_key: str) -> None:
        """Set temperature for a specific zone with comprehensive validation.
        
        Args:
            zone_id: Identifier for the zone
            temperature: Target temperature
            temp_key: Temperature key for heating or cooling
            
        Raises:
            ValueError: If zone control is disabled or validation fails
            ApiError: If API communication fails
        """
        if not self.enable_zone_control:
            _LOGGER.error("Attempted to set zone temperature while zone control is disabled")
            raise ValueError("Zone control is not enabled")

        if not self.last_data:
            _LOGGER.error("No data available for zone temperature control")
            raise ValueError("No system data available")

        zones_data = self.last_data.get("zones", {})
        zone_data = zones_data.get(zone_id)
        
        if not zone_data:
            _LOGGER.error(f"Zone {zone_id} not found in available zones: {list(zones_data.keys())}")
            raise ValueError(f"Zone {zone_id} not found")

        if not zone_data.get("is_enabled", False):
            _LOGGER.error(f"Cannot set temperature for disabled zone {zone_id}")
            raise ValueError(f"Zone {zone_id} is not enabled")

        try:
            zone_index = int(zone_id.split('_')[1]) - 1
            command = self.api.create_command("SET_ZONE_TEMP", 
                                        zone=zone_index, 
                                        temp=temperature, 
                                        temp_key=temp_key)
            await self.api.send_command(self.device_id, command)
            _LOGGER.info(f"Successfully set zone {zone_id} temperature to {temperature}")
            await self.async_request_refresh()
        except Exception as err:
            _LOGGER.error(f"Failed to set zone {zone_id} temperature to {temperature}: {err}")
            raise

    async def set_zone_state(self, zone_id: str, enable: bool) -> None:
        """Set zone state."""
        try:
            zone_index = int(zone_id.split('_')[1]) - 1  # Convert zone_id to zero-based index
            current_zone_status = self.last_data["main"]["EnabledZones"]
            modified_statuses = current_zone_status.copy()
            modified_statuses[zone_index] = enable
            command = self.api.create_command("SET_ZONE_STATE", zones=modified_statuses)
            await self.api.send_command(self.device_id, command)
            await self.async_request_refresh()
        except Exception as err:
            _LOGGER.error(f"Failed to set zone {zone_id} state to {'on' if enable else 'off'}: {err}")
            raise

    async def set_climate_mode(self, mode: str) -> None:
        """Set climate mode for all zones."""
        try:
            command = self.api.create_command("CLIMATE_MODE", mode=mode)
            await self.api.send_command(self.device_id, command)
            await self.async_request_refresh()
        except Exception as err:
            _LOGGER.error(f"Failed to set climate mode to {mode}: {err}")
            raise

    async def set_away_mode(self, state: bool) -> None:
        """Set away mode."""
        try:
            await self.api.set_away_mode(state)
            await self.async_request_refresh()
        except Exception as err:
            _LOGGER.error(f"Failed to set away mode to {state}: {err}")
            raise

    async def set_quiet_mode(self, state: bool) -> None:
        """Set quiet mode."""
        try:
            await self.api.set_quiet_mode(state)
            await self.async_request_refresh()
        except Exception as err:
            _LOGGER.error(f"Failed to set quiet mode to {state}: {err}")
            raise

    async def force_update(self) -> None:
        """Force an immediate update of the device data."""
        await self.async_refresh()