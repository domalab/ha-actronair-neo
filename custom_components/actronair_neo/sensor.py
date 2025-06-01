"""Support for ActronAir Neo sensors."""
from __future__ import annotations

import logging
from typing import Any, Final

from homeassistant.components.sensor import ( # type: ignore
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry # type: ignore
from homeassistant.const import UnitOfTemperature # type: ignore
from homeassistant.core import HomeAssistant # type: ignore
from homeassistant.helpers.entity_platform import AddEntitiesCallback # type: ignore
from homeassistant.helpers.typing import StateType # type: ignore
from homeassistant.helpers.update_coordinator import CoordinatorEntity # type: ignore

from .const import (
    DOMAIN,
    ATTR_BATTERY_LEVEL,
    ATTR_ZONE_NAME,
    ATTR_ZONE_TYPE,
    ATTR_SIGNAL_STRENGTH,
    ATTR_LAST_UPDATED,
)
from .coordinator import ActronDataCoordinator
from .base_entity import ActronEntityBase

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ActronAir Neo sensors from a config entry."""
    coordinator: ActronDataCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        ActronMainSensor(coordinator),
        # Enhanced diagnostic sensors
        ActronSystemDiagnosticSensor(coordinator),
        ActronConnectivitySensor(coordinator),
        ActronPerformanceSensor(coordinator),
    ]

    # Add zone sensors
    for zone_id, zone_data in coordinator.data['zones'].items():
        _LOGGER.debug("Adding zone sensor for %s: %s", zone_id, zone_data)
        entities.append(ActronZoneSensor(coordinator, zone_id))

        # Add zone analytics sensors if zone analytics is enabled
        if coordinator.enable_zone_analytics:
            entities.append(ActronZoneRuntimeSensor(coordinator, zone_id))
            entities.append(ActronZoneEfficiencySensor(coordinator, zone_id))

    async_add_entities(entities)

class ActronSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for ActronAir Neo sensors."""

    _ATTR_HAS_ENTITY_NAME: Final = True

    def __init__(
        self,
        coordinator: ActronDataCoordinator,
        unique_id: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.device_id}_{unique_id}"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def device_info(self):
        """Return device information about this entity."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.device_id)},
            "name": "ActronAir Neo",
            "manufacturer": "ActronAir",
            "model": self.coordinator.data["main"]["model"],
            "sw_version": self.coordinator.data["main"]["firmware_version"],
        }

class ActronMainSensor(ActronEntityBase, SensorEntity):
    """Main temperature sensor."""

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the main temperature sensor."""
        super().__init__(coordinator, "sensor", "Avg. Inside Temp")
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        return self.coordinator.data["main"]["indoor_temp"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        return {
            "Inside Humidity": self.coordinator.data["main"]["indoor_humidity"],
        }

class ActronZoneSensor(ActronEntityBase, SensorEntity):
    """Zone temperature sensor."""

    def __init__(self, coordinator: ActronDataCoordinator, zone_id: str) -> None:
        """Initialize the zone sensor."""
        zone_name = coordinator.data['zones'][zone_id]['name']
        super().__init__(coordinator, "sensor", f"Zone {zone_name}")
        self.zone_id = zone_id
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT

    def _format_signal_strength(self, signal: int | float | None) -> str:
        """Format signal strength with quality rating."""
        if not isinstance(signal, (int, float)):
            return "Unknown"

        if signal > -50:
            quality = "Excellent"
        elif signal > -60:
            quality = "Good"
        elif signal > -70:
            quality = "Fair"
        else:
            quality = "Poor"

        return f"{signal} dBm ({quality})"

    @property
    def native_value(self) -> StateType:
        """Return the temperature of the zone."""
        try:
            return self.coordinator.data['zones'][self.zone_id]['temp']
        except KeyError as err:
            _LOGGER.error("Failed to get temperature for zone %s: %s", self.zone_id, err)
            return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            super().available
            and self.zone_id in self.coordinator.data['zones']
            and self.coordinator.data['zones'][self.zone_id].get('temp') is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return zone specific attributes including humidity and battery level."""
        try:
            zone_data = self.coordinator.data['zones'][self.zone_id]
            peripheral_data = self.coordinator.get_zone_peripheral(self.zone_id)

            attributes = {
                ATTR_ZONE_NAME: zone_data['name'],
                "humidity": zone_data['humidity'],
                "enabled": zone_data['is_enabled'],
            }

            # Add battery level from zone data if available (for wireless sensors)
            if zone_data.get('battery_level') is not None:
                attributes[ATTR_BATTERY_LEVEL] = zone_data['battery_level']
                _LOGGER.debug("Zone %s has battery level: %s%%", self.zone_id, zone_data['battery_level'])

            # Add peripheral type information if available
            if zone_data.get('peripheral_type') is not None:
                attributes[ATTR_ZONE_TYPE] = zone_data['peripheral_type']

            # Add connection information for wireless sensors
            if zone_data.get('last_connection') is not None:
                attributes[ATTR_LAST_UPDATED] = zone_data['last_connection']
            if zone_data.get('connection_state') is not None:
                attributes["connection_state"] = zone_data['connection_state']

            # Add signal strength if available (with user-friendly formatting)
            if zone_data.get('signal_strength') is not None:
                signal = zone_data['signal_strength']
                attributes["signal_strength"] = self._format_signal_strength(signal)

            # Fallback to peripheral data for additional information if available
            if peripheral_data:
                # Only use peripheral battery data if zone data doesn't have it
                if ATTR_BATTERY_LEVEL not in attributes and "RemainingBatteryCapacity_pc" in peripheral_data:
                    attributes[ATTR_BATTERY_LEVEL] = peripheral_data["RemainingBatteryCapacity_pc"]
                    _LOGGER.debug("Zone %s using peripheral battery level: %s%%", self.zone_id, peripheral_data["RemainingBatteryCapacity_pc"])

                # Use peripheral data for additional attributes if zone data doesn't have them
                if ATTR_ZONE_TYPE not in attributes and "DeviceType" in peripheral_data:
                    attributes[ATTR_ZONE_TYPE] = peripheral_data["DeviceType"]
                if "signal_strength" not in attributes and "Signal_of3" in peripheral_data and peripheral_data["Signal_of3"] != "NA":
                    try:
                        signal = int(peripheral_data["Signal_of3"])
                        attributes["signal_strength"] = self._format_signal_strength(signal)
                    except (ValueError, TypeError):
                        attributes["signal_strength"] = peripheral_data["Signal_of3"]
                if ATTR_LAST_UPDATED not in attributes and "LastConnectionTime" in peripheral_data:
                    attributes[ATTR_LAST_UPDATED] = peripheral_data["LastConnectionTime"]
                if "connection_state" not in attributes and "ConnectionState" in peripheral_data:
                    attributes["connection_state"] = peripheral_data["ConnectionState"]

            _LOGGER.debug("Zone %s attributes: %s", self.zone_id, attributes)
            return attributes

        except KeyError as ex:
            _LOGGER.error("Key error getting attributes for zone %s: %s", self.zone_id, str(ex))
            return {}
        except TypeError as ex:
            _LOGGER.error("Type error getting attributes for zone %s: %s", self.zone_id, str(ex))
            return {}
        except ValueError as ex:
            _LOGGER.error("Value error getting attributes for zone %s: %s", self.zone_id, str(ex))
            return {}


class ActronZoneRuntimeSensor(ActronSensorBase):
    """Zone runtime sensor for analytics."""

    def __init__(self, coordinator: ActronDataCoordinator, zone_id: str) -> None:
        """Initialize the zone runtime sensor."""
        zone_data = coordinator.data['zones'][zone_id]
        zone_name = zone_data['name']
        super().__init__(
            coordinator,
            f"sensor_zone_{zone_name.lower().replace(' ', '_')}_runtime",
            f"{zone_name} Runtime"
        )
        self.zone_id = zone_id
        self._attr_device_class = SensorDeviceClass.DURATION
        self._attr_native_unit_of_measurement = "h"
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = "mdi:timer-outline"

    @property
    def native_value(self) -> float | None:
        """Return the zone runtime in hours."""
        if not self.coordinator.zone_analytics_manager:
            return None
        stats = self.coordinator.zone_analytics_manager.get_zone_stats(self.zone_id)
        return round(stats.total_runtime_hours, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        if not self.coordinator.zone_analytics_manager:
            return None
        stats = self.coordinator.zone_analytics_manager.get_zone_stats(self.zone_id)
        from datetime import datetime
        return {
            "daily_average_hours": round(stats.get_daily_runtime(datetime.now()), 2),
            "on_off_cycles": stats.on_off_cycles,
            "setpoint_changes": stats.setpoint_changes,
        }


class ActronZoneEfficiencySensor(ActronSensorBase):
    """Zone efficiency sensor for analytics."""

    def __init__(self, coordinator: ActronDataCoordinator, zone_id: str) -> None:
        """Initialize the zone efficiency sensor."""
        zone_data = coordinator.data['zones'][zone_id]
        zone_name = zone_data['name']
        super().__init__(
            coordinator,
            f"sensor_zone_{zone_name.lower().replace(' ', '_')}_efficiency",
            f"{zone_name} Efficiency"
        )
        self.zone_id = zone_id
        self._attr_native_unit_of_measurement = "%"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:gauge"

    @property
    def native_value(self) -> float | None:
        """Return the zone efficiency score."""
        if not self.coordinator.zone_analytics_manager:
            return None
        stats = self.coordinator.zone_analytics_manager.get_zone_stats(self.zone_id)
        return round(stats.efficiency_score, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        if not self.coordinator.zone_analytics_manager:
            return None

        report = self.coordinator.zone_analytics_manager.get_zone_performance_report(self.zone_id)
        if report.get("status") != "ok":
            return None

        return {
            "performance_rating": report.get("performance_rating"),
            "temperature_trend": report.get("temperature_trend", {}).get("status"),
            "recent_daily_average": round(report.get("recent_daily_average_hours", 0), 2),
        }


class ActronSystemDiagnosticSensor(ActronEntityBase, SensorEntity):
    """Enhanced system diagnostic sensor with live data and user-friendly formatting."""

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the system diagnostic sensor."""
        super().__init__(
            coordinator,
            "sensor",
            "System Diagnostics",
            is_diagnostic=True
        )
        self._attr_icon = "mdi:information-outline"
        self._attr_native_unit_of_measurement = None
        self._attr_device_class = None
        self._attr_state_class = None

    @property
    def native_value(self) -> str:
        """Return the overall system status."""
        try:
            main_data = self.coordinator.data["main"]
            if main_data.get("is_on", False):
                mode = main_data.get("mode", "Unknown").title()
                return f"Running ({mode})"
            else:
                return "Standby"
        except (KeyError, TypeError):
            return "Unknown"

    def _format_uptime(self, seconds: int) -> str:
        """Format uptime to human readable string."""
        if not isinstance(seconds, (int, float)) or seconds < 0:
            return "Unknown"

        days, remainder = divmod(int(seconds), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)

        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"

    def _format_temperature(self, value: Any) -> str:
        """Format temperature value."""
        if value is None or value == "Unknown":
            return "Unknown"
        try:
            return f"{float(value):.1f}°C"
        except (ValueError, TypeError):
            return str(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return enhanced diagnostic attributes with live data."""
        try:
            main_data = self.coordinator.data["main"]
            raw_data = self.coordinator.data.get("raw_data", {})
            last_known_state = raw_data.get("lastKnownState", {})

            # System status from live data
            system_status = last_known_state.get("SystemStatus_Local", {})
            live_aircon = last_known_state.get("LiveAircon", {})

            return {
                # System Information
                "model": main_data.get("model", "Unknown"),
                "firmware_version": main_data.get("firmware_version", "Unknown"),
                "serial_number": main_data.get("serial_number", "Unknown"),

                # Live System Status
                "system_uptime": self._format_uptime(system_status.get("Uptime_s", 0)),
                "operating_mode": main_data.get("mode", "Unknown").title(),
                "fan_mode": main_data.get("fan_mode", "Unknown").title(),
                "quiet_mode_active": main_data.get("quiet_mode", False),
                "away_mode_active": main_data.get("away_mode", False),

                # Live Performance Data
                "compressor_running": live_aircon.get("SystemOn", False),
                "compressor_capacity": f"{live_aircon.get('CompressorCapacity', 0)}%",
                "fan_running": live_aircon.get("AmRunningFan", False),
                "fan_speed": f"{live_aircon.get('FanRPM', 0)} RPM",

                # Live Temperature Readings
                "indoor_temperature": self._format_temperature(main_data.get("indoor_temp")),
                "indoor_humidity": f"{main_data.get('indoor_humidity', 0):.1f}%",
                "coil_inlet_temperature": self._format_temperature(live_aircon.get("CoilInlet")),
                "ambient_temperature": self._format_temperature(
                    system_status.get("SensorInputs", {}).get("SHTC1", {}).get("Temperature_oC")
                ),

                # System Health
                "filter_status": "Needs Cleaning" if main_data.get("filter_clean_required") else "Clean",
                "defrosting_active": main_data.get("defrosting", False),
                "error_code": live_aircon.get("ErrCode", 0),

                # Last Update Information
                "last_api_update": raw_data.get("lastStatusUpdate", "Unknown"),
                "data_freshness": "Live" if self.coordinator.last_update_success else "Stale",
            }

        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.error("Error getting system diagnostic attributes: %s", err)
            return {
                "error": "Failed to retrieve system diagnostics",
                "error_details": str(err)
            }


class ActronConnectivitySensor(ActronEntityBase, SensorEntity):
    """Enhanced connectivity sensor with signal quality and connection health."""

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the connectivity sensor."""
        super().__init__(
            coordinator,
            "sensor",
            "Connectivity Status",
            is_diagnostic=True
        )
        self._attr_icon = "mdi:wifi"
        self._attr_native_unit_of_measurement = None
        self._attr_device_class = None
        self._attr_state_class = None

    @property
    def native_value(self) -> str:
        """Return the connectivity status."""
        try:
            raw_data = self.coordinator.data.get("raw_data", {})
            last_known_state = raw_data.get("lastKnownState", {})

            cloud_status = last_known_state.get("Cloud", {})
            connection_state = cloud_status.get("ConnectionState", "Unknown")

            if connection_state == "Connected":
                return "Online"
            else:
                return f"Offline ({connection_state})"

        except (KeyError, TypeError):
            return "Unknown"

    def _format_wifi_signal(self, signal: int | float | None) -> dict[str, str]:
        """Format WiFi signal strength with quality rating."""
        if not isinstance(signal, (int, float)):
            return {"strength": "Unknown", "quality": "Unknown", "bars": "0/4"}

        if signal > -50:
            quality = "Excellent"
            bars = "4/4"
        elif signal > -60:
            quality = "Good"
            bars = "3/4"
        elif signal > -70:
            quality = "Fair"
            bars = "2/4"
        else:
            quality = "Poor"
            bars = "1/4"

        return {
            "strength": f"{signal} dBm",
            "quality": quality,
            "bars": bars
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return enhanced connectivity attributes."""
        try:
            raw_data = self.coordinator.data.get("raw_data", {})
            last_known_state = raw_data.get("lastKnownState", {})

            system_status = last_known_state.get("SystemStatus_Local", {})
            cloud_status = last_known_state.get("Cloud", {})
            wifi_info = system_status.get("WiFi", {})

            # WiFi signal analysis
            wifi_signal = self._format_wifi_signal(system_status.get("WifiStrength_of3"))

            return {
                # Connection Status
                "cloud_connection": cloud_status.get("ConnectionState", "Unknown"),
                "connection_uptime": self._format_uptime(
                    cloud_status.get("Connection", {}).get("UpTime", {}).get("CurrentSession_s", 0)
                ),

                # WiFi Information
                "wifi_network": wifi_info.get("ApSSID", "Unknown"),
                "wifi_signal_strength": wifi_signal["strength"],
                "wifi_signal_quality": wifi_signal["quality"],
                "wifi_signal_bars": wifi_signal["bars"],
                "wifi_channel": wifi_info.get("RFChannel", "Unknown"),
                "wifi_firmware": wifi_info.get("FirmwareVersion", "Unknown"),

                # Connection Statistics
                "packets_sent": cloud_status.get("SentPackets", 0),
                "packets_received": cloud_status.get("ReceivedPackets", 0),
                "failed_packets": cloud_status.get("FailedSentPackets", 0),
                "connection_sessions": cloud_status.get("Connection", {}).get("SessionCount", {}).get("SinceLastMCUReset", 0),

                # Error Monitoring
                "wifi_hardware_errors": wifi_info.get("HardwareErrorCount", 0),
                "dns_failures": cloud_status.get("Connection", {}).get("ErrorCount", {}).get("DNSFailures", 0),
                "socket_errors": cloud_status.get("Connection", {}).get("ErrorCount", {}).get("AbortedSockets", 0),

                # Data Freshness
                "last_contact": raw_data.get("timeSinceLastContact", "Unknown"),
                "last_status_update": raw_data.get("lastStatusUpdate", "Unknown"),
                "device_online": raw_data.get("isOnline", False),
            }

        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.error("Error getting connectivity attributes: %s", err)
            return {
                "error": "Failed to retrieve connectivity data",
                "error_details": str(err)
            }

    def _format_uptime(self, seconds: int) -> str:
        """Format uptime to human readable string."""
        if not isinstance(seconds, (int, float)) or seconds < 0:
            return "Unknown"

        days, remainder = divmod(int(seconds), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)

        if days > 0:
            return f"{days}d {hours}h"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"


class ActronPerformanceSensor(ActronEntityBase, SensorEntity):
    """Enhanced performance sensor with real-time operational metrics."""

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the performance sensor."""
        super().__init__(
            coordinator,
            "sensor",
            "Performance Metrics",
            is_diagnostic=True
        )
        self._attr_icon = "mdi:speedometer"
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_class = None
        self._attr_state_class = None

    @property
    def native_value(self) -> float | None:
        """Return the overall system efficiency percentage."""
        try:
            raw_data = self.coordinator.data.get("raw_data", {})
            last_known_state = raw_data.get("lastKnownState", {})
            live_aircon = last_known_state.get("LiveAircon", {})

            # Calculate efficiency based on compressor capacity and system status
            if live_aircon.get("SystemOn", False):
                capacity = live_aircon.get("CompressorCapacity", 0)
                return float(capacity) if capacity is not None else 0.0
            else:
                return 0.0

        except (KeyError, TypeError, ValueError):
            return None

    def _format_temperature(self, value: Any) -> str:
        """Format temperature value."""
        if value is None or value == "Unknown":
            return "Unknown"
        try:
            return f"{float(value):.1f}°C"
        except (ValueError, TypeError):
            return str(value)

    def _format_power(self, value: Any) -> str:
        """Format power value."""
        if value is None or value == "Unknown":
            return "Unknown"
        try:
            power = float(value)
            if power >= 1000:
                return f"{power/1000:.1f} kW"
            else:
                return f"{power:.0f} W"
        except (ValueError, TypeError):
            return str(value)

    def _get_operational_status(self, live_aircon: dict) -> str:
        """Determine operational status from live data."""
        if not live_aircon.get("SystemOn", False):
            return "Standby"

        compressor_on = live_aircon.get("CompressorMode", "OFF") != "OFF"
        fan_running = live_aircon.get("AmRunningFan", False)

        if compressor_on and fan_running:
            return "Active Cooling/Heating"
        elif fan_running:
            return "Fan Only"
        elif compressor_on:
            return "Compressor Only"
        else:
            return "System On (Idle)"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return enhanced performance attributes with live operational data."""
        try:
            main_data = self.coordinator.data["main"]
            raw_data = self.coordinator.data.get("raw_data", {})
            last_known_state = raw_data.get("lastKnownState", {})

            live_aircon = last_known_state.get("LiveAircon", {})
            outdoor_unit = live_aircon.get("OutdoorUnit", {})
            system_status = last_known_state.get("SystemStatus_Local", {})

            return {
                # Operational Status
                "operational_status": self._get_operational_status(live_aircon),
                "system_running": live_aircon.get("SystemOn", False),
                "defrosting": main_data.get("defrosting", False),

                # Compressor Performance
                "compressor_mode": live_aircon.get("CompressorMode", "Unknown"),
                "compressor_capacity": f"{live_aircon.get('CompressorCapacity', 0)}%",
                "compressor_power": self._format_power(outdoor_unit.get("CompPower", 0)),
                "compressor_speed": f"{outdoor_unit.get('CompSpeed', 0)} RPM",
                "compressor_running": outdoor_unit.get("CompressorOn", False),

                # Fan Performance
                "fan_running": live_aircon.get("AmRunningFan", False),
                "fan_speed": f"{live_aircon.get('FanRPM', 0)} RPM",
                "fan_power": f"{live_aircon.get('FanPWM', 0)}%",

                # Temperature Control
                "target_temperature": self._format_temperature(live_aircon.get("CompressorChasingTemperature")),
                "current_temperature": self._format_temperature(live_aircon.get("CompressorLiveTemperature")),
                "coil_inlet_temp": self._format_temperature(live_aircon.get("CoilInlet")),
                "outdoor_coil_temp": self._format_temperature(outdoor_unit.get("CoilTemp")),

                # System Efficiency Metrics
                "indoor_temp": self._format_temperature(main_data.get("indoor_temp")),
                "indoor_humidity": f"{main_data.get('indoor_humidity', 0):.1f}%",
                "ambient_temp": self._format_temperature(
                    system_status.get("SensorInputs", {}).get("SHTC1", {}).get("Temperature_oC")
                ),

                # Valve and Control
                "reverse_valve_position": outdoor_unit.get("ReverseValvePosition", "Unknown"),
                "defrost_mode": outdoor_unit.get("DefrostMode", 0),
                "drm_active": outdoor_unit.get("DRM", False),

                # Error Monitoring
                "error_code": live_aircon.get("ErrCode", 0),
                "outdoor_errors": {
                    "error_1": outdoor_unit.get("ErrCode_1", 0),
                    "error_2": outdoor_unit.get("ErrCode_2", 0),
                    "error_3": outdoor_unit.get("ErrCode_3", 0),
                    "error_4": outdoor_unit.get("ErrCode_4", 0),
                    "error_5": outdoor_unit.get("ErrCode_5", 0),
                },

                # Zone Performance Summary
                "active_zones": sum(1 for zone in self.coordinator.data.get("zones", {}).values()
                                  if zone.get("is_enabled", False)),
                "total_zones": len(self.coordinator.data.get("zones", {})),

                # Power Management
                "quiet_mode": main_data.get("quiet_mode", False),
                "away_mode": main_data.get("away_mode", False),
                "continuous_fan": main_data.get("fan_continuous", False),
            }

        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.error("Error getting performance attributes: %s", err)
            return {
                "error": "Failed to retrieve performance data",
                "error_details": str(err)
            }

