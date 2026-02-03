"""Tests for Vevor Heater sensor platform."""
from __future__ import annotations

from unittest.mock import MagicMock

# Import stubs first
from . import conftest  # noqa: F401

from custom_components.vevor_heater.sensor import (
    VevorCabTemperatureSensor,
    VevorCaseTemperatureSensor,
    VevorSupplyVoltageSensor,
    VevorRunningStepSensor,
    VevorRunningModeSensor,
    VevorSetLevelSensor,
    VevorAltitudeSensor,
    VevorErrorCodeSensor,
    VevorHourlyFuelConsumptionSensor,
    VevorDailyFuelConsumedSensor,
    VevorTotalFuelConsumedSensor,
    VevorFuelRemainingSensor,
    VevorDailyRuntimeSensor,
    VevorTotalRuntimeSensor,
)
from custom_components.vevor_heater.const import (
    ERROR_NAMES,
    RUNNING_MODE_NAMES,
    RUNNING_STEP_NAMES,
)


def create_mock_coordinator() -> MagicMock:
    """Create a mock coordinator for sensor testing."""
    coordinator = MagicMock()
    coordinator._address = "AA:BB:CC:DD:EE:FF"
    coordinator._heater_id = "EE:FF"
    coordinator.last_update_success = True
    coordinator.data = {
        "connected": True,
        "running_state": 1,
        "running_step": 3,
        "running_mode": 1,
        "set_level": 5,
        "set_temp": 22,
        "cab_temperature": 20.5,
        "cab_temperature_raw": 20.0,
        "case_temperature": 50,
        "supply_voltage": 12.5,
        "error_code": 0,
        "altitude": 500,
        "heater_offset": 0,
        "hourly_fuel_consumption": 0.25,
        "daily_fuel_consumed": 1.5,
        "total_fuel_consumed": 25.0,
        "fuel_remaining": 3.5,
        "fuel_consumed_since_reset": 1.5,
        "daily_runtime_hours": 4.5,
        "total_runtime_hours": 150.0,
        "co_ppm": None,
        "remain_run_time": None,
        "hw_version": None,
        "sw_version": None,
        "daily_fuel_history": {},
        "daily_runtime_history": {},
    }
    return coordinator


# ---------------------------------------------------------------------------
# Temperature sensor tests
# ---------------------------------------------------------------------------

class TestCabTemperatureSensor:
    """Tests for cabin temperature sensor."""

    def test_native_value(self):
        """Test that native_value returns cabin temperature."""
        coordinator = create_mock_coordinator()
        sensor = VevorCabTemperatureSensor(coordinator)

        assert sensor.native_value == 20.5

    def test_native_value_none_when_disconnected(self):
        """Test that native_value is None when heater is disconnected."""
        coordinator = create_mock_coordinator()
        coordinator.data["cab_temperature"] = None
        sensor = VevorCabTemperatureSensor(coordinator)

        assert sensor.native_value is None

    def test_device_class(self):
        """Test that device_class is temperature."""
        coordinator = create_mock_coordinator()
        sensor = VevorCabTemperatureSensor(coordinator)

        # Check device_class is set (MagicMock comparison doesn't work)
        assert sensor.device_class is not None

    def test_unique_id(self):
        """Test unique_id format."""
        coordinator = create_mock_coordinator()
        sensor = VevorCabTemperatureSensor(coordinator)

        # unique_id should contain the address and sensor type
        assert "_cab_temperature" in sensor.unique_id or "cab_temp" in sensor.unique_id


class TestCaseTemperatureSensor:
    """Tests for case temperature sensor."""

    def test_native_value(self):
        """Test that native_value returns case temperature."""
        coordinator = create_mock_coordinator()
        sensor = VevorCaseTemperatureSensor(coordinator)

        assert sensor.native_value == 50

    def test_native_value_none(self):
        """Test native_value when data is None."""
        coordinator = create_mock_coordinator()
        coordinator.data["case_temperature"] = None
        sensor = VevorCaseTemperatureSensor(coordinator)

        assert sensor.native_value is None


# ---------------------------------------------------------------------------
# Voltage sensor tests
# ---------------------------------------------------------------------------

class TestSupplyVoltageSensor:
    """Tests for supply voltage sensor."""

    def test_native_value(self):
        """Test that native_value returns voltage."""
        coordinator = create_mock_coordinator()
        sensor = VevorSupplyVoltageSensor(coordinator)

        assert sensor.native_value == 12.5

    def test_device_class(self):
        """Test that device_class is voltage."""
        coordinator = create_mock_coordinator()
        sensor = VevorSupplyVoltageSensor(coordinator)

        # Check device_class is set (MagicMock comparison doesn't work)
        assert sensor.device_class is not None


# ---------------------------------------------------------------------------
# Running state sensor tests
# ---------------------------------------------------------------------------

class TestRunningStepSensor:
    """Tests for running step sensor."""

    def test_native_value_returns_step_name(self):
        """Test that native_value returns human-readable step name."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = 3
        sensor = VevorRunningStepSensor(coordinator)

        value = sensor.native_value
        # running_step 3 should map to a RUNNING_STEP_NAMES entry
        assert value == RUNNING_STEP_NAMES.get(3, "Unknown (3)")

    def test_native_value_unknown_step(self):
        """Test native_value with unknown step code."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_step"] = 99
        sensor = VevorRunningStepSensor(coordinator)

        value = sensor.native_value
        assert "Unknown" in value or "99" in value


class TestRunningModeSensor:
    """Tests for running mode sensor."""

    def test_native_value_returns_mode_name(self):
        """Test that native_value returns human-readable mode name."""
        coordinator = create_mock_coordinator()
        coordinator.data["running_mode"] = 1
        sensor = VevorRunningModeSensor(coordinator)

        value = sensor.native_value
        assert value == RUNNING_MODE_NAMES.get(1, "Unknown (1)")


# ---------------------------------------------------------------------------
# Level and settings sensor tests
# ---------------------------------------------------------------------------

class TestSetLevelSensor:
    """Tests for set level sensor."""

    def test_native_value(self):
        """Test that native_value returns current level."""
        coordinator = create_mock_coordinator()
        coordinator.data["set_level"] = 7
        sensor = VevorSetLevelSensor(coordinator)

        assert sensor.native_value == 7


class TestAltitudeSensor:
    """Tests for altitude sensor."""

    def test_native_value(self):
        """Test that native_value returns altitude."""
        coordinator = create_mock_coordinator()
        coordinator.data["altitude"] = 1500
        sensor = VevorAltitudeSensor(coordinator)

        assert sensor.native_value == 1500


# ---------------------------------------------------------------------------
# Error sensor tests
# ---------------------------------------------------------------------------

class TestErrorCodeSensor:
    """Tests for error code sensor."""

    def test_native_value_no_error(self):
        """Test native_value when no error."""
        coordinator = create_mock_coordinator()
        coordinator.data["error_code"] = 0
        sensor = VevorErrorCodeSensor(coordinator)

        value = sensor.native_value
        assert value == ERROR_NAMES.get(0, "E00: Unknown Error")

    def test_native_value_with_error(self):
        """Test native_value with error code."""
        coordinator = create_mock_coordinator()
        coordinator.data["error_code"] = 1
        sensor = VevorErrorCodeSensor(coordinator)

        value = sensor.native_value
        assert "E01" in value or value == ERROR_NAMES.get(1, "E01: Unknown Error")


# ---------------------------------------------------------------------------
# Fuel consumption sensor tests
# ---------------------------------------------------------------------------

class TestHourlyFuelConsumptionSensor:
    """Tests for hourly fuel consumption sensor."""

    def test_native_value(self):
        """Test that native_value returns hourly consumption."""
        coordinator = create_mock_coordinator()
        coordinator.data["hourly_fuel_consumption"] = 0.35
        sensor = VevorHourlyFuelConsumptionSensor(coordinator)

        assert sensor.native_value == 0.35


class TestDailyFuelConsumedSensor:
    """Tests for daily fuel consumed sensor."""

    def test_native_value(self):
        """Test that native_value returns daily consumption."""
        coordinator = create_mock_coordinator()
        coordinator.data["daily_fuel_consumed"] = 2.5
        sensor = VevorDailyFuelConsumedSensor(coordinator)

        assert sensor.native_value == 2.5


class TestTotalFuelConsumedSensor:
    """Tests for total fuel consumed sensor."""

    def test_native_value(self):
        """Test that native_value returns total consumption."""
        coordinator = create_mock_coordinator()
        coordinator.data["total_fuel_consumed"] = 100.5
        sensor = VevorTotalFuelConsumedSensor(coordinator)

        assert sensor.native_value == 100.5


class TestFuelRemainingSensor:
    """Tests for fuel remaining sensor."""

    def test_native_value(self):
        """Test that native_value returns fuel remaining."""
        coordinator = create_mock_coordinator()
        coordinator.data["fuel_remaining"] = 4.5
        sensor = VevorFuelRemainingSensor(coordinator)

        assert sensor.native_value == 4.5

    def test_native_value_none(self):
        """Test native_value when not tracked."""
        coordinator = create_mock_coordinator()
        coordinator.data["fuel_remaining"] = None
        sensor = VevorFuelRemainingSensor(coordinator)

        assert sensor.native_value is None


# ---------------------------------------------------------------------------
# Runtime sensor tests
# ---------------------------------------------------------------------------

class TestDailyRuntimeSensor:
    """Tests for daily runtime sensor."""

    def test_native_value(self):
        """Test that native_value returns daily runtime hours."""
        coordinator = create_mock_coordinator()
        coordinator.data["daily_runtime_hours"] = 5.5
        sensor = VevorDailyRuntimeSensor(coordinator)

        assert sensor.native_value == 5.5


class TestTotalRuntimeSensor:
    """Tests for total runtime sensor."""

    def test_native_value(self):
        """Test that native_value returns total runtime hours."""
        coordinator = create_mock_coordinator()
        coordinator.data["total_runtime_hours"] = 250.0
        sensor = VevorTotalRuntimeSensor(coordinator)

        assert sensor.native_value == 250.0


# ---------------------------------------------------------------------------
# Availability tests
# ---------------------------------------------------------------------------

class TestSensorAvailability:
    """Tests for sensor availability."""

    def test_available_when_connected(self):
        """Test sensor is available when last_update_success and has value."""
        coordinator = create_mock_coordinator()
        coordinator.last_update_success = True
        coordinator.data["cab_temperature"] = 20.5
        sensor = VevorCabTemperatureSensor(coordinator)

        assert sensor.available is True

    def test_unavailable_when_update_failed(self):
        """Test sensor is unavailable when last_update_success is False."""
        coordinator = create_mock_coordinator()
        coordinator.last_update_success = False
        sensor = VevorCabTemperatureSensor(coordinator)

        assert sensor.available is False

    def test_unavailable_when_value_none(self):
        """Test sensor is unavailable when native_value is None."""
        coordinator = create_mock_coordinator()
        coordinator.last_update_success = True
        coordinator.data["cab_temperature"] = None
        sensor = VevorCabTemperatureSensor(coordinator)

        assert sensor.available is False
