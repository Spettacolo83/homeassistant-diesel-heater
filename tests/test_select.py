"""Tests for Vevor Heater select platform."""
from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock

# Import stubs first
from . import conftest  # noqa: F401

from custom_components.vevor_heater.select import (
    VevorHeaterModeSelect,
    VevorBacklightSelect,
)


def create_mock_coordinator() -> MagicMock:
    """Create a mock coordinator for select testing."""
    coordinator = MagicMock()
    coordinator._address = "AA:BB:CC:DD:EE:FF"
    coordinator.address = "AA:BB:CC:DD:EE:FF"
    coordinator._heater_id = "EE:FF"
    coordinator.last_update_success = True
    coordinator.send_command = AsyncMock(return_value=True)
    coordinator.data = {
        "connected": True,
        "running_mode": 1,  # Level mode
        "backlight": 3,
    }
    return coordinator


# ---------------------------------------------------------------------------
# Mode select tests
# ---------------------------------------------------------------------------

class TestVevorHeaterModeSelect:
    """Tests for Vevor heater mode select entity."""

    def test_current_option_level_mode(self):
        """Test current_option returns correct mode name."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_mode"] = 1  # Level mode
        select = VevorHeaterModeSelect(coordinator)

        # Should return some mode name
        assert select.current_option is not None

    def test_current_option_temp_mode(self):
        """Test current_option in temperature mode."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_mode"] = 2  # Temperature mode
        select = VevorHeaterModeSelect(coordinator)

        assert select.current_option is not None

    def test_options_attr_not_empty(self):
        """Test _attr_options list is not empty."""
        coordinator = create_mock_coordinator()
        select = VevorHeaterModeSelect(coordinator)

        assert len(select._attr_options) > 0

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        select = VevorHeaterModeSelect(coordinator)

        assert "_mode" in select.unique_id


# ---------------------------------------------------------------------------
# Backlight select tests
# ---------------------------------------------------------------------------

class TestVevorBacklightSelect:
    """Tests for Vevor backlight select entity."""

    def test_current_option(self):
        """Test current_option returns backlight level."""
        coordinator = create_mock_coordinator()
        coordinator.data["backlight"] = 3
        select = VevorBacklightSelect(coordinator)

        # Should return some value
        assert select.current_option is not None

    def test_options_attr_not_empty(self):
        """Test _attr_options list is not empty."""
        coordinator = create_mock_coordinator()
        select = VevorBacklightSelect(coordinator)

        assert len(select._attr_options) > 0

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        select = VevorBacklightSelect(coordinator)

        assert "_backlight" in select.unique_id


# ---------------------------------------------------------------------------
# Availability tests
# ---------------------------------------------------------------------------

class TestSelectAvailability:
    """Tests for select availability."""

    def test_available_when_connected(self):
        """Test select is available when connected."""
        coordinator = create_mock_coordinator()
        coordinator.data["connected"] = True
        select = VevorHeaterModeSelect(coordinator)

        assert select.available is True

    def test_unavailable_when_disconnected(self):
        """Test select is unavailable when disconnected."""
        coordinator = create_mock_coordinator()
        coordinator.data["connected"] = False
        select = VevorHeaterModeSelect(coordinator)

        assert select.available is False
