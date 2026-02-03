"""Tests for Vevor Heater number platform."""
from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock

# Import stubs first
from . import conftest  # noqa: F401

from custom_components.vevor_heater.number import (
    VevorHeaterLevelNumber,
    VevorHeaterOffsetNumber,
    VevorTankCapacityNumber,
)


def create_mock_coordinator() -> MagicMock:
    """Create a mock coordinator for number testing."""
    coordinator = MagicMock()
    coordinator._address = "AA:BB:CC:DD:EE:FF"
    coordinator.address = "AA:BB:CC:DD:EE:FF"
    coordinator._heater_id = "EE:FF"
    coordinator.last_update_success = True
    coordinator.send_command = AsyncMock(return_value=True)
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
