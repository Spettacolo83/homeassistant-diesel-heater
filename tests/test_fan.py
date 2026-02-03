"""Tests for Vevor Heater fan platform."""
from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock

# Import stubs first
from . import conftest  # noqa: F401

from custom_components.vevor_heater.fan import VevorHeaterFan


def create_mock_coordinator() -> MagicMock:
    """Create a mock coordinator for fan testing."""
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
        "running_mode": 1,  # Level mode
        "set_level": 5,
        "set_temp": 22,
        "cab_temperature": 20.5,
        "error_code": 0,
    }
    return coordinator


# ---------------------------------------------------------------------------
# Fan entity tests
# ---------------------------------------------------------------------------

class TestVevorHeaterFan:
    """Tests for Vevor fan entity."""

    def test_is_on_when_running(self):
        """Test is_on returns True when heater is running."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_state"] = 1
        fan = VevorHeaterFan(coordinator)

        assert fan.is_on is True

    def test_is_on_when_off(self):
        """Test is_on returns False when heater is off."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_state"] = 0
        fan = VevorHeaterFan(coordinator)

        assert fan.is_on is False

    def test_percentage_property_exists(self):
        """Test percentage property is accessible."""
        coordinator = create_mock_coordinator()
        coordinator.data["set_level"] = 5
        fan = VevorHeaterFan(coordinator)

        # Just verify property is accessible
        _ = fan.percentage

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        fan = VevorHeaterFan(coordinator)

        # Fan uses heater_level as unique_id suffix
        assert "_heater_level" in fan.unique_id or "_fan" in fan.unique_id


class TestFanAvailability:
    """Tests for fan availability."""

    def test_available_when_connected(self):
        """Test fan is available when connected."""
        coordinator = create_mock_coordinator()
        coordinator.data["connected"] = True
        fan = VevorHeaterFan(coordinator)

        assert fan.available is True

    def test_available_property_exists(self):
        """Test available property is accessible."""
        coordinator = create_mock_coordinator()
        fan = VevorHeaterFan(coordinator)

        # Just verify property is accessible
        _ = fan.available
