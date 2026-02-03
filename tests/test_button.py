"""Tests for Vevor Heater button platform."""
from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock

# Import stubs first
from . import conftest  # noqa: F401

from custom_components.vevor_heater.button import (
    VevorTimeSyncButton,
    VevorResetFuelLevelButton,
)


def create_mock_coordinator() -> MagicMock:
    """Create a mock coordinator for button testing."""
    coordinator = MagicMock()
    coordinator._address = "AA:BB:CC:DD:EE:FF"
    coordinator.address = "AA:BB:CC:DD:EE:FF"
    coordinator._heater_id = "EE:FF"
    coordinator.last_update_success = True
    coordinator.send_command = AsyncMock(return_value=True)
    coordinator.reset_fuel_level = AsyncMock()
    coordinator.data = {
        "connected": True,
    }
    return coordinator


# ---------------------------------------------------------------------------
# Time sync button tests
# ---------------------------------------------------------------------------

class TestVevorTimeSyncButton:
    """Tests for Vevor time sync button entity."""

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        button = VevorTimeSyncButton(coordinator)

        assert "_time_sync" in button.unique_id or "_sync" in button.unique_id

    def test_has_entity_name(self):
        """Test has_entity_name is True."""
        coordinator = create_mock_coordinator()
        button = VevorTimeSyncButton(coordinator)

        assert button._attr_has_entity_name is True


# ---------------------------------------------------------------------------
# Reset fuel level button tests
# ---------------------------------------------------------------------------

class TestVevorResetFuelLevelButton:
    """Tests for Vevor reset fuel level button entity."""

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        button = VevorResetFuelLevelButton(coordinator)

        assert "_reset" in button.unique_id or "_fuel" in button.unique_id

    def test_has_entity_name(self):
        """Test has_entity_name is True."""
        coordinator = create_mock_coordinator()
        button = VevorResetFuelLevelButton(coordinator)

        assert button._attr_has_entity_name is True


# ---------------------------------------------------------------------------
# Availability tests
# ---------------------------------------------------------------------------

class TestButtonAvailability:
    """Tests for button availability."""

    def test_available_when_connected(self):
        """Test button is available when connected."""
        coordinator = create_mock_coordinator()
        coordinator.last_update_success = True
        button = VevorTimeSyncButton(coordinator)

        assert button.available is True

    def test_available_property_exists(self):
        """Test available property is accessible."""
        coordinator = create_mock_coordinator()
        button = VevorTimeSyncButton(coordinator)

        # Just verify property is accessible
        _ = button.available
