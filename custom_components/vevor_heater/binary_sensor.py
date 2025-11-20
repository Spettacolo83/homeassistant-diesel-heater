"""Binary sensor platform for Vevor Diesel Heater."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ERROR_NONE, LOW_FUEL_THRESHOLD, RUNNING_STATE_ON
from .coordinator import VevorHeaterCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vevor Heater binary sensors."""
    coordinator: VevorHeaterCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    async_add_entities(
        [
            VevorHeaterActiveSensor(coordinator),
            VevorHeaterProblemSensor(coordinator),
            VevorHeaterConnectedSensor(coordinator),
            VevorLowFuelSensor(coordinator),
        ]
    )


class VevorHeaterActiveSensor(
    CoordinatorEntity[VevorHeaterCoordinator], BinarySensorEntity
):
    """Vevor Heater active binary sensor."""

    _attr_has_entity_name = True
    _attr_name = "Active"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_active"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Diesel Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }

    @property
    def is_on(self) -> bool:
        """Return true if heater is running."""
        return self.coordinator.data.get("running_state") == RUNNING_STATE_ON

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorHeaterProblemSensor(
    CoordinatorEntity[VevorHeaterCoordinator], BinarySensorEntity
):
    """Vevor Heater problem binary sensor."""

    _attr_has_entity_name = True
    _attr_name = "Problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_problem"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Diesel Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }

    @property
    def is_on(self) -> bool:
        """Return true if there's a problem."""
        return self.coordinator.data.get("error_code", 0) != ERROR_NONE

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorHeaterConnectedSensor(
    CoordinatorEntity[VevorHeaterCoordinator], BinarySensorEntity
):
    """Vevor Heater connected binary sensor."""

    _attr_has_entity_name = True
    _attr_name = "Connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_registry_enabled_default = False  # Disabled by default

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_connected"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Diesel Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }

    @property
    def is_on(self) -> bool:
        """Return true if connected."""
        return self.coordinator.data.get("connected", False)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorLowFuelSensor(
    CoordinatorEntity[VevorHeaterCoordinator], BinarySensorEntity
):
    """Vevor Heater low fuel warning binary sensor."""

    _attr_has_entity_name = True
    _attr_name = "Low Fuel"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:fuel-alert"

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_low_fuel"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Diesel Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }

    @property
    def is_on(self) -> bool:
        """Return true if fuel level is low (<20%)."""
        fuel_level = self.coordinator.data.get("fuel_level_percent", 100)
        return fuel_level < (LOW_FUEL_THRESHOLD * 100)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
