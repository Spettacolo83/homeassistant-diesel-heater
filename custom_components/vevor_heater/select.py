"""Select platform for Vevor Diesel Heater."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    RUNNING_MODE_MANUAL,
    RUNNING_MODE_LEVEL,
    RUNNING_MODE_TEMPERATURE,
    RUNNING_MODE_NAMES,
)
from .coordinator import VevorHeaterCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vevor Heater select from config entry."""
    coordinator: VevorHeaterCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VevorHeaterModeSelect(coordinator)])


class VevorHeaterModeSelect(SelectEntity):
    """Select entity for Vevor Heater running mode."""

    _attr_has_entity_name = True
    _attr_name = "Running Mode"
    _attr_icon = "mdi:cog"
    _attr_options = [
        RUNNING_MODE_NAMES[RUNNING_MODE_MANUAL],
        RUNNING_MODE_NAMES[RUNNING_MODE_LEVEL],
        RUNNING_MODE_NAMES[RUNNING_MODE_TEMPERATURE],
    ]

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the select entity."""
        self.coordinator = coordinator
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }
        self._attr_unique_id = f"{coordinator.address}_running_mode"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data.get("connected", False)

    @property
    def current_option(self) -> str | None:
        """Return the current running mode."""
        mode = self.coordinator.data.get("running_mode")
        if mode is not None:
            return RUNNING_MODE_NAMES.get(mode)
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the running mode."""
        # Find the mode value for the selected option
        mode_value = None
        for mode, name in RUNNING_MODE_NAMES.items():
            if name == option:
                mode_value = mode
                break

        if mode_value is not None:
            _LOGGER.info("Changing running mode to: %s (value: %d)", option, mode_value)
            await self.coordinator.async_set_mode(mode_value)
        else:
            _LOGGER.error("Unknown running mode: %s", option)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
