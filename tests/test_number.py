"""Tests for Diesel Heater number platform."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

# Import stubs first
from . import conftest  # noqa: F401

from custom_components.diesel_heater.number import (
    VevorHeaterLevelNumber,
    VevorHeaterTemperatureNumber,
    VevorHeaterOffsetNumber,
    VevorTankCapacityNumber,
    VevorBurnoffDurationNumber,
    VevorBurnoffAfterCyclesNumber,
    VevorBurnoffAfterHoursNumber,
    VevorCurrentFuelLevelNumber,
    async_setup_entry,
)
from custom_components.diesel_heater.const import (
    RUNNING_MODE_LEVEL,
    RUNNING_MODE_TEMPERATURE,
)


def create_mock_coordinator(protocol_mode: int = 0) -> MagicMock:
    """Create a mock coordinator for number testing."""
    coordinator = MagicMock()
    coordinator._address = "AA:BB:CC:DD:EE:FF"
    coordinator.address = "AA:BB:CC:DD:EE:FF"
    coordinator._heater_id = "EE:FF"
    coordinator.last_update_success = True
    coordinator.send_command = AsyncMock(return_value=True)
    coordinator.async_set_level = AsyncMock()
    coordinator.async_set_temperature = AsyncMock()
    coordinator.async_set_heater_offset = AsyncMock()
    coordinator.async_set_tank_capacity = AsyncMock()
    coordinator.async_set_burnoff_duration = AsyncMock()
    coordinator.async_set_burnoff_after_cycles = AsyncMock()
    coordinator.async_set_burnoff_after_hours = AsyncMock()
    coordinator.burnoff_duration_minutes = 10
    coordinator.burnoff_after_cycles = 0
    coordinator.burnoff_after_hours = 0
    coordinator.burnoff_active = False
    coordinator.protocol_mode = protocol_mode
    coordinator._heater_uses_fahrenheit = False
    coordinator.has_cronus_fuel_estimate = False
    coordinator.data = {
        "connected": True,
        "set_level": 5,
        "set_temp": 22,
        "heater_offset": 0,
        "tank_capacity": 5,
    }
    return coordinator


# ---------------------------------------------------------------------------
# Level number tests
# ---------------------------------------------------------------------------

class TestVevorHeaterLevelNumber:
    """Tests for Vevor heater level number entity."""

    def test_native_value(self):
        """Test native_value returns current level."""
        coordinator = create_mock_coordinator()
        coordinator.data["set_level"] = 7
        number = VevorHeaterLevelNumber(coordinator)

        assert number.native_value == 7

    def test_min_value_attr(self):
        """Test _attr_native_min_value is 1."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterLevelNumber(coordinator)

        assert number._attr_native_min_value == 1

    def test_max_value_attr(self):
        """Test _attr_native_max_value is 10."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterLevelNumber(coordinator)

        assert number._attr_native_max_value == 10

    def test_cronus_air_level_maximum_is_four(self):
        """ThermoConnect exposes air level 1-4 only in ventilation mode."""
        coordinator = create_mock_coordinator(protocol_mode=9)
        number = VevorHeaterLevelNumber(coordinator)

        assert number._attr_native_max_value == 4

    def test_step_attr(self):
        """Test _attr_native_step is 1."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterLevelNumber(coordinator)

        assert number._attr_native_step == 1

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterLevelNumber(coordinator)

        assert "_level" in number.unique_id


# ---------------------------------------------------------------------------
# Offset number tests
# ---------------------------------------------------------------------------

class TestVevorHeaterOffsetNumber:
    """Tests for Vevor heater offset number entity."""

    def test_native_value(self):
        """Test native_value returns current offset."""
        coordinator = create_mock_coordinator()
        coordinator.data["heater_offset"] = 2
        number = VevorHeaterOffsetNumber(coordinator)

        assert number.native_value == 2

    def test_native_value_negative(self):
        """Test native_value with negative offset."""
        coordinator = create_mock_coordinator()
        coordinator.data["heater_offset"] = -3
        number = VevorHeaterOffsetNumber(coordinator)

        assert number.native_value == -3

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterOffsetNumber(coordinator)

        assert "_offset" in number.unique_id


# ---------------------------------------------------------------------------
# Tank capacity number tests
# ---------------------------------------------------------------------------

class TestVevorTankCapacityNumber:
    """Tests for Vevor tank capacity number entity."""

    def test_native_value(self):
        """Test native_value returns current tank capacity."""
        coordinator = create_mock_coordinator()
        coordinator.data["tank_capacity"] = 10
        number = VevorTankCapacityNumber(coordinator)

        assert number.native_value == 10

    def test_current_fuel_level_max_handles_none_capacity(self):
        """A missing capacity must not reach max() as None."""
        coordinator = create_mock_coordinator()
        coordinator.data["tank_capacity"] = None
        from custom_components.diesel_heater.number import VevorCurrentFuelLevelNumber

        number = VevorCurrentFuelLevelNumber(coordinator)
        assert number.native_max_value == 1

    def test_current_fuel_level_value_handles_none_capacity(self):
        """A missing capacity returns no estimated fuel value."""
        coordinator = create_mock_coordinator()
        coordinator.data["tank_capacity"] = None
        from custom_components.diesel_heater.number import VevorCurrentFuelLevelNumber

        number = VevorCurrentFuelLevelNumber(coordinator)
        assert number.native_value is None

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        number = VevorTankCapacityNumber(coordinator)

        assert "_tank" in number.unique_id or "_capacity" in number.unique_id


# ---------------------------------------------------------------------------
# Availability tests
# ---------------------------------------------------------------------------

class TestNumberAvailability:
    """Tests for number availability."""

    def test_available_when_connected(self):
        """Test number is available when connected."""
        coordinator = create_mock_coordinator()
        coordinator.last_update_success = True
        number = VevorHeaterLevelNumber(coordinator)

        assert number.available is True

    def test_available_property_exists(self):
        """Test available property is accessible."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterLevelNumber(coordinator)

        # Just verify property is accessible
        _ = number.available

    def test_level_unavailable_during_burnoff(self):
        """Level is a burn-off snapshot field and must be locked."""
        coordinator = create_mock_coordinator()
        coordinator.data["connected"] = True
        coordinator.data["running_mode"] = RUNNING_MODE_LEVEL
        coordinator.burnoff_active = True
        number = VevorHeaterLevelNumber(coordinator)

        assert number.available is False

    def test_level_available_when_burnoff_inactive(self):
        """Level stays available in Level mode when burn-off is not running."""
        coordinator = create_mock_coordinator()
        coordinator.data["connected"] = True
        coordinator.data["running_mode"] = RUNNING_MODE_LEVEL
        coordinator.burnoff_active = False
        number = VevorHeaterLevelNumber(coordinator)

        assert number.available is True

    def test_temperature_unavailable_during_burnoff(self):
        """Target temperature is a burn-off snapshot field and must be locked."""
        coordinator = create_mock_coordinator()
        coordinator.data["connected"] = True
        coordinator.data["running_mode"] = RUNNING_MODE_TEMPERATURE
        coordinator.burnoff_active = True
        number = VevorHeaterTemperatureNumber(coordinator)

        assert number.available is False

    def test_temperature_available_when_burnoff_inactive(self):
        """Target temperature stays available in Temperature mode when idle."""
        coordinator = create_mock_coordinator()
        coordinator.data["connected"] = True
        coordinator.data["running_mode"] = RUNNING_MODE_TEMPERATURE
        coordinator.burnoff_active = False
        number = VevorHeaterTemperatureNumber(coordinator)

        assert number.available is True


# ---------------------------------------------------------------------------
# Async setup entry tests
# ---------------------------------------------------------------------------

class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_creates_core_entities(self):
        """Test async_setup_entry creates core number entities."""
        coordinator = create_mock_coordinator(protocol_mode=0)

        # Create mock entry with runtime_data
        entry = MagicMock()
        entry.runtime_data = coordinator

        # Create mock async_add_entities
        async_add_entities = MagicMock()

        # Create mock hass
        hass = MagicMock()

        await async_setup_entry(hass, entry, async_add_entities)

        # Verify async_add_entities was called
        async_add_entities.assert_called_once()
        call_args = async_add_entities.call_args[0][0]
        # Mode 0 creates all entities (7 core + offset = 8)
        assert len(call_args) == 8

    @pytest.mark.asyncio
    async def test_async_setup_entry_protocol_mode_2(self):
        """Test async_setup_entry with protocol mode 2 includes offset."""
        coordinator = create_mock_coordinator(protocol_mode=2)

        entry = MagicMock()
        entry.runtime_data = coordinator
        async_add_entities = MagicMock()
        hass = MagicMock()

        await async_setup_entry(hass, entry, async_add_entities)

        async_add_entities.assert_called_once()
        call_args = async_add_entities.call_args[0][0]
        # Mode 2 includes offset (7 core + offset = 8)
        assert len(call_args) == 8

    @pytest.mark.asyncio
    async def test_async_setup_entry_protocol_mode_1(self):
        """Test async_setup_entry with protocol mode 1 excludes offset."""
        coordinator = create_mock_coordinator(protocol_mode=1)

        entry = MagicMock()
        entry.runtime_data = coordinator
        async_add_entities = MagicMock()
        hass = MagicMock()

        await async_setup_entry(hass, entry, async_add_entities)

        async_add_entities.assert_called_once()
        call_args = async_add_entities.call_args[0][0]
        # Mode 1 excludes offset (7 core entities)
        assert len(call_args) == 7


    @pytest.mark.asyncio
    async def test_cronus_air_creates_only_record_backed_controls(self):
        coordinator = create_mock_coordinator(protocol_mode=9)
        coordinator.data["cronus_controller_type"] = "air"
        entry = MagicMock(runtime_data=coordinator)
        async_add_entities = MagicMock()

        await async_setup_entry(MagicMock(), entry, async_add_entities)

        entities = async_add_entities.call_args[0][0]
        assert {type(entity) for entity in entities} == {
            VevorHeaterLevelNumber,
            VevorHeaterTemperatureNumber,
        }
        assert not any(isinstance(entity, VevorTankCapacityNumber) for entity in entities)
        assert not any(isinstance(entity, VevorCurrentFuelLevelNumber) for entity in entities)

    @pytest.mark.asyncio
    async def test_cronus_water_creates_fuel_controls_with_matching_profile(self):
        coordinator = create_mock_coordinator(protocol_mode=9)
        coordinator.has_cronus_fuel_estimate = True
        coordinator.data["cronus_controller_type"] = "water"
        async_add_entities = MagicMock()

        await async_setup_entry(MagicMock(), MagicMock(runtime_data=coordinator), async_add_entities)

        assert {type(entity) for entity in async_add_entities.call_args[0][0]} == {
            VevorTankCapacityNumber,
            VevorCurrentFuelLevelNumber,
        }

    @pytest.mark.asyncio
    async def test_cronus_water_omits_air_and_calculated_controls(self):
        coordinator = create_mock_coordinator(protocol_mode=9)
        coordinator.data["cronus_controller_type"] = "water"
        entry = MagicMock(runtime_data=coordinator)
        async_add_entities = MagicMock()

        await async_setup_entry(MagicMock(), entry, async_add_entities)

        assert async_add_entities.call_args[0][0] == []


# ---------------------------------------------------------------------------
# Temperature number tests
# ---------------------------------------------------------------------------

class TestVevorHeaterTemperatureNumber:
    """Tests for Vevor heater temperature number entity."""

    def test_native_value(self):
        """Test native_value returns current temperature."""
        coordinator = create_mock_coordinator()
        coordinator.data["set_temp"] = 25
        number = VevorHeaterTemperatureNumber(coordinator)

        assert number.native_value == 25

    def test_native_value_none_returns_min(self):
        """Test native_value returns min temp when None."""
        coordinator = create_mock_coordinator()
        coordinator.data["set_temp"] = None
        number = VevorHeaterTemperatureNumber(coordinator)

        # Should return MIN_TEMP_CELSIUS (8)
        assert number.native_value == 8

    def test_min_value_attr(self):
        """Test _attr_native_min_value is 8."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterTemperatureNumber(coordinator)

        assert number._attr_native_min_value == 8

    def test_max_value_attr(self):
        """Test _attr_native_max_value is 36."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterTemperatureNumber(coordinator)

        assert number._attr_native_max_value == 36

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterTemperatureNumber(coordinator)

        assert "_target_temp" in number.unique_id

    def test_has_entity_name(self):
        """Test has_entity_name is True."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterTemperatureNumber(coordinator)

        assert number._attr_has_entity_name is True

    def test_device_info(self):
        """Test device_info is set correctly."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterTemperatureNumber(coordinator)

        assert number._attr_device_info is not None
        assert "identifiers" in number._attr_device_info


# ---------------------------------------------------------------------------
# Async set native value tests
# ---------------------------------------------------------------------------

class TestNumberAsyncSetNativeValue:
    """Tests for async_set_native_value methods."""

    @pytest.mark.asyncio
    async def test_level_async_set_native_value(self):
        """Test VevorHeaterLevelNumber async_set_native_value."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterLevelNumber(coordinator)

        await number.async_set_native_value(7)

        coordinator.async_set_level.assert_called_once_with(7)

    @pytest.mark.asyncio
    async def test_temperature_async_set_native_value(self):
        """Test VevorHeaterTemperatureNumber async_set_native_value."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterTemperatureNumber(coordinator)

        await number.async_set_native_value(25)

        coordinator.async_set_temperature.assert_called_once_with(25)

    @pytest.mark.asyncio
    async def test_offset_async_set_native_value(self):
        """Test VevorHeaterOffsetNumber async_set_native_value."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterOffsetNumber(coordinator)

        await number.async_set_native_value(3)

        coordinator.async_set_heater_offset.assert_called_once_with(3)

    @pytest.mark.asyncio
    async def test_tank_capacity_async_set_native_value(self):
        """Test VevorTankCapacityNumber async_set_native_value."""
        coordinator = create_mock_coordinator()
        number = VevorTankCapacityNumber(coordinator)

        await number.async_set_native_value(15)

        coordinator.async_set_tank_capacity.assert_called_once_with(15)

    @pytest.mark.asyncio
    async def test_level_converts_float_to_int(self):
        """Test level async_set_native_value converts float to int."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterLevelNumber(coordinator)

        await number.async_set_native_value(5.7)

        coordinator.async_set_level.assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_offset_handles_negative_value(self):
        """Test offset async_set_native_value handles negative values."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterOffsetNumber(coordinator)

        await number.async_set_native_value(-5)

        coordinator.async_set_heater_offset.assert_called_once_with(-5)


# ---------------------------------------------------------------------------
# Entity attribute tests
# ---------------------------------------------------------------------------

class TestNumberEntityAttributes:
    """Tests for number entity attributes."""

    def test_level_icon(self):
        """Test level icon."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterLevelNumber(coordinator)

        assert number._attr_icon == "mdi:gauge"

    def test_temperature_icon(self):
        """Test temperature icon."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterTemperatureNumber(coordinator)

        assert number._attr_icon == "mdi:thermometer"

    def test_offset_icon(self):
        """Test offset icon."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterOffsetNumber(coordinator)

        assert number._attr_icon == "mdi:thermometer-plus"

    def test_tank_capacity_icon(self):
        """Test tank capacity icon."""
        coordinator = create_mock_coordinator()
        number = VevorTankCapacityNumber(coordinator)

        assert number._attr_icon == "mdi:gas-station"

    def test_offset_min_max_values(self):
        """Test offset min/max values."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterOffsetNumber(coordinator)

        assert number._attr_native_min_value == -9
        assert number._attr_native_max_value == 9

    def test_tank_capacity_min_max_values(self):
        """Test tank capacity min/max values."""
        coordinator = create_mock_coordinator()
        number = VevorTankCapacityNumber(coordinator)

        assert number._attr_native_min_value == 1
        assert number._attr_native_max_value == 100

    def test_tank_capacity_entity_category(self):
        """Test tank capacity is in CONFIG category."""
        coordinator = create_mock_coordinator()
        number = VevorTankCapacityNumber(coordinator)

        # EntityCategory.CONFIG is mocked, just check it's set
        assert number._attr_entity_category is not None


# ---------------------------------------------------------------------------
# _handle_coordinator_update tests
# ---------------------------------------------------------------------------

class TestHandleCoordinatorUpdate:
    """Tests for _handle_coordinator_update on all number entities."""

    def test_level_handle_coordinator_update(self):
        """Test LevelNumber _handle_coordinator_update calls async_write_ha_state."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterLevelNumber(coordinator)
        number.async_write_ha_state = MagicMock()

        number._handle_coordinator_update()

        number.async_write_ha_state.assert_called_once()

    def test_temperature_handle_coordinator_update(self):
        """Test TemperatureNumber _handle_coordinator_update calls async_write_ha_state."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterTemperatureNumber(coordinator)
        number.async_write_ha_state = MagicMock()

        number._handle_coordinator_update()

        number.async_write_ha_state.assert_called_once()

    def test_offset_handle_coordinator_update(self):
        """Test OffsetNumber _handle_coordinator_update calls async_write_ha_state."""
        coordinator = create_mock_coordinator()
        number = VevorHeaterOffsetNumber(coordinator)
        number.async_write_ha_state = MagicMock()

        number._handle_coordinator_update()

        number.async_write_ha_state.assert_called_once()

    def test_tank_capacity_handle_coordinator_update(self):
        """Test TankCapacityNumber _handle_coordinator_update calls async_write_ha_state."""
        coordinator = create_mock_coordinator()
        number = VevorTankCapacityNumber(coordinator)
        number.async_write_ha_state = MagicMock()

        number._handle_coordinator_update()

        number.async_write_ha_state.assert_called_once()


class TestVevorBurnoffDurationNumber:
    """Tests for burn-off duration number entity."""

    def test_native_value(self):
        """Test native_value returns coordinator duration."""
        coordinator = create_mock_coordinator()
        coordinator.burnoff_duration_minutes = 15
        number = VevorBurnoffDurationNumber(coordinator)

        assert number.native_value == 15

    def test_min_max(self):
        """Test duration range is 1-30 minutes."""
        coordinator = create_mock_coordinator()
        number = VevorBurnoffDurationNumber(coordinator)

        assert number._attr_native_min_value == 1
        assert number._attr_native_max_value == 30

    @pytest.mark.asyncio
    async def test_async_set_native_value(self):
        """Test setting duration calls coordinator."""
        coordinator = create_mock_coordinator()
        number = VevorBurnoffDurationNumber(coordinator)

        await number.async_set_native_value(8)

        coordinator.async_set_burnoff_duration.assert_called_once_with(8)


class TestVevorBurnoffAfterCyclesNumber:
    """Tests for burn-off after cycles number entity."""

    def test_native_value(self):
        """Test native_value returns coordinator cycle threshold."""
        coordinator = create_mock_coordinator()
        coordinator.burnoff_after_cycles = 5
        number = VevorBurnoffAfterCyclesNumber(coordinator)

        assert number.native_value == 5

    @pytest.mark.asyncio
    async def test_async_set_native_value(self):
        """Test setting cycles calls coordinator."""
        coordinator = create_mock_coordinator()
        number = VevorBurnoffAfterCyclesNumber(coordinator)

        await number.async_set_native_value(3)

        coordinator.async_set_burnoff_after_cycles.assert_called_once_with(3)


class TestVevorBurnoffAfterHoursNumber:
    """Tests for burn-off after hours number entity."""

    def test_native_value(self):
        """Test native_value returns coordinator hours threshold."""
        coordinator = create_mock_coordinator()
        coordinator.burnoff_after_hours = 4
        number = VevorBurnoffAfterHoursNumber(coordinator)

        assert number.native_value == 4

    @pytest.mark.asyncio
    async def test_async_set_native_value(self):
        """Test setting hours calls coordinator."""
        coordinator = create_mock_coordinator()
        number = VevorBurnoffAfterHoursNumber(coordinator)

        await number.async_set_native_value(2)

        coordinator.async_set_burnoff_after_hours.assert_called_once_with(2)
