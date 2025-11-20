"""Climate platform for Vevor Diesel Heater."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import VevorHeaterCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vevor Heater climate from config entry."""
    coordinator: VevorHeaterCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VevorHeaterClimate(coordinator)])


class VevorHeaterClimate(ClimateEntity):
    """Climate entity for Vevor Heater."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_min_temp = 8
    _attr_max_temp = 36
    _attr_target_temperature_step = 1

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the climate entity."""
        self.coordinator = coordinator
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }
        self._attr_unique_id = f"{coordinator.address}_climate"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.data.get("connected", False)

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature (interior/cabin temperature)."""
        return self.coordinator.data.get("cab_temperature")

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self.coordinator.data.get("set_temp")

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        running_state = self.coordinator.data.get("running_state", 0)
        if running_state == 1:
            return HVACMode.HEAT
        return HVACMode.OFF

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        temperature = int(temperature)
        _LOGGER.info("Setting target temperature to %d°C", temperature)
        await self.coordinator.async_set_temperature(temperature)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode."""
        if hvac_mode == HVACMode.HEAT:
            _LOGGER.info("Turning heater ON")
            await self.coordinator.async_turn_on()
        elif hvac_mode == HVACMode.OFF:
            _LOGGER.info("Turning heater OFF")
            await self.coordinator.async_turn_off()

    async def async_turn_on(self) -> None:
        """Turn on the heater."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Turn off the heater."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
