"""Number platform for Vevor Diesel Heater."""
from __future__ import annotations

PARALLEL_UPDATES = 1

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfVolume

from . import VevorHeaterConfigEntry
from .const import (
    DOMAIN,
    MAX_HEATER_OFFSET,
    MAX_LEVEL,
    MAX_TEMP_CELSIUS,
    MIN_HEATER_OFFSET,
    MIN_LEVEL,
    MIN_TEMP_CELSIUS,
)
from .coordinator import VevorHeaterCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VevorHeaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Vevor Heater number entities.

    Entities are created conditionally based on the detected BLE protocol.
    Mode 0 (unknown) creates all entities as safe fallback.
    """
    coordinator = entry.runtime_data
    mode = coordinator.protocol_mode

    # Core number entities (all protocols)
    entities: list[NumberEntity] = [
        VevorHeaterLevelNumber(coordinator),
        VevorHeaterTemperatureNumber(coordinator),
        VevorTankCapacityNumber(coordinator),
        VevorCurrentFuelLevelNumber(coordinator),
    ]

    # Offset number (encrypted + CBFF protocols only)
    if mode in (0, 2, 4, 6):
        entities.append(VevorHeaterOffsetNumber(coordinator))

    async_add_entities(entities)


class VevorHeaterLevelNumber(CoordinatorEntity[VevorHeaterCoordinator], NumberEntity):
    """Vevor Heater level number entity.

    Beta.36: ALL protocols support levels 1-10 (@Xev, issue #46)
    The beta.33 assumption that Hcalory only supports 1-6 was wrong -
    decompiled APK data was incorrect. Confirmed by @smaj100: levels go 1-9, HH10.

    Beta.40: Level entity is UNAVAILABLE in Temperature mode (@Xev, issue #43)
    This prevents sending Level commands when heater is in Temperature mode,
    which would be ignored by the heater but cause coordinator state mismatch.
    """

    _attr_has_entity_name = True
    _attr_name = "Level"
    _attr_icon = "mdi:gauge"
    _attr_native_min_value = MIN_LEVEL
    _attr_native_max_value = MAX_LEVEL  # All protocols support 1-10 levels
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
    def available(self) -> bool:
        """Return True if entity is available.

        Level entity is only available when NOT in Temperature mode (mode 1).
        In Temperature mode, level commands are ignored by the heater.
        """
        # First check coordinator availability
        if not super().available:
            return False

        # Check if in Temperature mode (RUNNING_MODE_TEMPERATURE = 1)
        from .const import RUNNING_MODE_TEMPERATURE
        running_mode = self.coordinator.data.get("running_mode")
        if running_mode == RUNNING_MODE_TEMPERATURE:
            return False

        return True

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
    """Vevor Heater temperature number entity.

    Beta.37 fix for issue #43 (@Xev's analysis):
    - Use NumberDeviceClass.TEMPERATURE so HA handles unit conversions
    - Set native_unit_of_measurement dynamically based on heater's native unit
    - This fixes the 97°F bug where entity declared °C but received °F values

    Beta.40: Temperature entity is UNAVAILABLE in Level mode (@Xev, issue #43)
    This prevents sending Temperature commands when heater is in Level mode,
    which would be ignored by the heater but cause coordinator state mismatch.
    """

    _attr_has_entity_name = True
    _attr_name = "Target Temperature"
    _attr_icon = "mdi:thermometer"
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_step = 1

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the number entity.

        Set temperature unit and range statically at init based on heater's native unit.
        This approach is more reliable than dynamic properties (@Xev, issue #43).
        """
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_target_temp"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Diesel Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }

        # Set unit and range based on heater's native unit and protocol
        # Beta.41 fix: Per-protocol limits (Hcalory: 0-40°C, AAXX: 8-36°C)
        is_hcalory = coordinator.protocol_mode == 7
        if coordinator._heater_uses_fahrenheit:
            self._attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
            self._attr_native_min_value = 32   # 32°F = 0°C (Hcalory F)
            self._attr_native_max_value = 104  # 104°F = 40°C (Hcalory F)
        elif is_hcalory:
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_native_min_value = 0   # Hcalory Celsius: 0-40°C
            self._attr_native_max_value = 40
        else:
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_native_min_value = MIN_TEMP_CELSIUS   # AAXX: 8°C
            self._attr_native_max_value = MAX_TEMP_CELSIUS   # AAXX: 36°C

    @property
    def available(self) -> bool:
        """Return True if entity is available.

        Temperature entity is only available when NOT in Level mode (mode 2).
        In Level mode, temperature commands are ignored by the heater.
        """
        # First check coordinator availability
        if not super().available:
            return False

        # Check if in Level mode (RUNNING_MODE_LEVEL = 2)
        from .const import RUNNING_MODE_LEVEL
        running_mode = self.coordinator.data.get("running_mode")
        if running_mode == RUNNING_MODE_LEVEL:
            return False

        return True

    @property
    def native_value(self) -> float | None:
        """Return the current value in heater's native unit."""
        temp = self.coordinator.data.get("set_temp")
        if temp is not None:
            return temp
        # Fallback: return min value in correct unit
        return self._attr_native_min_value

    async def async_set_native_value(self, value: float) -> None:
        """Set new value (no conversion needed - already in native unit)."""
        await self.coordinator.async_set_temperature(value)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorHeaterOffsetNumber(CoordinatorEntity[VevorHeaterCoordinator], NumberEntity):
    """Vevor Heater temperature offset number entity.

    This allows manual control of the temperature offset sent to the heater
    via BLE command 20. The heater uses this offset to adjust its internal
    temperature sensor reading for auto-start/stop logic.

    Both positive and negative offsets (-10 to +10) are supported.
    """

    _attr_has_entity_name = True
    _attr_name = "Temperature Offset"
    _attr_icon = "mdi:thermometer-plus"
    _attr_native_unit_of_measurement = "°C"
    _attr_native_min_value = MIN_HEATER_OFFSET
    _attr_native_max_value = MAX_HEATER_OFFSET
    _attr_native_step = 1
    _attr_entity_category = None  # Show in main controls, not configuration

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_heater_offset"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Diesel Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Not available for Hcalory (mode 7) - no offset support.
        """
        if not self.coordinator.data.get("connected", False):
            return False
        # Hcalory doesn't support temperature offset commands (@Xev, issue #34)
        return self.coordinator.protocol_mode != 7

    @property
    def native_value(self) -> float:
        """Return the current value."""
        return self.coordinator.data.get("heater_offset", 0)

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self.coordinator.async_set_heater_offset(int(value))

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorTankCapacityNumber(CoordinatorEntity[VevorHeaterCoordinator], NumberEntity):
    """Tank capacity number entity for estimated fuel tracking.

    Allows the user to set their actual tank capacity in liters (1-100L).
    This is independent from the heater's BLE Tank Volume setting and is
    used locally to calculate the estimated fuel remaining.
    """

    _attr_has_entity_name = True
    _attr_name = "Tank Capacity"
    _attr_icon = "mdi:gas-station"
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_native_min_value = 1
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_entity_category = EntityCategory.CONFIG

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
    def native_value(self) -> float | None:
        """Return the current value."""
        return self.coordinator.data.get("tank_capacity")

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self.coordinator.async_set_tank_capacity(int(value))

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class VevorCurrentFuelLevelNumber(CoordinatorEntity[VevorHeaterCoordinator], NumberEntity):
    """Current fuel level number entity for manual fuel level input.

    Allows the user to manually set the current fuel level in the tank.
    Useful for partial refills (e.g., adding 5L without filling completely).

    When set, updates the internal fuel consumed counter:
    new_consumed = capacity - manual_level

    Feature requested by @Wheemer in issue #38.
    """

    _attr_has_entity_name = True
    _attr_name = "Current Fuel Level"
    _attr_icon = "mdi:fuel"
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_native_min_value = 0
    _attr_native_step = 0.1  # Allow 0.1L precision (@Wheemer, issue #38)

    def __init__(self, coordinator: VevorHeaterCoordinator) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_current_fuel_level"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.address)},
            "name": "Vevor Diesel Heater",
            "manufacturer": "Vevor",
            "model": "Diesel Heater",
        }

    @property
    def native_max_value(self) -> float:
        """Return the dynamic max value based on tank capacity."""
        capacity = self.coordinator.data.get("tank_capacity", 0)
        return max(1, capacity)  # Ensure at least 1L as max

    @property
    def native_value(self) -> float | None:
        """Return the current estimated fuel remaining."""
        # Beta.29 fix: Field name is fuel_remaining, not estimated_fuel_remaining (issue #38)
        estimated = self.coordinator.data.get("fuel_remaining")
        if estimated is not None:
            return estimated
        # If no fuel tracking data yet, assume tank is full
        capacity = self.coordinator.data.get("tank_capacity", 0)
        return capacity if capacity > 0 else None

    async def async_set_native_value(self, value: float) -> None:
        """Set new current fuel level (updates consumed counter)."""
        await self.coordinator.async_set_current_fuel_level(value)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


