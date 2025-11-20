"""Sensor platform for Vevor Diesel Heater."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfTemperature,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ERROR_NAMES,
    RUNNING_MODE_NAMES,
    RUNNING_STEP_NAMES,
)
from .coordinator import VevorHeaterCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vevor Heater sensors."""
    coordinator: VevorHeaterCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    async_add_entities(
        [
            VevorCaseTemperatureSensor(coordinator),
            VevorCabTemperatureSensor(coordinator),
            VevorSupplyVoltageSensor(coordinator),
            VevorRunningStepSensor(coordinator),
            VevorRunningModeSensor(coordinator),
            VevorSetLevelSensor(coordinator),
            VevorAltitudeSensor(coordinator),
            VevorErrorCodeSensor(coordinator),
            # Fuel consumption sensors
            VevorHourlyFuelConsumptionSensor(coordinator),
            VevorDailyFuelConsumedSensor(coordinator),
            VevorTotalFuelConsumedSensor(coordinator),
        ]
    )


class VevorSensorBase(CoordinatorEntity[VevorHeaterCoordinator], SensorEntity):
    """Base class for Vevor Heater sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: VevorHeaterCoordinator,
        key: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.address}_{key}"
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Diesel Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorCaseTemperatureSensor(VevorSensorBase):
    """Case temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "case_temp", "Case Temperature")

    @property
    def native_value(self) -> float | None:
        """Return the state."""
        return self.coordinator.data.get("case_temperature")


class VevorCabTemperatureSensor(VevorSensorBase):
    """Cab/interior temperature sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "cab_temp", "Interior Temperature")

    @property
    def native_value(self) -> float | None:
        """Return the state."""
        return self.coordinator.data.get("cab_temperature")


class VevorSupplyVoltageSensor(VevorSensorBase):
    """Supply voltage sensor."""

    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "supply_voltage", "Supply Voltage")

    @property
    def native_value(self) -> float | None:
        """Return the state."""
        return self.coordinator.data.get("supply_voltage")


class VevorRunningStepSensor(VevorSensorBase):
    """Running step sensor."""

    _attr_icon = "mdi:progress-clock"

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "running_step", "Running Step")

    @property
    def native_value(self) -> str | None:
        """Return the state."""
        step = self.coordinator.data.get("running_step")
        return RUNNING_STEP_NAMES.get(step, f"Unknown ({step})")


class VevorRunningModeSensor(VevorSensorBase):
    """Running mode sensor."""

    _attr_icon = "mdi:cog"

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "running_mode", "Running Mode")

    @property
    def native_value(self) -> str | None:
        """Return the state."""
        mode = self.coordinator.data.get("running_mode")
        return RUNNING_MODE_NAMES.get(mode, f"Unknown ({mode})")


class VevorSetLevelSensor(VevorSensorBase):
    """Set level sensor."""

    _attr_icon = "mdi:gauge"

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "set_level", "Set Level")

    @property
    def native_value(self) -> int | None:
        """Return the state."""
        return self.coordinator.data.get("set_level")


class VevorAltitudeSensor(VevorSensorBase):
    """Altitude sensor."""

    _attr_icon = "mdi:altimeter"
    _attr_native_unit_of_measurement = "m"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "altitude", "Altitude")

    @property
    def native_value(self) -> float | None:
        """Return the state."""
        return self.coordinator.data.get("altitude")


class VevorErrorCodeSensor(VevorSensorBase):
    """Error code sensor."""

    _attr_icon = "mdi:alert-circle"

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "error_code", "Error")

    @property
    def native_value(self) -> str | None:
        """Return the state."""
        error = self.coordinator.data.get("error_code", 0)
        return ERROR_NAMES.get(error, f"Unknown error ({error})")


# Fuel consumption sensors

class VevorHourlyFuelConsumptionSensor(VevorSensorBase):
    """Hourly fuel consumption sensor (instantaneous rate)."""

    _attr_device_class = SensorDeviceClass.VOLUME_FLOW_RATE
    _attr_native_unit_of_measurement = f"{UnitOfVolume.LITERS}/h"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:gauge"

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "hourly_fuel_consumption", "Hourly Fuel Consumption")

    @property
    def native_value(self) -> float | None:
        """Return the state."""
        return self.coordinator.data.get("hourly_fuel_consumption")


class VevorDailyFuelConsumedSensor(VevorSensorBase):
    """Daily fuel consumed sensor."""

    _attr_device_class = SensorDeviceClass.VOLUME
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:gas-station"

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "daily_fuel_consumed", "Daily Fuel Consumed")

    @property
    def native_value(self) -> float | None:
        """Return the state."""
        return self.coordinator.data.get("daily_fuel_consumed")


class VevorTotalFuelConsumedSensor(VevorSensorBase):
    """Total fuel consumed sensor."""

    _attr_device_class = SensorDeviceClass.VOLUME
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:gas-station"

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, "total_fuel_consumed", "Total Fuel Consumed")

    @property
    def native_value(self) -> float | None:
        """Return the state."""
        return self.coordinator.data.get("total_fuel_consumed")
