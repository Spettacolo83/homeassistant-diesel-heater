"""Constants for the Vevor Diesel Heater integration."""
from typing import Final

DOMAIN: Final = "vevor_heater"

# BLE Service and Characteristic UUIDs
# Some Vevor heaters use ffe0 instead of fff0
SERVICE_UUID: Final = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_UUID: Final = "0000ffe1-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID: Final = "0000ffe2-0000-1000-8000-00805f9b34fb"

# Alternative UUIDs (fff0 variant)
SERVICE_UUID_ALT: Final = "0000fff0-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_UUID_ALT: Final = "0000fff1-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID_ALT: Final = "0000fff2-0000-1000-8000-00805f9b34fb"

# Protocol constants
PROTOCOL_HEADER_AA55: Final = 0xAA55  # Protocol type 1
PROTOCOL_HEADER_AA66: Final = 0xAA66  # Protocol type 2

# XOR encryption key for encrypted protocols
ENCRYPTION_KEY: Final = [112, 97, 115, 115, 119, 111, 114, 100]  # "password"

# Running states
RUNNING_STATE_OFF: Final = 0
RUNNING_STATE_ON: Final = 1

# Running steps
RUNNING_STEP_STANDBY: Final = 0
RUNNING_STEP_SELF_TEST: Final = 1
RUNNING_STEP_IGNITION: Final = 2
RUNNING_STEP_RUNNING: Final = 3
RUNNING_STEP_COOLDOWN: Final = 4

RUNNING_STEP_NAMES: Final = {
    RUNNING_STEP_STANDBY: "Standby",
    RUNNING_STEP_SELF_TEST: "Self-test",
    RUNNING_STEP_IGNITION: "Ignition",
    RUNNING_STEP_RUNNING: "Running",
    RUNNING_STEP_COOLDOWN: "Cooldown",
}

# Running modes
RUNNING_MODE_MANUAL: Final = 0
RUNNING_MODE_LEVEL: Final = 1
RUNNING_MODE_TEMPERATURE: Final = 2

RUNNING_MODE_NAMES: Final = {
    RUNNING_MODE_MANUAL: "Manual",
    RUNNING_MODE_LEVEL: "Level Mode",
    RUNNING_MODE_TEMPERATURE: "Temperature Mode",
}

# Error codes
ERROR_NONE: Final = 0
ERROR_STARTUP_FAILURE: Final = 1
ERROR_LACK_OF_FUEL: Final = 2
ERROR_SUPPLY_VOLTAGE_OVERRUN: Final = 3
ERROR_OUTLET_SENSOR_FAULT: Final = 4
ERROR_INLET_SENSOR_FAULT: Final = 5
ERROR_PULSE_PUMP_FAULT: Final = 6
ERROR_FAN_FAULT: Final = 7
ERROR_IGNITION_UNIT_FAULT: Final = 8
ERROR_OVERHEATING: Final = 9
ERROR_OVERHEAT_SENSOR_FAULT: Final = 10

ERROR_NAMES: Final = {
    ERROR_NONE: "No fault",
    ERROR_STARTUP_FAILURE: "Startup failure",
    ERROR_LACK_OF_FUEL: "Lack of fuel",
    ERROR_SUPPLY_VOLTAGE_OVERRUN: "Supply voltage overrun",
    ERROR_OUTLET_SENSOR_FAULT: "Outlet sensor fault",
    ERROR_INLET_SENSOR_FAULT: "Inlet sensor fault",
    ERROR_PULSE_PUMP_FAULT: "Pulse pump fault",
    ERROR_FAN_FAULT: "Fan fault",
    ERROR_IGNITION_UNIT_FAULT: "Ignition unit fault",
    ERROR_OVERHEATING: "Overheating",
    ERROR_OVERHEAT_SENSOR_FAULT: "Overheat sensor fault",
}

# Limits
MIN_LEVEL: Final = 1
MAX_LEVEL: Final = 10
MIN_TEMP_CELSIUS: Final = 8
MAX_TEMP_CELSIUS: Final = 36

# Temperature calibration
CONF_TEMPERATURE_OFFSET: Final = "temperature_offset"
DEFAULT_TEMPERATURE_OFFSET: Final = 0.0
MIN_TEMPERATURE_OFFSET: Final = -20.0
MAX_TEMPERATURE_OFFSET: Final = 20.0
SENSOR_TEMP_MIN: Final = -128
SENSOR_TEMP_MAX: Final = 127

# Update interval
UPDATE_INTERVAL: Final = 30  # seconds

# Fuel consumption tracking
# Consumption rates in L/h based on VEVOR specs (0.16-0.52 L/h range)
# Linear interpolation from level 1 (min) to level 10 (max)
FUEL_CONSUMPTION_TABLE: Final = {
    1: 0.16,  # Minimum consumption
    2: 0.20,
    3: 0.24,
    4: 0.28,
    5: 0.32,
    6: 0.36,
    7: 0.40,
    8: 0.44,
    9: 0.48,
    10: 0.52,  # Maximum consumption
}

# Tank capacity
CONF_TANK_CAPACITY: Final = "tank_capacity"
DEFAULT_TANK_CAPACITY: Final = 10.0  # Liters
MIN_TANK_CAPACITY: Final = 1.0
MAX_TANK_CAPACITY: Final = 100.0

# Low fuel warning threshold
LOW_FUEL_THRESHOLD: Final = 0.20  # 20%

# Fuel calibration factor (user adjustable)
CONF_FUEL_CALIBRATION: Final = "fuel_calibration"
DEFAULT_FUEL_CALIBRATION: Final = 1.0  # Multiplier for consumption table
MIN_FUEL_CALIBRATION: Final = 0.5
MAX_FUEL_CALIBRATION: Final = 2.0

# Data persistence keys
STORAGE_KEY_TOTAL_FUEL: Final = "total_fuel_consumed"
STORAGE_KEY_DAILY_FUEL: Final = "daily_fuel_consumed"
STORAGE_KEY_DAILY_DATE: Final = "daily_fuel_date"
STORAGE_KEY_TOTAL_RUNTIME: Final = "total_runtime_seconds"
STORAGE_KEY_DAILY_RUNTIME: Final = "daily_runtime_seconds"
STORAGE_KEY_DAILY_RUNTIME_DATE: Final = "daily_runtime_date"

# External temperature sensor
CONF_EXTERNAL_TEMP_SENSOR: Final = "external_temperature_sensor"
