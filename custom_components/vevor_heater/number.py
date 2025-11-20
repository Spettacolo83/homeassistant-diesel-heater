"""Number platform for Vevor Diesel Heater."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MAX_LEVEL,
    MAX_TEMP_CELSIUS,
    MIN_LEVEL,
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
