"""Button platform for Vevor Diesel Heater."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VevorHeaterCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vevor Heater buttons."""
    coordinator: VevorHeaterCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        VevorTimeSyncButton(coordinator),
    ])


class VevorTimeSyncButton(CoordinatorEntity[VevorHeaterCoordinator], ButtonEntity):
    """Button to sync heater time with Home Assistant.

    Many heaters have a clock that drifts over time. This button allows
    syncing the heater's internal clock with Home Assistant's time.
    """

    _attr_has_entity_name = True
    _attr_name = "Sync Time"
    _attr_icon = "mdi:clock-sync"

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_sync_time"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Diesel Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data.get("connected", False)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_sync_time()
