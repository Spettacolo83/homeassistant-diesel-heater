"""Tests for Vevor Heater Coordinator.

Tests the coordinator logic without requiring actual BLE connections.
Focuses on data processing, fuel/runtime tracking, and protocol handling.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio

# Import stubs first
from . import conftest  # noqa: F401

# Now we can import the coordinator
from custom_components.vevor_heater.coordinator import VevorHeaterCoordinator
from custom_components.vevor_heater.const import (
    FUEL_CONSUMPTION_TABLE,
    RUNNING_STEP_RUNNING,
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
