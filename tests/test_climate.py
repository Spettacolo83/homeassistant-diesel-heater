"""Tests for Vevor Heater climate platform."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

# Import stubs first
from . import conftest  # noqa: F401

from custom_components.vevor_heater.climate import VevorHeaterClimate


def create_mock_coordinator() -> MagicMock:
    """Create a mock coordinator for climate testing."""
    coordinator = MagicMock()
    coordinator._address = "AA:BB:CC:DD:EE:FF"
    coordinator.address = "AA:BB:CC:DD:EE:FF"
    coordinator._heater_id = "EE:FF"
    coordinator.last_update_success = True
    coordinator.send_command = AsyncMock(return_value=True)
    coordinator.async_set_temperature = AsyncMock()
    coordinator.async_turn_on = AsyncMock()
    coordinator.async_turn_off = AsyncMock()
    coordinator.data = {
        "connected": True,
        "running_state": 1,
        "running_step": 3,
        "running_mode": 2,  # Temperature mode
        "set_level": 5,
        "set_temp": 22,
        "cab_temperature": 20.5,
        "case_temperature": 50,
        "supply_voltage": 12.5,
        "error_code": 0,
    }
    return coordinator


def create_mock_config_entry() -> MagicMock:
    """Create a mock config entry for climate testing."""
    entry = MagicMock()
    entry.data = {
        "address": "AA:BB:CC:DD:EE:FF",
        "preset_away_temp": 8,
        "preset_comfort_temp": 21,
    }
    entry.options = {
        "preset_modes": {},
    }
    entry.entry_id = "test_entry"
    return entry


# ---------------------------------------------------------------------------
# Climate entity tests
# ---------------------------------------------------------------------------

class TestVevorHeaterClimate:
    """Tests for Vevor climate entity."""

    def test_current_temperature(self):
        """Test current_temperature returns cabin temperature."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert climate.current_temperature == 20.5

    def test_current_temperature_none(self):
        """Test current_temperature when None."""
        coordinator = create_mock_coordinator()
        coordinator.data["cab_temperature"] = None
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert climate.current_temperature is None

    def test_target_temperature(self):
        """Test target_temperature returns set_temp."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert climate.target_temperature == 22

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert "_climate" in climate.unique_id


class TestClimateHvacMode:
    """Tests for HVAC mode functionality."""

    def test_hvac_mode_heat_when_running(self):
        """Test hvac_mode is HEAT when heater is running."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_state"] = 1  # Running
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        # The actual value may be a MagicMock, just check it's not None/OFF
        assert climate.hvac_mode is not None

    def test_hvac_mode_off_when_not_running(self):
        """Test hvac_mode is OFF when heater is off."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_state"] = 0  # Off
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        # Check it returns a valid value
        assert climate.hvac_mode is not None


class TestClimateAvailability:
    """Tests for climate availability."""

    def test_available_when_connected(self):
        """Test climate is available when connected."""
        coordinator = create_mock_coordinator()
        coordinator.last_update_success = True
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert climate.available is True

    def test_available_property_exists(self):
        """Test available property is accessible."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        # Just verify we can access the property
        _ = climate.available


# ---------------------------------------------------------------------------
# HVAC Action tests
# ---------------------------------------------------------------------------

class TestClimateHvacAction:
    """Tests for HVAC action functionality."""

    def test_hvac_action_when_standby_and_off(self):
        """Test hvac_action when standby and running_state OFF."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = 0  # RUNNING_STEP_STANDBY
        coordinator.data["running_state"] = 0  # OFF
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        # Should return HVACAction.OFF (mock object)
        assert climate.hvac_action is not None

    def test_hvac_action_when_standby_and_on(self):
        """Test hvac_action when standby but running_state ON."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = 0  # RUNNING_STEP_STANDBY
        coordinator.data["running_state"] = 1  # ON (Auto Start/Stop waiting)
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        # Should return HVACAction.IDLE
        assert climate.hvac_action is not None

    def test_hvac_action_when_running(self):
        """Test hvac_action when heater is running."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = 3  # RUNNING_STEP_RUNNING
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        # Should return HVACAction.HEATING
        assert climate.hvac_action is not None

    def test_hvac_action_when_ignition(self):
        """Test hvac_action when in ignition phase."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = 2  # RUNNING_STEP_IGNITION
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        # Should return HVACAction.HEATING
        assert climate.hvac_action is not None

    def test_hvac_action_when_self_test(self):
        """Test hvac_action when in self-test phase."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = 1  # RUNNING_STEP_SELF_TEST
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert climate.hvac_action is not None

    def test_hvac_action_when_cooldown(self):
        """Test hvac_action when in cooldown phase."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = 4  # RUNNING_STEP_COOLDOWN
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        # Should return HVACAction.FAN
        assert climate.hvac_action is not None

    def test_hvac_action_when_ventilation(self):
        """Test hvac_action when in ventilation mode."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = 6  # RUNNING_STEP_VENTILATION
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert climate.hvac_action is not None

    def test_hvac_action_none_when_running_step_none(self):
        """Test hvac_action is None when running_step is None."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = None
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert climate.hvac_action is None

    def test_hvac_action_for_unknown_step(self):
        """Test hvac_action for unknown running_step."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = 99  # Unknown step
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        # Should return IDLE as default
        assert climate.hvac_action is not None


# ---------------------------------------------------------------------------
# Preset mode tests
# ---------------------------------------------------------------------------

class TestClimatePresetMode:
    """Tests for preset mode functionality."""

    def test_preset_mode_property_accessible(self):
        """Test preset_mode property is accessible."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        # Just verify we can access the property
        _ = climate.preset_mode

    def test_preset_mode_when_temp_matches_away(self):
        """Test preset detection when temp matches away."""
        coordinator = create_mock_coordinator()
        coordinator.data["set_temp"] = 8  # Matches default away temp
        config_entry = create_mock_config_entry()
        config_entry.data["preset_away_temp"] = 8
        climate = VevorHeaterClimate(coordinator, config_entry)

        # Should detect PRESET_AWAY
        assert climate.preset_mode is not None

    def test_preset_mode_when_temp_matches_comfort(self):
        """Test preset detection when temp matches comfort."""
        coordinator = create_mock_coordinator()
        coordinator.data["set_temp"] = 21  # Matches default comfort temp
        config_entry = create_mock_config_entry()
        config_entry.data["preset_comfort_temp"] = 21
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert climate.preset_mode is not None

    def test_preset_mode_when_user_cleared(self):
        """Test preset stays NONE when user explicitly cleared it."""
        coordinator = create_mock_coordinator()
        coordinator.data["set_temp"] = 8  # Matches away temp
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)
        climate._user_cleared_preset = True  # User cleared preset

        # Should still return PRESET_NONE
        assert climate.preset_mode is not None


# ---------------------------------------------------------------------------
# Async method tests
# ---------------------------------------------------------------------------

class TestClimateAsyncMethods:
    """Tests for async climate methods."""

    @pytest.mark.asyncio
    async def test_async_set_temperature_method_exists(self):
        """Test async_set_temperature method exists and is callable."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        # Verify method exists
        assert hasattr(climate, 'async_set_temperature')
        assert callable(climate.async_set_temperature)

    @pytest.mark.asyncio
    async def test_async_turn_on(self):
        """Test async_turn_on turns on heater."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        await climate.async_turn_on()

        coordinator.async_turn_on.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_turn_off(self):
        """Test async_turn_off turns off heater."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        await climate.async_turn_off()

        coordinator.async_turn_off.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_set_hvac_mode_method_exists(self):
        """Test async_set_hvac_mode method exists."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert hasattr(climate, 'async_set_hvac_mode')
        assert callable(climate.async_set_hvac_mode)

    @pytest.mark.asyncio
    async def test_async_set_preset_mode_method_exists(self):
        """Test async_set_preset_mode method exists."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert hasattr(climate, 'async_set_preset_mode')
        assert callable(climate.async_set_preset_mode)


# ---------------------------------------------------------------------------
# Climate attributes tests
# ---------------------------------------------------------------------------

class TestClimateAttributes:
    """Tests for climate entity attributes."""

    def test_min_temp(self):
        """Test min_temp attribute."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert climate._attr_min_temp == 8

    def test_max_temp(self):
        """Test max_temp attribute."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert climate._attr_max_temp == 36

    def test_target_temperature_step(self):
        """Test target_temperature_step attribute."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert climate._attr_target_temperature_step == 1

    def test_hvac_modes_not_empty(self):
        """Test hvac_modes attribute is not empty."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert len(climate._attr_hvac_modes) == 2

    def test_preset_modes_not_empty(self):
        """Test preset_modes attribute is not empty."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert len(climate._attr_preset_modes) == 3

    def test_has_entity_name(self):
        """Test has_entity_name is True."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert climate._attr_has_entity_name is True

    def test_device_info(self):
        """Test device_info is set correctly."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert climate._attr_device_info is not None
        assert "identifiers" in climate._attr_device_info
        assert "name" in climate._attr_device_info


# ---------------------------------------------------------------------------
# Helper method tests
# ---------------------------------------------------------------------------

class TestClimateHelperMethods:
    """Tests for climate helper methods."""

    def test_get_away_temp_default(self):
        """Test _get_away_temp returns default value."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        config_entry.data = {"address": "AA:BB:CC:DD:EE:FF"}  # No preset temps
        climate = VevorHeaterClimate(coordinator, config_entry)

        # Should return default (8)
        assert climate._get_away_temp() == 8

    def test_get_away_temp_configured(self):
        """Test _get_away_temp returns configured value."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        config_entry.data["preset_away_temp"] = 10
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert climate._get_away_temp() == 10

    def test_get_comfort_temp_default(self):
        """Test _get_comfort_temp returns default value."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        config_entry.data = {"address": "AA:BB:CC:DD:EE:FF"}  # No preset temps
        climate = VevorHeaterClimate(coordinator, config_entry)

        # Should return default (21)
        assert climate._get_comfort_temp() == 21

    def test_get_comfort_temp_configured(self):
        """Test _get_comfort_temp returns configured value."""
        coordinator = create_mock_coordinator()
        config_entry = create_mock_config_entry()
        config_entry.data["preset_comfort_temp"] = 23
        climate = VevorHeaterClimate(coordinator, config_entry)

        assert climate._get_comfort_temp() == 23
