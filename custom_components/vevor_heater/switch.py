"""Switch platform for Vevor Diesel Heater."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, RUNNING_STATE_ON
from .coordinator import VevorHeaterCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vevor Heater switch."""
    coordinator: VevorHeaterCoordinator = hass.data[DOMAIN][entry.entry_id]
    
    async_add_entities([VevorHeaterPowerSwitch(coordinator)])


class VevorHeaterPowerSwitch(CoordinatorEntity[VevorHeaterCoordinator], SwitchEntity):
    """Vevor Heater power switch."""

    _attr_has_entity_name = True
    _attr_name = "Power"
    _attr_icon = "mdi:power"

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_power"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Diesel Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }

    @property
    def is_on(self) -> bool:
        """Return true if heater is on."""
        return self.coordinator.data.get("running_state") == RUNNING_STATE_ON

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the heater on."""
        await self.coordinator.async_turn_on()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the heater off."""
        await self.coordinator.async_turn_off()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
