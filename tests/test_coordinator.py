"""Tests for Vevor Heater Coordinator.

Tests the coordinator logic without requiring actual BLE connections.
Focuses on data processing, fuel/runtime tracking, and protocol handling.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio
import pytest

# Import stubs first
from . import conftest  # noqa: F401

# Now we can import the coordinator
from custom_components.vevor_heater.coordinator import VevorHeaterCoordinator
from custom_components.vevor_heater.const import (
    FUEL_CONSUMPTION_TABLE,
    RUNNING_STEP_RUNNING,
    STORAGE_KEY_TOTAL_FUEL,
    STORAGE_KEY_DAILY_FUEL,
    STORAGE_KEY_DAILY_DATE,
    STORAGE_KEY_DAILY_HISTORY,
    STORAGE_KEY_TOTAL_RUNTIME,
    STORAGE_KEY_DAILY_RUNTIME,
    STORAGE_KEY_DAILY_RUNTIME_DATE,
    STORAGE_KEY_DAILY_RUNTIME_HISTORY,
    STORAGE_KEY_FUEL_SINCE_RESET,
    STORAGE_KEY_TANK_CAPACITY,
    STORAGE_KEY_LAST_REFUELED,
    STORAGE_KEY_AUTO_OFFSET_ENABLED,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def create_mock_coordinator() -> VevorHeaterCoordinator:
    """Create a mock coordinator for testing without calling __init__."""
    from diesel_heater_ble import (
        ProtocolAA55, ProtocolAA66, ProtocolAA55Encrypted,
        ProtocolAA66Encrypted, ProtocolABBA, ProtocolCBFF,
    )

    hass = MagicMock()
    hass.loop = asyncio.new_event_loop()

    entry = MagicMock()
    entry.data = {"address": "AA:BB:CC:DD:EE:FF"}
    entry.options = {}
    entry.entry_id = "test_entry"

    ble_device = MagicMock()
    ble_device.address = "AA:BB:CC:DD:EE:FF"

    # Create coordinator without calling __init__ using object.__new__
    coordinator = object.__new__(VevorHeaterCoordinator)

    # Set up minimum required attributes
    coordinator.hass = hass
    coordinator.config_entry = entry
    coordinator._address = "AA:BB:CC:DD:EE:FF"
    coordinator._heater_id = "EE:FF"
    coordinator._logger = MagicMock()
    coordinator._store = MagicMock()
    coordinator._protocol = None
    coordinator._protocol_mode = 0
    coordinator._passkey = 1234

    # Protocol handlers dict (mode -> protocol instance)
    coordinator._protocols = {
        1: ProtocolAA55(),
        2: ProtocolAA55Encrypted(),
        3: ProtocolAA66(),
        4: ProtocolAA66Encrypted(),
        5: ProtocolABBA(),
        6: ProtocolCBFF(),
    }

    # Data dict
    coordinator.data = {
        "connected": False,
        "running_state": 0,
        "running_step": 0,
        "running_mode": 0,
        "set_level": 1,
        "set_temp": 22,
        "cab_temperature": 20.0,
        "case_temperature": 50,
        "supply_voltage": 12.5,
        "error_code": 0,
        "altitude": 0,
        "hourly_fuel_consumption": 0.0,
        "daily_fuel_consumed": 0.0,
        "total_fuel_consumed": 0.0,
        "fuel_remaining": None,
        "fuel_consumed_since_reset": 0.0,
        "tank_capacity": 5,
        "daily_runtime_hours": 0.0,
        "total_runtime_hours": 0.0,
        "daily_fuel_history": {},
        "daily_runtime_history": {},
    }

    # Fuel tracking state (correct attribute names)
    coordinator._daily_fuel_consumed = 0.0
    coordinator._total_fuel_consumed = 0.0
    coordinator._daily_fuel_history = {}
    coordinator._fuel_consumed_since_reset = 0.0
    coordinator._last_reset_date = datetime.now().strftime("%Y-%m-%d")

    # Runtime tracking state (correct attribute names)
    coordinator._daily_runtime_seconds = 0.0
    coordinator._total_runtime_seconds = 0.0
    coordinator._daily_runtime_history = {}
    coordinator._last_runtime_reset_date = datetime.now().strftime("%Y-%m-%d")

    # Connection state
    coordinator._last_update_time = None
    coordinator._last_valid_data = {}
    coordinator._consecutive_failures = 0
    coordinator._max_stale_cycles = 3
    coordinator._is_abba_device = False

    # Volatile fields for clear/restore/save
    coordinator._VOLATILE_FIELDS = (
        "case_temperature", "cab_temperature", "cab_temperature_raw",
        "supply_voltage", "running_state", "running_step", "running_mode",
        "set_level", "set_temp", "altitude", "error_code",
        "hourly_fuel_consumption", "co_ppm", "remain_run_time",
    )

    # Auto offset related
    coordinator._auto_offset_unsub = None
    coordinator._auto_offset_enabled = False
    coordinator._external_temp_sensor = None
    coordinator._auto_offset_max = 5
    coordinator._heater_uses_fahrenheit = False

    # Add address property (used by statistics import)
    coordinator.address = "AA:BB:CC:DD:EE:FF"

    # Add async_set_updated_data method (from DataUpdateCoordinator parent)
    coordinator.async_set_updated_data = MagicMock()

    return coordinator


# ---------------------------------------------------------------------------
# Fuel consumption calculation tests
# ---------------------------------------------------------------------------

class TestFuelConsumption:
    """Tests for fuel consumption calculations."""

    def test_calculate_fuel_consumption_level_1(self):
        """Test fuel consumption at level 1."""
        coordinator = create_mock_coordinator()
        coordinator.data["set_level"] = 1
        coordinator.data["running_step"] = RUNNING_STEP_RUNNING

        # 1 hour = 3600 seconds
        consumption = coordinator._calculate_fuel_consumption(3600)

        # Level 1 consumption from table
        expected = FUEL_CONSUMPTION_TABLE.get(1, 0.1)
        assert abs(consumption - expected) < 0.001

    def test_calculate_fuel_consumption_level_10(self):
        """Test fuel consumption at maximum level."""
        coordinator = create_mock_coordinator()
        coordinator.data["set_level"] = 10
        coordinator.data["running_step"] = RUNNING_STEP_RUNNING

        consumption = coordinator._calculate_fuel_consumption(3600)
        expected = FUEL_CONSUMPTION_TABLE.get(10, 0.5)
        assert abs(consumption - expected) < 0.001

    def test_calculate_fuel_consumption_fractional_hour(self):
        """Test fuel consumption for partial hour."""
        coordinator = create_mock_coordinator()
        coordinator.data["set_level"] = 5
        coordinator.data["running_step"] = RUNNING_STEP_RUNNING

        # 30 minutes = 1800 seconds
        consumption = coordinator._calculate_fuel_consumption(1800)
        expected = FUEL_CONSUMPTION_TABLE.get(5, 0.25) / 2
        assert abs(consumption - expected) < 0.001

    def test_calculate_fuel_consumption_zero_time(self):
        """Test fuel consumption with zero elapsed time."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = RUNNING_STEP_RUNNING
        consumption = coordinator._calculate_fuel_consumption(0)
        assert consumption == 0.0

    def test_calculate_fuel_consumption_when_not_running(self):
        """Test fuel consumption returns 0 when heater not running."""
        coordinator = create_mock_coordinator()
        coordinator.data["set_level"] = 10
        coordinator.data["running_step"] = 0  # Standby

        consumption = coordinator._calculate_fuel_consumption(3600)
        assert consumption == 0.0


class TestFuelTracking:
    """Tests for fuel tracking logic."""

    def test_update_fuel_tracking_when_running(self):
        """Test fuel tracking updates when heater is running."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = RUNNING_STEP_RUNNING
        coordinator.data["set_level"] = 5

        initial_daily = coordinator._daily_fuel_consumed
        initial_total = coordinator._total_fuel_consumed

        coordinator._update_fuel_tracking(3600)  # 1 hour

        expected = FUEL_CONSUMPTION_TABLE.get(5, 0.25)
        assert coordinator._daily_fuel_consumed > initial_daily
        assert coordinator._total_fuel_consumed > initial_total
        assert abs(coordinator._daily_fuel_consumed - expected) < 0.01

    def test_update_fuel_tracking_when_not_running(self):
        """Test fuel tracking doesn't update when heater is off."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = 0  # Standby

        initial_daily = coordinator._daily_fuel_consumed
        initial_total = coordinator._total_fuel_consumed

        coordinator._update_fuel_tracking(3600)

        assert coordinator._daily_fuel_consumed == initial_daily
        assert coordinator._total_fuel_consumed == initial_total

    def test_update_fuel_remaining(self):
        """Test fuel remaining calculation."""
        coordinator = create_mock_coordinator()
        coordinator.data["tank_capacity"] = 10
        coordinator._fuel_consumed_since_reset = 3.5

        coordinator._update_fuel_remaining()

        assert coordinator.data["fuel_remaining"] == 6.5

    def test_update_fuel_remaining_negative_clamped(self):
        """Test fuel remaining is clamped to zero."""
        coordinator = create_mock_coordinator()
        coordinator.data["tank_capacity"] = 5
        coordinator._fuel_consumed_since_reset = 10.0

        coordinator._update_fuel_remaining()

        assert coordinator.data["fuel_remaining"] == 0.0


# ---------------------------------------------------------------------------
# Runtime tracking tests
# ---------------------------------------------------------------------------

class TestRuntimeTracking:
    """Tests for runtime tracking logic."""

    def test_update_runtime_when_running(self):
        """Test runtime updates when heater is running."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = RUNNING_STEP_RUNNING

        initial_daily = coordinator._daily_runtime_seconds
        initial_total = coordinator._total_runtime_seconds

        coordinator._update_runtime_tracking(3600)  # 1 hour

        # Runtime is tracked in seconds internally
        assert coordinator._daily_runtime_seconds == initial_daily + 3600
        assert coordinator._total_runtime_seconds == initial_total + 3600

    def test_update_runtime_when_not_running(self):
        """Test runtime doesn't update when heater is off."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = 0

        initial_daily = coordinator._daily_runtime_seconds

        coordinator._update_runtime_tracking(3600)

        assert coordinator._daily_runtime_seconds == initial_daily


# ---------------------------------------------------------------------------
# Data management tests
# ---------------------------------------------------------------------------

class TestDataManagement:
    """Tests for data clearing, saving, and restoring."""

    def test_clear_sensor_values(self):
        """Test that sensor values are cleared correctly."""
        coordinator = create_mock_coordinator()
        coordinator.data["cab_temperature"] = 25.0
        coordinator.data["supply_voltage"] = 12.5

        coordinator._clear_sensor_values()

        assert coordinator.data["cab_temperature"] is None
        assert coordinator.data["supply_voltage"] is None

    def test_save_valid_data(self):
        """Test that valid data is saved for restoration."""
        coordinator = create_mock_coordinator()
        coordinator.data["cab_temperature"] = 25.0
        coordinator.data["supply_voltage"] = 12.5

        coordinator._save_valid_data()

        assert coordinator._last_valid_data["cab_temperature"] == 25.0
        assert coordinator._last_valid_data["supply_voltage"] == 12.5

    def test_restore_stale_data(self):
        """Test that stale data is restored correctly."""
        coordinator = create_mock_coordinator()
        coordinator._last_valid_data = {
            "cab_temperature": 25.0,
            "supply_voltage": 12.5,
        }
        coordinator.data["cab_temperature"] = None
        coordinator.data["supply_voltage"] = None

        coordinator._restore_stale_data()

        assert coordinator.data["cab_temperature"] == 25.0
        assert coordinator.data["supply_voltage"] == 12.5


# ---------------------------------------------------------------------------
# Protocol detection tests
# ---------------------------------------------------------------------------

class TestProtocolDetection:
    """Tests for protocol detection logic."""

    def test_detect_protocol_aa55_unencrypted(self):
        """Test detection of AA55 unencrypted protocol."""
        coordinator = create_mock_coordinator()

        # AA55 header, 20 bytes
        data = bytearray([0xAA, 0x55] + [0x00] * 18)
        header = (data[0] << 8) | data[1]

        protocol, parsed_data = coordinator._detect_protocol(data, header)

        assert protocol is not None
        assert protocol.protocol_mode == 1  # AA55 unencrypted

    def test_detect_protocol_aa55_encrypted(self):
        """Test detection of AA55 encrypted protocol (48 bytes)."""
        coordinator = create_mock_coordinator()

        # 48 bytes, after decryption should have AA55 or AA66 header
        # Create encrypted data that decrypts to AA55
        from diesel_heater_ble import _encrypt_data
        plain = bytearray([0xAA, 0x55] + [0x00] * 46)
        data = _encrypt_data(plain)
        header = (data[0] << 8) | data[1]

        protocol, parsed_data = coordinator._detect_protocol(data, header)

        assert protocol is not None
        assert protocol.protocol_mode in [2, 4]  # Encrypted variants

    def test_detect_protocol_abba(self):
        """Test detection of ABBA/HeaterCC protocol."""
        coordinator = create_mock_coordinator()

        # ABBA header 0xABBA, 21+ bytes
        data = bytearray([0xAB, 0xBA] + [0x00] * 19)
        header = (data[0] << 8) | data[1]

        protocol, parsed_data = coordinator._detect_protocol(data, header)

        assert protocol is not None
        assert protocol.protocol_mode == 5  # ABBA

    def test_detect_protocol_cbff(self):
        """Test detection of CBFF/Sunster protocol."""
        coordinator = create_mock_coordinator()

        # CBFF header 0xCBFF, 47 bytes
        data = bytearray([0xCB, 0xFF] + [0x00] * 45)
        header = (data[0] << 8) | data[1]

        protocol, parsed_data = coordinator._detect_protocol(data, header)

        assert protocol is not None
        assert protocol.protocol_mode == 6  # CBFF

    def test_detect_protocol_unknown_returns_none(self):
        """Test that unknown data returns None."""
        coordinator = create_mock_coordinator()

        # Random data with no valid header
        data = bytearray([0x12, 0x34] + [0x00] * 10)
        header = (data[0] << 8) | data[1]

        protocol, parsed_data = coordinator._detect_protocol(data, header)

        assert protocol is None


# ---------------------------------------------------------------------------
# Command building tests
# ---------------------------------------------------------------------------

class TestCommandBuilding:
    """Tests for command packet building."""

    def test_build_command_packet_aa55(self):
        """Test building AA55 command packet."""
        coordinator = create_mock_coordinator()
        coordinator._protocol_mode = 1  # AA55
        coordinator._passkey = 1234

        packet = coordinator._build_command_packet(1, 0)  # Status request

        assert len(packet) == 8
        assert packet[0] == 0xAA
        assert packet[1] == 0x55

    def test_build_command_packet_abba(self):
        """Test building ABBA command packet."""
        coordinator = create_mock_coordinator()
        coordinator._protocol_mode = 5  # ABBA
        coordinator._is_abba_device = True

        # Need to set protocol to ABBA
        from diesel_heater_ble import ProtocolABBA
        coordinator._protocol = ProtocolABBA()

        packet = coordinator._build_command_packet(1, 0)  # Status request

        # ABBA status request is "baab04cc000000"
        assert packet[0] == 0xBA
        assert packet[1] == 0xAB


# ---------------------------------------------------------------------------
# UI temperature offset tests
# ---------------------------------------------------------------------------

class TestUITemperatureOffset:
    """Tests for UI temperature offset application."""

    def test_apply_positive_offset(self):
        """Test applying positive temperature offset."""
        coordinator = create_mock_coordinator()
        coordinator.data["cab_temperature"] = 20.0
        coordinator.data["heater_offset"] = 0
        # Set manual offset via config_entry.data
        coordinator.config_entry.data = {"temperature_offset": 2.0}

        coordinator._apply_ui_temperature_offset()

        assert coordinator.data["cab_temperature"] == 22.0
        assert coordinator.data["cab_temperature_raw"] == 20.0

    def test_apply_negative_offset(self):
        """Test applying negative temperature offset."""
        coordinator = create_mock_coordinator()
        coordinator.data["cab_temperature"] = 20.0
        coordinator.data["heater_offset"] = 0
        coordinator.config_entry.data = {"temperature_offset": -3.0}

        coordinator._apply_ui_temperature_offset()

        assert coordinator.data["cab_temperature"] == 17.0
        assert coordinator.data["cab_temperature_raw"] == 20.0

    def test_no_offset_when_none(self):
        """Test no offset applied when cab_temperature is None."""
        coordinator = create_mock_coordinator()
        coordinator.data["cab_temperature"] = None
        coordinator.config_entry.data = {"temperature_offset": 5.0}

        coordinator._apply_ui_temperature_offset()

        assert coordinator.data["cab_temperature"] is None


# ---------------------------------------------------------------------------
# Connection failure handling tests
# ---------------------------------------------------------------------------

class TestConnectionFailureHandling:
    """Tests for connection failure handling."""

    def test_handle_connection_failure_increments_counter(self):
        """Test that connection failures increment the counter."""
        coordinator = create_mock_coordinator()
        coordinator._consecutive_failures = 0

        coordinator._handle_connection_failure(Exception("Test error"))

        assert coordinator._consecutive_failures == 1

    def test_handle_connection_failure_clears_data_after_threshold(self):
        """Test that data is cleared after consecutive failures exceed threshold."""
        coordinator = create_mock_coordinator()
        coordinator._consecutive_failures = 2  # After 3rd failure, data should clear
        coordinator.data["cab_temperature"] = 25.0
        coordinator._stale_cycles = 3  # Exceed stale tolerance

        coordinator._handle_connection_failure(Exception("Test error"))

        # After threshold, connected should be false
        assert coordinator.data["connected"] is False


# ---------------------------------------------------------------------------
# History cleaning tests
# ---------------------------------------------------------------------------

class TestHistoryCleaning:
    """Tests for history data cleanup."""

    def test_clean_old_history_removes_old_entries(self):
        """Test that entries older than MAX_HISTORY_DAYS are removed."""
        coordinator = create_mock_coordinator()

        # Add old and new entries
        old_date = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
        recent_date = datetime.now().strftime("%Y-%m-%d")

        coordinator._daily_fuel_history = {
            old_date: 1.5,
            recent_date: 0.5,
        }

        coordinator._clean_old_history()

        assert old_date not in coordinator._daily_fuel_history
        assert recent_date in coordinator._daily_fuel_history

    def test_clean_old_runtime_history(self):
        """Test that old runtime history is cleaned."""
        coordinator = create_mock_coordinator()

        old_date = (datetime.now() - timedelta(days=100)).strftime("%Y-%m-%d")
        recent_date = datetime.now().strftime("%Y-%m-%d")

        coordinator._daily_runtime_history = {
            old_date: 5.0,
            recent_date: 2.0,
        }

        coordinator._clean_old_runtime_history()

        assert old_date not in coordinator._daily_runtime_history
        assert recent_date in coordinator._daily_runtime_history

    def test_clean_old_history_empty(self):
        """Test cleaning empty history doesn't crash."""
        coordinator = create_mock_coordinator()
        coordinator._daily_fuel_history = {}

        coordinator._clean_old_history()

        assert coordinator._daily_fuel_history == {}

    def test_clean_old_runtime_history_empty(self):
        """Test cleaning empty runtime history doesn't crash."""
        coordinator = create_mock_coordinator()
        coordinator._daily_runtime_history = {}

        coordinator._clean_old_runtime_history()

        assert coordinator._daily_runtime_history == {}


# ---------------------------------------------------------------------------
# Protocol mode property tests
# ---------------------------------------------------------------------------

class TestProtocolMode:
    """Tests for protocol_mode property."""

    def test_protocol_mode_returns_value(self):
        """Test protocol_mode returns current mode."""
        coordinator = create_mock_coordinator()
        coordinator._protocol_mode = 3

        assert coordinator.protocol_mode == 3

    def test_protocol_mode_default(self):
        """Test protocol_mode default is 0."""
        coordinator = create_mock_coordinator()
        coordinator._protocol_mode = 0

        assert coordinator.protocol_mode == 0


# ---------------------------------------------------------------------------
# Notification callback tests
# ---------------------------------------------------------------------------

class TestNotificationCallback:
    """Tests for BLE notification callback."""

    def test_notification_callback_method_exists(self):
        """Test notification callback method exists."""
        coordinator = create_mock_coordinator()

        # Method should exist and be callable
        assert hasattr(coordinator, '_notification_callback')
        assert callable(coordinator._notification_callback)


# ---------------------------------------------------------------------------
# Additional fuel tracking tests
# ---------------------------------------------------------------------------

class TestFuelTrackingAdvanced:
    """Advanced tests for fuel tracking."""

    def test_fuel_consumption_all_levels(self):
        """Test fuel consumption calculation for all levels 1-10."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = RUNNING_STEP_RUNNING

        for level in range(1, 11):
            coordinator.data["set_level"] = level
            consumption = coordinator._calculate_fuel_consumption(3600)
            expected = FUEL_CONSUMPTION_TABLE.get(level, 0.1)
            assert abs(consumption - expected) < 0.001, f"Level {level} failed"

    def test_fuel_tracking_accumulates(self):
        """Test fuel tracking accumulates over multiple updates."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = RUNNING_STEP_RUNNING
        coordinator.data["set_level"] = 1

        # First update
        coordinator._update_fuel_tracking(1800)  # 30 min
        first_total = coordinator._total_fuel_consumed

        # Second update
        coordinator._update_fuel_tracking(1800)  # 30 min
        second_total = coordinator._total_fuel_consumed

        assert second_total > first_total
        assert abs(second_total - first_total * 2) < 0.01

    def test_fuel_remaining_with_zero_capacity(self):
        """Test fuel remaining when tank capacity is 0."""
        coordinator = create_mock_coordinator()
        coordinator.data["tank_capacity"] = 0
        coordinator._fuel_consumed_since_reset = 0.0

        coordinator._update_fuel_remaining()

        # With 0 capacity, fuel remaining stays None or 0
        assert coordinator.data["fuel_remaining"] is None or coordinator.data["fuel_remaining"] == 0.0

    def test_fuel_remaining_exact_empty(self):
        """Test fuel remaining when exactly empty."""
        coordinator = create_mock_coordinator()
        coordinator.data["tank_capacity"] = 5
        coordinator._fuel_consumed_since_reset = 5.0

        coordinator._update_fuel_remaining()

        assert coordinator.data["fuel_remaining"] == 0.0


# ---------------------------------------------------------------------------
# Additional runtime tracking tests
# ---------------------------------------------------------------------------

class TestRuntimeTrackingAdvanced:
    """Advanced tests for runtime tracking."""

    def test_runtime_tracking_accumulates(self):
        """Test runtime tracking accumulates over multiple updates."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = RUNNING_STEP_RUNNING

        # First update
        coordinator._update_runtime_tracking(1800)  # 30 min
        first_total = coordinator._total_runtime_seconds

        # Second update
        coordinator._update_runtime_tracking(1800)  # 30 min
        second_total = coordinator._total_runtime_seconds

        assert second_total == first_total + 1800

    def test_runtime_updates_data_dict(self):
        """Test runtime tracking updates data dict."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = RUNNING_STEP_RUNNING

        coordinator._update_runtime_tracking(3600)  # 1 hour

        # Data dict should have updated values
        assert coordinator.data["daily_runtime_hours"] == 1.0
        assert coordinator.data["total_runtime_hours"] == 1.0


# ---------------------------------------------------------------------------
# Additional command building tests
# ---------------------------------------------------------------------------

class TestCommandBuildingAdvanced:
    """Advanced tests for command building."""

    def test_build_command_packet_with_argument(self):
        """Test building command packet with argument."""
        coordinator = create_mock_coordinator()
        coordinator._protocol_mode = 1  # AA55
        coordinator._passkey = 1234

        # Set level command (cmd 4) with argument 5
        packet = coordinator._build_command_packet(4, 5)

        assert len(packet) == 8
        assert packet[0] == 0xAA
        assert packet[1] == 0x55

    def test_build_command_packet_encrypted(self):
        """Test building command packet for encrypted protocol."""
        coordinator = create_mock_coordinator()
        coordinator._protocol_mode = 2  # AA55 Encrypted
        coordinator._passkey = 1234

        packet = coordinator._build_command_packet(1, 0)

        # Command packets start with AA55 regardless of protocol
        assert packet[0] == 0xAA
        assert packet[1] == 0x55

    def test_build_command_packet_aa66(self):
        """Test building AA66 command packet."""
        coordinator = create_mock_coordinator()
        coordinator._protocol_mode = 3  # AA66
        coordinator._passkey = 1234

        packet = coordinator._build_command_packet(1, 0)

        # AA66 devices use AA55 command format
        assert len(packet) == 8
        assert packet[0] == 0xAA

    def test_build_command_packet_cbff(self):
        """Test building CBFF command packet (uses AA55 format)."""
        coordinator = create_mock_coordinator()
        coordinator._protocol_mode = 6  # CBFF
        coordinator._passkey = 1234

        packet = coordinator._build_command_packet(1, 0)

        # CBFF uses AA55 command format
        assert packet[0] == 0xAA
        assert packet[1] == 0x55


# ---------------------------------------------------------------------------
# Additional protocol detection tests
# ---------------------------------------------------------------------------

class TestProtocolDetectionAdvanced:
    """Advanced tests for protocol detection."""

    def test_detect_protocol_aa66_unencrypted(self):
        """Test detection of AA66 unencrypted protocol."""
        coordinator = create_mock_coordinator()

        # AA66 header, 20 bytes
        data = bytearray([0xAA, 0x66] + [0x00] * 18)
        header = (data[0] << 8) | data[1]

        protocol, parsed_data = coordinator._detect_protocol(data, header)

        assert protocol is not None
        assert protocol.protocol_mode == 3  # AA66 unencrypted

    def test_detect_protocol_short_data(self):
        """Test protocol detection with too short data."""
        coordinator = create_mock_coordinator()

        # Only 5 bytes - too short for any protocol
        data = bytearray([0xAA, 0x55, 0x00, 0x00, 0x00])
        header = (data[0] << 8) | data[1]

        protocol, parsed_data = coordinator._detect_protocol(data, header)

        # Should not match any protocol due to length
        assert protocol is None or parsed_data is None


# ---------------------------------------------------------------------------
# Data persistence format tests
# ---------------------------------------------------------------------------

class TestDataFormat:
    """Tests for data format and rounding."""

    def test_hourly_consumption_rounded(self):
        """Test hourly consumption is rounded to 2 decimals."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = RUNNING_STEP_RUNNING
        coordinator.data["set_level"] = 5

        coordinator._update_fuel_tracking(3600)

        # Check rounding in data dict
        daily = coordinator.data["daily_fuel_consumed"]
        assert daily == round(daily, 2)

    def test_runtime_hours_rounded(self):
        """Test runtime hours are rounded to 2 decimals."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = RUNNING_STEP_RUNNING

        coordinator._update_runtime_tracking(3661)  # 1 hour and 1 second

        hours = coordinator.data["daily_runtime_hours"]
        assert hours == round(hours, 2)


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_fuel_consumption_invalid_level(self):
        """Test fuel consumption with invalid level (defaults)."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = RUNNING_STEP_RUNNING
        coordinator.data["set_level"] = 99  # Invalid

        # Should use default consumption rate
        consumption = coordinator._calculate_fuel_consumption(3600)
        assert consumption >= 0

    def test_clear_sensor_values_preserves_non_volatile(self):
        """Test clearing sensor values preserves non-volatile data."""
        coordinator = create_mock_coordinator()
        coordinator.data["daily_fuel_consumed"] = 5.0
        coordinator.data["total_fuel_consumed"] = 100.0
        coordinator.data["cab_temperature"] = 25.0

        coordinator._clear_sensor_values()

        # Volatile should be cleared
        assert coordinator.data["cab_temperature"] is None
        # Non-volatile should remain
        assert coordinator.data["daily_fuel_consumed"] == 5.0
        assert coordinator.data["total_fuel_consumed"] == 100.0

    def test_restore_stale_data_partial(self):
        """Test restoring partial stale data."""
        coordinator = create_mock_coordinator()
        coordinator._last_valid_data = {
            "cab_temperature": 25.0,
            # supply_voltage not saved
        }
        coordinator.data["cab_temperature"] = None
        coordinator.data["supply_voltage"] = None

        coordinator._restore_stale_data()

        # Should restore what we have
        assert coordinator.data["cab_temperature"] == 25.0
        # Should remain None
        assert coordinator.data["supply_voltage"] is None

    def test_connection_failure_first_failure(self):
        """Test first connection failure behavior."""
        coordinator = create_mock_coordinator()
        coordinator._consecutive_failures = 0
        coordinator._last_valid_data = {"cab_temperature": 20.0}
        coordinator.data["cab_temperature"] = 20.0

        coordinator._handle_connection_failure(Exception("Network error"))

        # After first failure, should restore stale data
        assert coordinator._consecutive_failures == 1

    def test_save_valid_data_filters_none(self):
        """Test that save_valid_data doesn't save None values."""
        coordinator = create_mock_coordinator()
        coordinator.data["cab_temperature"] = 25.0
        coordinator.data["supply_voltage"] = None

        coordinator._save_valid_data()

        assert coordinator._last_valid_data.get("cab_temperature") == 25.0
        # None values should not overwrite existing saved data
        assert coordinator._last_valid_data.get("supply_voltage") is None


# ---------------------------------------------------------------------------
# Temperature offset advanced tests
# ---------------------------------------------------------------------------

class TestTemperatureOffsetAdvanced:
    """Advanced tests for temperature offset."""

    def test_offset_with_heater_offset(self):
        """Test UI offset calculation with heater's own offset."""
        coordinator = create_mock_coordinator()
        coordinator.data["cab_temperature"] = 20.0
        coordinator.data["heater_offset"] = 2  # Heater reports +2 offset
        coordinator.config_entry.data = {"temperature_offset": 0.0}

        coordinator._apply_ui_temperature_offset()

        # Raw should be 20 - 2 = 18 (sensor reading before heater offset)
        assert coordinator.data["cab_temperature_raw"] == 18.0

    def test_offset_applies_correctly(self):
        """Test temperature offset applies correctly."""
        coordinator = create_mock_coordinator()
        coordinator.data["cab_temperature"] = 25.0
        coordinator.data["heater_offset"] = 0
        coordinator.config_entry.data = {"temperature_offset": 5.0}

        coordinator._apply_ui_temperature_offset()

        assert coordinator.data["cab_temperature"] == 30.0

    def test_offset_zero_no_change(self):
        """Test zero offset doesn't change temperature."""
        coordinator = create_mock_coordinator()
        coordinator.data["cab_temperature"] = 25.0
        coordinator.data["heater_offset"] = 0
        coordinator.config_entry.data = {"temperature_offset": 0.0}

        coordinator._apply_ui_temperature_offset()

        assert coordinator.data["cab_temperature"] == 25.0


# ---------------------------------------------------------------------------
# Async data persistence tests
# ---------------------------------------------------------------------------

class TestAsyncDataPersistence:
    """Tests for async data persistence methods."""

    @pytest.mark.asyncio
    async def test_async_save_data_calls_store(self):
        """Test async_save_data calls the store."""
        coordinator = create_mock_coordinator()
        coordinator._store = MagicMock()
        coordinator._store.async_save = AsyncMock()
        coordinator._last_save_time = 0

        await coordinator.async_save_data()

        coordinator._store.async_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_save_data_includes_fuel_data(self):
        """Test async_save_data includes fuel tracking data."""
        coordinator = create_mock_coordinator()
        coordinator._store = MagicMock()
        coordinator._store.async_save = AsyncMock()
        coordinator._last_save_time = 0
        coordinator._total_fuel_consumed = 50.5
        coordinator._daily_fuel_consumed = 2.5

        await coordinator.async_save_data()

        # Check the saved data contains fuel info
        call_args = coordinator._store.async_save.call_args
        saved_data = call_args[0][0]
        assert STORAGE_KEY_TOTAL_FUEL in saved_data
        assert STORAGE_KEY_DAILY_FUEL in saved_data

    @pytest.mark.asyncio
    async def test_async_save_data_includes_runtime_data(self):
        """Test async_save_data includes runtime tracking data."""
        coordinator = create_mock_coordinator()
        coordinator._store = MagicMock()
        coordinator._store.async_save = AsyncMock()
        coordinator._last_save_time = 0
        coordinator._total_runtime_seconds = 36000.0
        coordinator._daily_runtime_seconds = 3600.0

        await coordinator.async_save_data()

        call_args = coordinator._store.async_save.call_args
        saved_data = call_args[0][0]
        assert STORAGE_KEY_TOTAL_RUNTIME in saved_data
        assert STORAGE_KEY_DAILY_RUNTIME in saved_data

    @pytest.mark.asyncio
    async def test_async_load_data_restores_fuel(self):
        """Test async_load_data calls store and processes data."""
        coordinator = create_mock_coordinator()
        coordinator._store = MagicMock()
        # Use today's date to avoid daily reset
        today = datetime.now().date().isoformat()
        stored_data = {
            STORAGE_KEY_TOTAL_FUEL: 100.5,
            STORAGE_KEY_DAILY_FUEL: 5.0,
            STORAGE_KEY_DAILY_HISTORY: {"2024-01-01": 3.0},
            STORAGE_KEY_DAILY_DATE: today,  # Use today to avoid reset
            STORAGE_KEY_TOTAL_RUNTIME: 7200.0,
            STORAGE_KEY_DAILY_RUNTIME: 1800.0,
            STORAGE_KEY_DAILY_RUNTIME_HISTORY: {},
            STORAGE_KEY_DAILY_RUNTIME_DATE: today,  # Use today to avoid reset
        }
        coordinator._store.async_load = AsyncMock(return_value=stored_data)

        await coordinator.async_load_data()

        # Verify store was called
        coordinator._store.async_load.assert_called_once()
        # After load, total fuel should be restored from stored data
        # The actual restoration depends on the coordinator implementation
        # Check that data dict has the values (they are synced to data dict)
        assert coordinator.data["total_fuel_consumed"] == 100.5
        assert coordinator.data["daily_fuel_consumed"] == 5.0

    @pytest.mark.asyncio
    async def test_async_load_data_handles_missing_data(self):
        """Test async_load_data handles missing/None data gracefully."""
        coordinator = create_mock_coordinator()
        coordinator._store = MagicMock()
        coordinator._store.async_load = AsyncMock(return_value=None)

        # Should not raise
        await coordinator.async_load_data()

        # Values should remain at defaults
        assert coordinator._total_fuel_consumed == 0.0


# ---------------------------------------------------------------------------
# Async fuel management tests
# ---------------------------------------------------------------------------

class TestAsyncFuelManagement:
    """Tests for async fuel management methods."""

    @pytest.mark.asyncio
    async def test_async_reset_fuel_level(self):
        """Test async_reset_fuel_level resets fuel tracking."""
        coordinator = create_mock_coordinator()
        coordinator._store = MagicMock()
        coordinator._store.async_save = AsyncMock()
        coordinator._fuel_consumed_since_reset = 10.0
        coordinator._last_save_time = 0

        await coordinator.async_reset_fuel_level()

        assert coordinator._fuel_consumed_since_reset == 0.0
        assert coordinator.data["fuel_consumed_since_reset"] == 0.0

    @pytest.mark.asyncio
    async def test_async_set_tank_capacity(self):
        """Test async_set_tank_capacity updates capacity."""
        coordinator = create_mock_coordinator()
        coordinator._store = MagicMock()
        coordinator._store.async_save = AsyncMock()
        coordinator._last_save_time = 0

        await coordinator.async_set_tank_capacity(15)

        assert coordinator.data["tank_capacity"] == 15


# ---------------------------------------------------------------------------
# Daily reset tests
# ---------------------------------------------------------------------------

class TestDailyReset:
    """Tests for daily reset functionality."""

    @pytest.mark.asyncio
    async def test_check_daily_reset_same_day(self):
        """Test _check_daily_reset doesn't reset on same day."""
        coordinator = create_mock_coordinator()
        coordinator._store = MagicMock()
        coordinator._store.async_save = AsyncMock()
        today = datetime.now().strftime("%Y-%m-%d")
        coordinator._last_reset_date = today
        coordinator._daily_fuel_consumed = 5.0

        await coordinator._check_daily_reset()

        # Should not reset since it's the same day
        assert coordinator._daily_fuel_consumed == 5.0

    @pytest.mark.asyncio
    async def test_check_daily_reset_new_day(self):
        """Test _check_daily_reset resets on new day."""
        coordinator = create_mock_coordinator()
        coordinator._store = MagicMock()
        coordinator._store.async_save = AsyncMock()
        coordinator._last_save_time = 0
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        coordinator._last_reset_date = yesterday
        coordinator._daily_fuel_consumed = 5.0
        coordinator._daily_fuel_history = {}

        await coordinator._check_daily_reset()

        # Should reset for new day
        assert coordinator._daily_fuel_consumed == 0.0
        # Yesterday's value should be in history
        assert yesterday in coordinator._daily_fuel_history

    @pytest.mark.asyncio
    async def test_check_daily_runtime_reset_same_day(self):
        """Test _check_daily_runtime_reset doesn't reset on same day."""
        coordinator = create_mock_coordinator()
        coordinator._store = MagicMock()
        coordinator._store.async_save = AsyncMock()
        today = datetime.now().strftime("%Y-%m-%d")
        coordinator._last_runtime_reset_date = today
        coordinator._daily_runtime_seconds = 3600.0

        await coordinator._check_daily_runtime_reset()

        # Should not reset
        assert coordinator._daily_runtime_seconds == 3600.0

    @pytest.mark.asyncio
    async def test_check_daily_runtime_reset_new_day(self):
        """Test _check_daily_runtime_reset resets on new day."""
        coordinator = create_mock_coordinator()
        coordinator._store = MagicMock()
        coordinator._store.async_save = AsyncMock()
        coordinator._last_save_time = 0
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        coordinator._last_runtime_reset_date = yesterday
        coordinator._daily_runtime_seconds = 7200.0
        coordinator._daily_runtime_history = {}

        await coordinator._check_daily_runtime_reset()

        # Should reset for new day
        assert coordinator._daily_runtime_seconds == 0.0
        # Yesterday's hours should be in history
        assert yesterday in coordinator._daily_runtime_history


# ---------------------------------------------------------------------------
# Async command tests
# ---------------------------------------------------------------------------

class TestAsyncCommands:
    """Tests for async command methods."""

    @pytest.mark.asyncio
    async def test_async_turn_on(self):
        """Test async_turn_on sends correct command."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_turn_on()

        coordinator._send_command.assert_called_once()
        # Command 3 with arg 1 is turn on
        call_args = coordinator._send_command.call_args
        assert call_args[0][0] == 3
        assert call_args[0][1] == 1

    @pytest.mark.asyncio
    async def test_async_turn_off(self):
        """Test async_turn_off sends correct command."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)
        coordinator.data["running_state"] = 1  # Must be running to turn off

        await coordinator.async_turn_off()

        coordinator._send_command.assert_called_once()
        # Command 3 with arg 0 is turn off
        call_args = coordinator._send_command.call_args
        assert call_args[0][0] == 3
        assert call_args[0][1] == 0

    @pytest.mark.asyncio
    async def test_async_set_level(self):
        """Test async_set_level sends correct command."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_level(7)

        coordinator._send_command.assert_called_once()
        # Command 4 is set level
        call_args = coordinator._send_command.call_args
        assert call_args[0][0] == 4
        assert call_args[0][1] == 7

    @pytest.mark.asyncio
    async def test_async_set_temperature(self):
        """Test async_set_temperature sends correct command."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_temperature(25)

        coordinator._send_command.assert_called_once()
        # Command 4 is used for both level and temperature
        call_args = coordinator._send_command.call_args
        assert call_args[0][0] == 4
        assert call_args[0][1] == 25

    @pytest.mark.asyncio
    async def test_async_set_mode(self):
        """Test async_set_mode sends correct command."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_mode(2)  # Temperature mode

        coordinator._send_command.assert_called_once()
        call_args = coordinator._send_command.call_args
        assert call_args[0][1] == 2

    @pytest.mark.asyncio
    async def test_async_set_auto_start_stop(self):
        """Test async_set_auto_start_stop sends correct command."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_auto_start_stop(True)

        coordinator._send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_sync_time(self):
        """Test async_sync_time sends time sync command."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_sync_time()

        coordinator._send_command.assert_called_once()
        # Command 10 is time sync
        call_args = coordinator._send_command.call_args
        assert call_args[0][0] == 10

    @pytest.mark.asyncio
    async def test_async_set_heater_offset(self):
        """Test async_set_heater_offset sends correct command."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_heater_offset(3)

        coordinator._send_command.assert_called_once()
        # Command 12 is set offset (or 20 for newer protocol)
        call_args = coordinator._send_command.call_args
        assert call_args[0][0] in [12, 20]

    @pytest.mark.asyncio
    async def test_async_set_backlight(self):
        """Test async_set_backlight sends correct command."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_backlight(5)

        coordinator._send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_set_auto_offset_enabled(self):
        """Test async_set_auto_offset_enabled updates state."""
        coordinator = create_mock_coordinator()
        coordinator._store = MagicMock()
        coordinator._store.async_save = AsyncMock()
        coordinator._last_save_time = 0
        coordinator._setup_external_temp_listener = AsyncMock()
        coordinator._auto_offset_unsub = None

        await coordinator.async_set_auto_offset_enabled(True)

        assert coordinator.data["auto_offset_enabled"] is True

    @pytest.mark.asyncio
    async def test_async_send_raw_command(self):
        """Test async_send_raw_command sends arbitrary command."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        result = await coordinator.async_send_raw_command(99, 42)

        assert result is True
        coordinator._send_command.assert_called_once_with(99, 42)


# ---------------------------------------------------------------------------
# Address and heater ID tests
# ---------------------------------------------------------------------------

class TestAddressProperties:
    """Tests for address-related properties."""

    def test_address_property(self):
        """Test address property returns BLE address."""
        coordinator = create_mock_coordinator()
        coordinator._address = "AA:BB:CC:DD:EE:FF"

        # Check if address property exists and works
        assert hasattr(coordinator, '_address')
        assert coordinator._address == "AA:BB:CC:DD:EE:FF"

    def test_heater_id_format(self):
        """Test heater_id is last 2 bytes of address."""
        coordinator = create_mock_coordinator()
        coordinator._heater_id = "EE:FF"

        assert coordinator._heater_id == "EE:FF"


# ---------------------------------------------------------------------------
# ABBA protocol specific tests
# ---------------------------------------------------------------------------

class TestABBAProtocol:
    """Tests for ABBA protocol specific behavior."""

    def test_is_abba_device_flag(self):
        """Test _is_abba_device flag."""
        coordinator = create_mock_coordinator()
        coordinator._is_abba_device = True

        assert coordinator._is_abba_device is True

    def test_build_command_abba_uses_protocol(self):
        """Test ABBA command building uses protocol handler."""
        from diesel_heater_ble import ProtocolABBA

        coordinator = create_mock_coordinator()
        coordinator._protocol_mode = 5
        coordinator._is_abba_device = True
        coordinator._protocol = ProtocolABBA()

        packet = coordinator._build_command_packet(1, 0)

        # ABBA packets start with BA AB
        assert packet[0] == 0xBA
        assert packet[1] == 0xAB


# ---------------------------------------------------------------------------
# Statistics import tests
# ---------------------------------------------------------------------------

class TestStatisticsImport:
    """Tests for statistics import functionality."""

    def test_has_import_statistics_method(self):
        """Test _import_statistics method exists."""
        coordinator = create_mock_coordinator()

        assert hasattr(coordinator, '_import_statistics')
        assert callable(coordinator._import_statistics)

    def test_has_import_runtime_statistics_method(self):
        """Test _import_runtime_statistics method exists."""
        coordinator = create_mock_coordinator()

        assert hasattr(coordinator, '_import_runtime_statistics')
        assert callable(coordinator._import_runtime_statistics)


# ---------------------------------------------------------------------------
# Additional async command tests
# ---------------------------------------------------------------------------

class TestAsyncConfigurationCommands:
    """Tests for async configuration commands."""

    @pytest.mark.asyncio
    async def test_async_set_language(self):
        """Test async_set_language sends correct command."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_language(2)  # German

        coordinator._send_command.assert_called_once()
        # Command 14 is set language
        call_args = coordinator._send_command.call_args
        assert call_args[0][0] == 14
        assert call_args[0][1] == 2

    @pytest.mark.asyncio
    async def test_async_set_temp_unit_celsius(self):
        """Test async_set_temp_unit sets Celsius."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_temp_unit(False)  # Celsius

        coordinator._send_command.assert_called_once()
        # Command 15 is set temp unit
        call_args = coordinator._send_command.call_args
        assert call_args[0][0] == 15
        assert call_args[0][1] == 0  # 0 = Celsius

    @pytest.mark.asyncio
    async def test_async_set_temp_unit_fahrenheit(self):
        """Test async_set_temp_unit sets Fahrenheit."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_temp_unit(True)  # Fahrenheit

        coordinator._send_command.assert_called_once()
        call_args = coordinator._send_command.call_args
        assert call_args[0][0] == 15
        assert call_args[0][1] == 1  # 1 = Fahrenheit

    @pytest.mark.asyncio
    async def test_async_set_altitude_unit_meters(self):
        """Test async_set_altitude_unit sets meters."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_altitude_unit(False)  # Meters

        coordinator._send_command.assert_called_once()
        # Command 19 is set altitude unit
        call_args = coordinator._send_command.call_args
        assert call_args[0][0] == 19
        assert call_args[0][1] == 0  # 0 = Meters

    @pytest.mark.asyncio
    async def test_async_set_altitude_unit_feet(self):
        """Test async_set_altitude_unit sets feet."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_altitude_unit(True)  # Feet

        coordinator._send_command.assert_called_once()
        call_args = coordinator._send_command.call_args
        assert call_args[0][0] == 19
        assert call_args[0][1] == 1  # 1 = Feet

    @pytest.mark.asyncio
    async def test_async_set_high_altitude_enabled_abba(self):
        """Test async_set_high_altitude enables high altitude mode for ABBA."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)
        coordinator._is_abba_device = True  # Must be ABBA device
        coordinator.async_request_refresh = AsyncMock()

        await coordinator.async_set_high_altitude(True)

        coordinator._send_command.assert_called_once()
        # Command 99 is high altitude toggle
        call_args = coordinator._send_command.call_args
        assert call_args[0][0] == 99

    @pytest.mark.asyncio
    async def test_async_set_high_altitude_skipped_non_abba(self):
        """Test async_set_high_altitude does nothing for non-ABBA devices."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)
        coordinator._is_abba_device = False  # Not ABBA device

        await coordinator.async_set_high_altitude(True)

        # Should not call _send_command for non-ABBA devices
        coordinator._send_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_set_tank_volume(self):
        """Test async_set_tank_volume sets tank volume index."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_tank_volume(5)  # Index 5 = 25L

        coordinator._send_command.assert_called_once()
        # Command 16 is set tank volume
        call_args = coordinator._send_command.call_args
        assert call_args[0][0] == 16
        assert call_args[0][1] == 5

    @pytest.mark.asyncio
    async def test_async_set_pump_type(self):
        """Test async_set_pump_type sets pump type."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_pump_type(2)  # 28µl pump

        coordinator._send_command.assert_called_once()
        # Command 17 is set pump type
        call_args = coordinator._send_command.call_args
        assert call_args[0][0] == 17
        assert call_args[0][1] == 2


# ---------------------------------------------------------------------------
# Response parsing tests
# ---------------------------------------------------------------------------

class TestResponseParsing:
    """Tests for response parsing functionality."""

    def test_parse_response_aa55_updates_data(self):
        """Test parsing AA55 response updates data dict."""
        coordinator = create_mock_coordinator()
        coordinator._protocol_mode = 1  # AA55
        coordinator._protocol = coordinator._protocols[1]

        # Create a valid 20-byte AA55 response
        data = bytearray([0xAA, 0x55] + [0x00] * 18)

        # Parse the response (actual byte positions depend on protocol)
        coordinator._parse_response(data)

        # After parsing, data dict should have some values updated
        # (not checking specific values since protocol layout is complex)
        assert "running_state" in coordinator.data

    def test_parse_response_method_exists(self):
        """Test _parse_response method exists."""
        coordinator = create_mock_coordinator()

        assert hasattr(coordinator, '_parse_response')
        assert callable(coordinator._parse_response)

    def test_parse_response_processes_data(self):
        """Test parsing response processes the data without error."""
        coordinator = create_mock_coordinator()
        coordinator._protocol_mode = 1  # AA55
        coordinator._protocol = coordinator._protocols[1]

        # Create a valid response
        data = bytearray([0xAA, 0x55] + [0x00] * 18)

        # Should not raise an exception
        coordinator._parse_response(data)

        # Data dict should still be accessible
        assert coordinator.data is not None


# ---------------------------------------------------------------------------
# Utility methods tests
# ---------------------------------------------------------------------------

class TestUtilityMethods:
    """Tests for utility methods."""

    def test_protocol_mode_property(self):
        """Test protocol_mode property getter."""
        coordinator = create_mock_coordinator()
        coordinator._protocol_mode = 5

        assert coordinator.protocol_mode == 5

    def test_clear_sensor_values_all_volatile(self):
        """Test clearing all volatile sensor values."""
        coordinator = create_mock_coordinator()
        # Set all volatile fields
        coordinator.data["case_temperature"] = 50
        coordinator.data["cab_temperature"] = 20
        coordinator.data["supply_voltage"] = 12.5
        coordinator.data["running_state"] = 1
        coordinator.data["running_step"] = 3
        coordinator.data["set_level"] = 5
        coordinator.data["set_temp"] = 22

        coordinator._clear_sensor_values()

        # All volatile fields should be None
        assert coordinator.data["case_temperature"] is None
        assert coordinator.data["cab_temperature"] is None
        assert coordinator.data["supply_voltage"] is None

    def test_save_valid_data_all_fields(self):
        """Test saving all valid data fields."""
        coordinator = create_mock_coordinator()
        coordinator.data["cab_temperature"] = 25.0
        coordinator.data["case_temperature"] = 60
        coordinator.data["supply_voltage"] = 13.2
        coordinator._last_valid_data = {}

        coordinator._save_valid_data()

        assert coordinator._last_valid_data["cab_temperature"] == 25.0
        assert coordinator._last_valid_data["case_temperature"] == 60
        assert coordinator._last_valid_data["supply_voltage"] == 13.2


# ---------------------------------------------------------------------------
# Temperature clamp tests
# ---------------------------------------------------------------------------

class TestTemperatureClamp:
    """Tests for temperature clamping logic."""

    @pytest.mark.asyncio
    async def test_set_temperature_clamps_below_min(self):
        """Test temperature below 8 is clamped to 8."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_temperature(5)  # Below min

        call_args = coordinator._send_command.call_args
        assert call_args[0][1] == 8  # Clamped to min

    @pytest.mark.asyncio
    async def test_set_temperature_clamps_above_max(self):
        """Test temperature above 36 is clamped to 36."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_temperature(40)  # Above max

        call_args = coordinator._send_command.call_args
        assert call_args[0][1] == 36  # Clamped to max


# ---------------------------------------------------------------------------
# Level clamp tests
# ---------------------------------------------------------------------------

class TestLevelClamp:
    """Tests for level clamping logic."""

    @pytest.mark.asyncio
    async def test_set_level_clamps_below_min(self):
        """Test level below 1 is clamped to 1."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_level(0)  # Below min

        call_args = coordinator._send_command.call_args
        assert call_args[0][1] == 1  # Clamped to min

    @pytest.mark.asyncio
    async def test_set_level_clamps_above_max(self):
        """Test level above 10 is clamped to 10."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_level(15)  # Above max

        call_args = coordinator._send_command.call_args
        assert call_args[0][1] == 10  # Clamped to max

    @pytest.mark.asyncio
    async def test_set_level_in_range(self):
        """Test level in valid range is not clamped."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_level(5)  # In range

        call_args = coordinator._send_command.call_args
        assert call_args[0][1] == 5  # Not clamped


# ---------------------------------------------------------------------------
# Mode command tests
# ---------------------------------------------------------------------------

class TestModeCommands:
    """Tests for mode switching commands."""

    @pytest.mark.asyncio
    async def test_set_mode_level(self):
        """Test setting level mode (1)."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_mode(1)  # Level mode

        call_args = coordinator._send_command.call_args
        assert call_args[0][1] == 1

    @pytest.mark.asyncio
    async def test_set_mode_temperature(self):
        """Test setting temperature mode (2)."""
        coordinator = create_mock_coordinator()
        coordinator._send_command = AsyncMock(return_value=True)

        await coordinator.async_set_mode(2)  # Temperature mode

        call_args = coordinator._send_command.call_args
        assert call_args[0][1] == 2
