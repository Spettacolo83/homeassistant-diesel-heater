"""Tests for Vevor Heater binary_sensor platform."""
from __future__ import annotations

from unittest.mock import MagicMock

# Import stubs first
from . import conftest  # noqa: F401

from custom_components.vevor_heater.binary_sensor import (
    VevorHeaterActiveSensor,
    VevorHeaterProblemSensor,
    VevorHeaterConnectedSensor,
)


def create_mock_coordinator() -> MagicMock:
    """Create a mock coordinator for binary_sensor testing."""
    coordinator = MagicMock()
    coordinator._address = "AA:BB:CC:DD:EE:FF"
    coordinator.address = "AA:BB:CC:DD:EE:FF"
    coordinator._heater_id = "EE:FF"
    coordinator.last_update_success = True
    coordinator.data = {
        "connected": True,
        "running_state": 1,
        "running_step": 3,
        "error_code": 0,
    }
    return coordinator


# ---------------------------------------------------------------------------
# Active sensor tests
# ---------------------------------------------------------------------------

class TestVevorHeaterActiveSensor:
    """Tests for Vevor heater active binary sensor."""

    def test_is_on_when_running(self):
        """Test is_on returns True when heater is running."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_state"] = 1
        sensor = VevorHeaterActiveSensor(coordinator)

        assert sensor.is_on is True

    def test_is_on_when_off(self):
        """Test is_on returns False when heater is off."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_state"] = 0
        sensor = VevorHeaterActiveSensor(coordinator)

        assert sensor.is_on is False

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        sensor = VevorHeaterActiveSensor(coordinator)

        assert "_active" in sensor.unique_id or "_running" in sensor.unique_id


# ---------------------------------------------------------------------------
# Problem sensor tests
# ---------------------------------------------------------------------------

class TestVevorHeaterProblemSensor:
    """Tests for Vevor heater problem binary sensor."""

    def test_is_on_when_error(self):
        """Test is_on returns True when there's an error."""
        coordinator = create_mock_coordinator()
        coordinator.data["error_code"] = 1  # Some error
        sensor = VevorHeaterProblemSensor(coordinator)

        assert sensor.is_on is True

    def test_is_on_when_no_error(self):
        """Test is_on returns False when no error."""
        coordinator = create_mock_coordinator()
        coordinator.data["error_code"] = 0  # No error
        sensor = VevorHeaterProblemSensor(coordinator)

        assert sensor.is_on is False

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        sensor = VevorHeaterProblemSensor(coordinator)

        assert "_problem" in sensor.unique_id or "_error" in sensor.unique_id


# ---------------------------------------------------------------------------
# Connected sensor tests
# ---------------------------------------------------------------------------

class TestVevorHeaterConnectedSensor:
    """Tests for Vevor heater connected binary sensor."""

    def test_is_on_when_connected(self):
        """Test is_on returns True when heater is connected."""
        coordinator = create_mock_coordinator()
        coordinator.data["connected"] = True
        sensor = VevorHeaterConnectedSensor(coordinator)

        assert sensor.is_on is True

    def test_is_on_when_disconnected(self):
        """Test is_on returns False when heater is disconnected."""
        coordinator = create_mock_coordinator()
        coordinator.data["connected"] = False
        sensor = VevorHeaterConnectedSensor(coordinator)

        assert sensor.is_on is False

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        sensor = VevorHeaterConnectedSensor(coordinator)

        assert "_connected" in sensor.unique_id


# ---------------------------------------------------------------------------
# Availability tests
# ---------------------------------------------------------------------------

class TestBinarySensorAvailability:
    """Tests for binary sensor availability."""

    def test_available_when_connected(self):
        """Test binary sensor is available when connected."""
        coordinator = create_mock_coordinator()
        coordinator.last_update_success = True
        sensor = VevorHeaterActiveSensor(coordinator)

        assert sensor.available is True

    def test_available_property_exists(self):
        """Test available property is accessible."""
        coordinator = create_mock_coordinator()
        sensor = VevorHeaterActiveSensor(coordinator)

        # Just verify property is accessible
        _ = sensor.available
