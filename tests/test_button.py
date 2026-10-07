"""Tests for Diesel Heater button platform."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

# Import stubs first
from . import conftest  # noqa: F401

from custom_components.diesel_heater.button import (
    VevorTimeSyncButton,
    VevorResetFuelLevelButton,
    VevorPowerOffNowButton,
    VevorRunBurnoffButton,
    async_setup_entry,
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
    coordinator.async_sync_time = AsyncMock()
    coordinator.async_reset_fuel_level = AsyncMock()
    coordinator.async_power_off_now = AsyncMock()
    coordinator.async_run_burnoff = AsyncMock()
    coordinator.protocol_mode = 0
    coordinator.has_cronus_fuel_estimate = False
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

    def test_not_available_when_not_connected(self):
        """Test button is not available when not connected."""
        coordinator = create_mock_coordinator()
        coordinator.data["connected"] = False
        button = VevorTimeSyncButton(coordinator)

        assert button.available is False


# ---------------------------------------------------------------------------
# Async setup entry tests
# ---------------------------------------------------------------------------

class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_async_setup_entry_creates_buttons(self):
        """Test async_setup_entry creates button entities."""
        coordinator = create_mock_coordinator()

        # Create mock entry with runtime_data
        entry = MagicMock()
        entry.runtime_data = coordinator

        # Create mock async_add_entities
        async_add_entities = MagicMock()

        # Create mock hass
        hass = MagicMock()

        await async_setup_entry(hass, entry, async_add_entities)

        # Verify async_add_entities was called with 4 buttons
        async_add_entities.assert_called_once()
        call_args = async_add_entities.call_args[0][0]
        assert len(call_args) == 4


# ---------------------------------------------------------------------------
# Async press tests
# ---------------------------------------------------------------------------

class TestButtonAsyncPress:
    """Tests for async_press methods."""

    @pytest.mark.asyncio
    async def test_time_sync_async_press(self):
        """Test VevorTimeSyncButton async_press calls coordinator."""
        coordinator = create_mock_coordinator()
        button = VevorTimeSyncButton(coordinator)

        await button.async_press()

        coordinator.async_sync_time.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_fuel_level_async_press(self):
        """Test VevorResetFuelLevelButton async_press calls coordinator."""
        coordinator = create_mock_coordinator()
        button = VevorResetFuelLevelButton(coordinator)

        await button.async_press()

        coordinator.async_reset_fuel_level.assert_called_once()

    @pytest.mark.asyncio
    async def test_power_off_now_async_press(self):
        """Test Power Off Now button calls coordinator."""
        coordinator = create_mock_coordinator()
        button = VevorPowerOffNowButton(coordinator)

        await button.async_press()

        coordinator.async_power_off_now.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_burnoff_async_press(self):
        """Test Run Burn-off button calls coordinator."""
        coordinator = create_mock_coordinator()
        button = VevorRunBurnoffButton(coordinator)

        await button.async_press()

        coordinator.async_run_burnoff.assert_called_once()


# ---------------------------------------------------------------------------
# Button attribute tests
# ---------------------------------------------------------------------------

class TestButtonAttributes:
    """Tests for button entity attributes."""

    def test_time_sync_icon(self):
        """Test time sync button icon."""
        coordinator = create_mock_coordinator()
        button = VevorTimeSyncButton(coordinator)

        assert button._attr_icon == "mdi:clock-sync"

    def test_reset_fuel_icon(self):
        """Test reset fuel button icon."""
        coordinator = create_mock_coordinator()
        button = VevorResetFuelLevelButton(coordinator)

        assert button._attr_icon == "mdi:gas-station"

    def test_time_sync_name(self):
        """Test time sync button name."""
        coordinator = create_mock_coordinator()
        button = VevorTimeSyncButton(coordinator)

        assert button._attr_name == "Sync Time"

    def test_reset_fuel_name(self):
        """Test reset fuel button name."""
        coordinator = create_mock_coordinator()
        button = VevorResetFuelLevelButton(coordinator)

        assert button._attr_name == "Reset Estimated Fuel Remaining"

    def test_time_sync_entity_category(self):
        """Test time sync button is in CONFIG category."""
        coordinator = create_mock_coordinator()
        button = VevorTimeSyncButton(coordinator)

        # EntityCategory.CONFIG is mocked
        assert button._attr_entity_category is not None

    def test_power_off_now_is_not_hidden_as_config(self):
        """Power Off Now must stay visible so users can skip remaining burn-off."""
        coordinator = create_mock_coordinator()
        button = VevorPowerOffNowButton(coordinator)

        assert getattr(button, "_attr_entity_category", None) is None

    def test_time_sync_device_info(self):
        """Test time sync button device_info."""
        coordinator = create_mock_coordinator()
        button = VevorTimeSyncButton(coordinator)

        assert button._attr_device_info is not None
        assert "identifiers" in button._attr_device_info

    def test_reset_fuel_device_info(self):
        """Test reset fuel button device_info."""
        coordinator = create_mock_coordinator()
        button = VevorResetFuelLevelButton(coordinator)

        assert button._attr_device_info is not None
        assert "identifiers" in button._attr_device_info


class TestCronusButtonSetup:
    """ThermoConnect creates only supported buttons and configured estimates."""

    @pytest.mark.asyncio
    async def test_does_not_create_generic_buttons(self):
        coordinator = create_mock_coordinator()
        coordinator.protocol_mode = 9
        entry = MagicMock(runtime_data=coordinator)
        async_add_entities = MagicMock()

        await async_setup_entry(MagicMock(), entry, async_add_entities)

        async_add_entities.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_only_reset_button_with_matching_profile(self):
        coordinator = create_mock_coordinator()
        coordinator.protocol_mode = 9
        coordinator.has_cronus_fuel_estimate = True
        async_add_entities = MagicMock()

        await async_setup_entry(MagicMock(), MagicMock(runtime_data=coordinator), async_add_entities)

        assert [type(entity) for entity in async_add_entities.call_args[0][0]] == [
            VevorResetFuelLevelButton
        ]
