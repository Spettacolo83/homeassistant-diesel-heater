"""Tests for Vevor Heater switch platform."""
from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock

# Import stubs first
from . import conftest  # noqa: F401

from custom_components.vevor_heater.switch import (
    VevorHeaterPowerSwitch,
    VevorAutoStartStopSwitch,
    VevorAutoOffsetSwitch,
)


def create_mock_coordinator() -> MagicMock:
    """Create a mock coordinator for switch testing."""
    coordinator = MagicMock()
    coordinator._address = "AA:BB:CC:DD:EE:FF"
    coordinator.address = "AA:BB:CC:DD:EE:FF"
    coordinator._heater_id = "EE:FF"
    coordinator.last_update_success = True
    coordinator.send_command = AsyncMock(return_value=True)
    coordinator.data = {
        "connected": True,
        "running_state": 1,
        "running_step": 3,
        "set_level": 5,
        "set_temp": 22,
        "auto_start_stop": 1,
        "auto_offset_enabled": False,
    }
    return coordinator


# ---------------------------------------------------------------------------
# Power switch tests
# ---------------------------------------------------------------------------

class TestVevorHeaterPowerSwitch:
    """Tests for Vevor power switch entity."""

    def test_is_on_when_running(self):
        """Test is_on returns True when heater is running."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_state"] = 1
        switch = VevorHeaterPowerSwitch(coordinator)

        assert switch.is_on is True

    def test_is_on_when_off(self):
        """Test is_on returns False when heater is off."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_state"] = 0
        switch = VevorHeaterPowerSwitch(coordinator)

        assert switch.is_on is False

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        switch = VevorHeaterPowerSwitch(coordinator)

        assert "_power" in switch.unique_id


# ---------------------------------------------------------------------------
# Auto start/stop switch tests
# ---------------------------------------------------------------------------

class TestVevorAutoStartStopSwitch:
    """Tests for Vevor auto start/stop switch entity."""

    def test_is_on_when_enabled(self):
        """Test is_on returns truthy when auto start/stop is enabled."""
        coordinator = create_mock_coordinator()
        coordinator.data["auto_start_stop"] = 1
        switch = VevorAutoStartStopSwitch(coordinator)

        # Returns 1 which is truthy
        assert switch.is_on

    def test_is_on_when_disabled(self):
        """Test is_on returns falsy when auto start/stop is disabled."""
        coordinator = create_mock_coordinator()
        coordinator.data["auto_start_stop"] = 0
        switch = VevorAutoStartStopSwitch(coordinator)

        # Returns 0 which is falsy
        assert not switch.is_on

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        switch = VevorAutoStartStopSwitch(coordinator)

        assert "_auto_start_stop" in switch.unique_id


# ---------------------------------------------------------------------------
# Auto offset switch tests
# ---------------------------------------------------------------------------

class TestVevorAutoOffsetSwitch:
    """Tests for Vevor auto offset switch entity."""

    def test_is_on_when_enabled(self):
        """Test is_on returns True when auto offset is enabled."""
        coordinator = create_mock_coordinator()
        coordinator.data["auto_offset_enabled"] = True
        switch = VevorAutoOffsetSwitch(coordinator)

        assert switch.is_on is True

    def test_is_on_when_disabled(self):
        """Test is_on returns False when auto offset is disabled."""
        coordinator = create_mock_coordinator()
        coordinator.data["auto_offset_enabled"] = False
        switch = VevorAutoOffsetSwitch(coordinator)

        assert switch.is_on is False

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        switch = VevorAutoOffsetSwitch(coordinator)

        assert "_auto_offset" in switch.unique_id


# ---------------------------------------------------------------------------
# Availability tests
# ---------------------------------------------------------------------------

class TestSwitchAvailability:
    """Tests for switch availability."""

    def test_available_when_connected(self):
        """Test switch is available when connected."""
        coordinator = create_mock_coordinator()
        coordinator.last_update_success = True
        switch = VevorHeaterPowerSwitch(coordinator)

        assert switch.available is True

    def test_available_property_exists(self):
        """Test available property is accessible."""
        coordinator = create_mock_coordinator()
        switch = VevorHeaterPowerSwitch(coordinator)

        # Just verify property is accessible
        _ = switch.available
