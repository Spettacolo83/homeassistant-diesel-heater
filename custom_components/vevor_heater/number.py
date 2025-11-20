"""Number platform for Vevor Diesel Heater."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_FUEL_CALIBRATION,
    CONF_TANK_CAPACITY,
    DEFAULT_FUEL_CALIBRATION,
    DEFAULT_TANK_CAPACITY,
    DOMAIN,
    MAX_FUEL_CALIBRATION,
    MAX_LEVEL,
    MAX_TANK_CAPACITY,
    MAX_TEMP_CELSIUS,
    MIN_FUEL_CALIBRATION,
    MIN_LEVEL,
    MIN_TANK_CAPACITY,
    MIN_TEMP_CELSIUS,
)
from .coordinator import VevorHeaterCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vevor Heater number entities."""
    coordinator: VevorHeaterCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    async_add_entities(
        [
            VevorHeaterLevelNumber(coordinator),
            VevorHeaterTemperatureNumber(coordinator),
            VevorTankCapacityNumber(coordinator),
            VevorFuelCalibrationNumber(coordinator),
        ]
    )


class VevorHeaterLevelNumber(CoordinatorEntity[VevorHeaterCoordinator], NumberEntity):
    """Vevor Heater level number entity."""

    _attr_has_entity_name = True
    _attr_name = "Level"
    _attr_icon = "mdi:gauge"
    _attr_native_min_value = MIN_LEVEL
    _attr_native_max_value = MAX_LEVEL
    _attr_native_step = 1

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_level"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Diesel Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }

    @property
    def native_value(self) -> float:
        """Return the current value."""
        return self.coordinator.data.get("set_level", MIN_LEVEL)

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self.coordinator.async_set_level(int(value))

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorHeaterTemperatureNumber(
    CoordinatorEntity[VevorHeaterCoordinator], NumberEntity
):
    """Vevor Heater temperature number entity."""

    _attr_has_entity_name = True
    _attr_name = "Target Temperature"
    _attr_icon = "mdi:thermometer"
    _attr_native_unit_of_measurement = "°C"
    _attr_native_min_value = MIN_TEMP_CELSIUS
    _attr_native_max_value = MAX_TEMP_CELSIUS
    _attr_native_step = 1

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_target_temp"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Diesel Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        temp = self.coordinator.data.get("set_temp")
        return temp if temp is not None else MIN_TEMP_CELSIUS

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self.coordinator.async_set_temperature(int(value))

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()

class VevorTankCapacityNumber(CoordinatorEntity[VevorHeaterCoordinator], NumberEntity):
    """Vevor Heater tank capacity number entity."""

    _attr_has_entity_name = True
    _attr_name = "Tank Capacity"
    _attr_icon = "mdi:fuel"
    _attr_native_unit_of_measurement = "L"
    _attr_native_min_value = MIN_TANK_CAPACITY
    _attr_native_max_value = MAX_TANK_CAPACITY
    _attr_native_step = 0.5
    _attr_entity_category = "config"

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_tank_capacity"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Diesel Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }

    @property
    def native_value(self) -> float:
        """Return the current value."""
        return self.coordinator.config_entry.options.get(
            CONF_TANK_CAPACITY,
            DEFAULT_TANK_CAPACITY
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        # Update config entry options
        new_options = {**self.coordinator.config_entry.options}
        new_options[CONF_TANK_CAPACITY] = value
        self.hass.config_entries.async_update_entry(
            self.coordinator.config_entry,
            options=new_options
        )
        # Update coordinator data
        self.coordinator.data["tank_capacity"] = value
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorFuelCalibrationNumber(
    CoordinatorEntity[VevorHeaterCoordinator], NumberEntity
):
    """Vevor Heater fuel calibration number entity."""

    _attr_has_entity_name = True
    _attr_name = "Fuel Calibration Factor"
    _attr_icon = "mdi:tune"
    _attr_native_min_value = MIN_FUEL_CALIBRATION
    _attr_native_max_value = MAX_FUEL_CALIBRATION
    _attr_native_step = 0.05
    _attr_entity_category = "config"

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_fuel_calibration"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Diesel Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }

    @property
    def native_value(self) -> float:
        """Return the current value."""
        return self.coordinator.config_entry.options.get(
            CONF_FUEL_CALIBRATION,
            DEFAULT_FUEL_CALIBRATION
        )

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        # Update config entry options
        new_options = {**self.coordinator.config_entry.options}
        new_options[CONF_FUEL_CALIBRATION] = value
        self.hass.config_entries.async_update_entry(
            self.coordinator.config_entry,
            options=new_options
        )
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
