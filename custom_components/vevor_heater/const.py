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
PROTOCOL_HEADER_AA55: Final = 0xAA55  # Protocol type 1 (Vevor)
PROTOCOL_HEADER_AA66: Final = 0xAA66  # Protocol type 2 (Vevor encrypted)
PROTOCOL_HEADER_ABBA: Final = 0xABBA  # Protocol type 5 (HeaterCC/ABBA)
PROTOCOL_HEADER_BAAB: Final = 0xBAAB  # ABBA command header (reversed)
PROTOCOL_HEADER_CBFF: Final = 0xCBFF  # Protocol type 6 (Sunster/v2.1)
PROTOCOL_HEADER_AA77: Final = 0xAA77  # Sunster command ACK header

# XOR encryption key for encrypted protocols
ENCRYPTION_KEY: Final = [112, 97, 115, 115, 119, 111, 114, 100]  # "password"

# ABBA Protocol (HeaterCC heaters)
# These heaters use service fff0 with characteristics fff1 (notify) and fff2 (write)
ABBA_SERVICE_UUID: Final = "0000fff0-0000-1000-8000-00805f9b34fb"
ABBA_NOTIFY_UUID: Final = "0000fff1-0000-1000-8000-00805f9b34fb"
ABBA_WRITE_UUID: Final = "0000fff2-0000-1000-8000-00805f9b34fb"

# ABBA Protocol commands (without checksum - added at send time)
ABBA_CMD_HEAT_ON: Final = bytes.fromhex("baab04bba10000")
ABBA_CMD_HEAT_OFF: Final = bytes.fromhex("baab04bba40000")  # 吹风 (blow air) = cooldown/off
ABBA_CMD_TEMP_UP: Final = bytes.fromhex("baab04bba20000")
ABBA_CMD_TEMP_DOWN: Final = bytes.fromhex("baab04bba30000")
ABBA_CMD_HIGH_ALTITUDE: Final = bytes.fromhex("baab04bba50000")  # 高原 (high altitude mode)
ABBA_CMD_AUTO: Final = bytes.fromhex("baab04bba60000")
ABBA_CMD_CONST_TEMP: Final = bytes.fromhex("baab04bbac0000")
ABBA_CMD_OTHER_MODE: Final = bytes.fromhex("baab04bbad0000")
ABBA_CMD_GET_TIME: Final = bytes.fromhex("baab04ec000000")
ABBA_CMD_GET_AUTO_CONFIG: Final = bytes.fromhex("baab04dc000000")
ABBA_CMD_STATUS: Final = bytes.fromhex("baab04cc00000035")  # Status/ACK request

# Running states
RUNNING_STATE_OFF: Final = 0
RUNNING_STATE_ON: Final = 1

# Running steps (AA55 protocol)
RUNNING_STEP_STANDBY: Final = 0
RUNNING_STEP_SELF_TEST: Final = 1
RUNNING_STEP_IGNITION: Final = 2
RUNNING_STEP_RUNNING: Final = 3
RUNNING_STEP_COOLDOWN: Final = 4
RUNNING_STEP_VENTILATION: Final = 6

RUNNING_STEP_NAMES: Final = {
    RUNNING_STEP_STANDBY: "Standby",
    RUNNING_STEP_SELF_TEST: "Self-test",
    RUNNING_STEP_IGNITION: "Ignition",
    RUNNING_STEP_RUNNING: "Running",
    RUNNING_STEP_COOLDOWN: "Cooldown",
    RUNNING_STEP_VENTILATION: "Ventilation",
}

# ABBA Protocol status mapping (byte 4)
# Different from AA55 - maps to same RUNNING_STEP values for consistency
ABBA_STATUS_MAP: Final = {
    0x00: RUNNING_STEP_STANDBY,      # Powered Off
    0x01: RUNNING_STEP_RUNNING,      # Running/Heating
    0x02: RUNNING_STEP_COOLDOWN,     # Cooldown
    0x04: RUNNING_STEP_VENTILATION,  # Ventilation
    0x06: RUNNING_STEP_STANDBY,      # Standby
}

# CBFF Protocol (Sunster/v2.1) run_state mapping (byte 10)
# From Sunster app: run_state 2/5/6 = OFF, others = ON
# run_step is directly at byte 14
CBFF_RUN_STATE_OFF: Final = {2, 5, 6}  # States that indicate heater is OFF

# ABBA Protocol error codes (when byte 5 = 0xFF, byte 6 = error code)
# Different from AA55 error codes
ABBA_ERROR_NONE: Final = 0
ABBA_ERROR_VOLTAGE: Final = 2
ABBA_ERROR_IGNITER: Final = 3
ABBA_ERROR_FUEL_PUMP: Final = 4
ABBA_ERROR_OVER_TEMP: Final = 5
ABBA_ERROR_FAN: Final = 6
ABBA_ERROR_COMMUNICATION: Final = 7
ABBA_ERROR_FLAMEOUT: Final = 8
ABBA_ERROR_SENSOR: Final = 9
ABBA_ERROR_STARTUP: Final = 10
ABBA_ERROR_CO_ALARM: Final = 192  # 0xC0 hex - clever pun: looks like "CO" (Carbon Monoxide)

ABBA_ERROR_NAMES: Final = {
    ABBA_ERROR_NONE: "No fault",
    ABBA_ERROR_VOLTAGE: "E2 - Voltage fault",
    ABBA_ERROR_IGNITER: "E3 - Igniter fault",
    ABBA_ERROR_FUEL_PUMP: "E4 - Fuel pump fault",
    ABBA_ERROR_OVER_TEMP: "E5 - Over-temperature",
    ABBA_ERROR_FAN: "E6 - Fan fault",
    ABBA_ERROR_COMMUNICATION: "E7 - Communication fault",
    ABBA_ERROR_FLAMEOUT: "E8 - Flameout",
    ABBA_ERROR_SENSOR: "E9 - Sensor fault",
    ABBA_ERROR_STARTUP: "E10 - Startup failure",
    ABBA_ERROR_CO_ALARM: "EC0 - Carbon monoxide alarm",  # 0xC0 = 192 decimal
}

# Running modes
RUNNING_MODE_MANUAL: Final = 0
RUNNING_MODE_LEVEL: Final = 1
RUNNING_MODE_TEMPERATURE: Final = 2

RUNNING_MODE_NAMES: Final = {
    RUNNING_MODE_MANUAL: "Off",
    RUNNING_MODE_LEVEL: "Level",
    RUNNING_MODE_TEMPERATURE: "Temperature",
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

# BLE authentication PIN
CONF_PIN: Final = "pin"
DEFAULT_PIN: Final = 1234
MIN_PIN: Final = 0
MAX_PIN: Final = 9999

# Climate presets
CONF_PRESET_AWAY_TEMP: Final = "preset_away_temp"
CONF_PRESET_COMFORT_TEMP: Final = "preset_comfort_temp"
DEFAULT_PRESET_AWAY_TEMP: Final = 8
DEFAULT_PRESET_COMFORT_TEMP: Final = 21

# Auto temperature offset from external sensor
CONF_EXTERNAL_TEMP_SENSOR: Final = "external_temp_sensor"
CONF_AUTO_OFFSET_MAX: Final = "auto_offset_max"
CONF_AUTO_OFFSET_ENABLED: Final = "auto_offset_enabled"
DEFAULT_AUTO_OFFSET_MAX: Final = 5
MIN_AUTO_OFFSET_MAX: Final = 1
MAX_AUTO_OFFSET_MAX: Final = 9
AUTO_OFFSET_THROTTLE_SECONDS: Final = 60
AUTO_OFFSET_THRESHOLD: Final = 1.0  # Only adjust if difference >= 1°C

# Heater temperature offset (sent to heater via cmd 20)
# Both positive and negative offsets now work via BLE
# Encoding: arg1 = value % 256, arg2 = (value // 256) % 256
MIN_HEATER_OFFSET: Final = -9
MAX_HEATER_OFFSET: Final = 9

# Configuration settings commands (verified by @Xev testing)
CMD_SET_LANGUAGE: Final = 14
CMD_SET_TEMP_UNIT: Final = 15
CMD_SET_TANK_VOLUME: Final = 16  # Index-based: 0=None, 1=5L, 2=10L, etc.
CMD_SET_PUMP_TYPE: Final = 17
CMD_SET_ALTITUDE_UNIT: Final = 19  # Was incorrectly 16
CMD_SET_OFFSET: Final = 20
CMD_SET_BACKLIGHT: Final = 21

# Language options (byte 26) - verified by @Xev testing
# Note: Values 1, 5, 6 may not be supported by all heaters
LANGUAGE_OPTIONS: Final = {
    0: "English",
    1: "Chinese",
    2: "German",
    3: "Silent",
    4: "Russian",
}

# Temperature unit (byte 27)
TEMP_UNIT_CELSIUS: Final = 0
TEMP_UNIT_FAHRENHEIT: Final = 1

# Altitude unit (byte 30)
ALTITUDE_UNIT_METERS: Final = 0
ALTITUDE_UNIT_FEET: Final = 1

# Tank volume range (byte 28) - index-based, not liters!
MIN_TANK_VOLUME: Final = 0
MAX_TANK_VOLUME: Final = 10

# Tank volume options - INDEX-BASED (verified by @Xev testing)
# The heater stores an index (0-10), not the actual volume
# Index 0 = None/disabled, Index 1 = 5L, Index 2 = 10L, etc.
TANK_VOLUME_OPTIONS: Final = {
    0: "None",
    1: "5 L",
    2: "10 L",
    3: "15 L",
    4: "20 L",
    5: "25 L",
    6: "30 L",
    7: "35 L",
    8: "40 L",
    9: "45 L",
    10: "50 L",
}

# Pump type options (byte 29) - verified by @Xev testing
# Values 20/21 indicate RF433 remote status (not pump type)
PUMP_TYPE_OPTIONS: Final = {
    0: "16µl",
    1: "22µl",
    2: "28µl",
    3: "32µl",
}

# Backlight brightness options (discrete values matching Vevor app)
# Off, 1-10 fine control, then 20-100 in steps of 10
BACKLIGHT_OPTIONS: Final = {
    0: "Off",
    1: "1",
    2: "2",
    3: "3",
    4: "4",
    5: "5",
    6: "6",
    7: "7",
    8: "8",
    9: "9",
    10: "10",
    20: "20",
    30: "30",
    40: "40",
    50: "50",
    60: "60",
    70: "70",
    80: "80",
    90: "90",
    100: "100",
}

# Update interval
UPDATE_INTERVAL: Final = 30  # seconds

# Fuel consumption tracking (minimal - consumption only)
# Consumption rates in L/h based on VEVOR specs (0.16-0.52 L/h range)
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

# Data persistence keys
STORAGE_KEY_TOTAL_FUEL: Final = "total_fuel_consumed"
STORAGE_KEY_DAILY_FUEL: Final = "daily_fuel_consumed"
STORAGE_KEY_DAILY_DATE: Final = "daily_fuel_date"
STORAGE_KEY_DAILY_HISTORY: Final = "daily_fuel_history"

# Runtime tracking persistence keys
STORAGE_KEY_TOTAL_RUNTIME: Final = "total_runtime_seconds"
STORAGE_KEY_DAILY_RUNTIME: Final = "daily_runtime_seconds"
STORAGE_KEY_DAILY_RUNTIME_DATE: Final = "daily_runtime_date"
STORAGE_KEY_DAILY_RUNTIME_HISTORY: Final = "daily_runtime_history"

# Fuel level tracking persistence keys
STORAGE_KEY_FUEL_SINCE_RESET: Final = "fuel_consumed_since_reset"
STORAGE_KEY_TANK_CAPACITY: Final = "tank_capacity_liters"
STORAGE_KEY_LAST_REFUELED: Final = "last_refueled"

# Auto offset persistence key
STORAGE_KEY_AUTO_OFFSET_ENABLED: Final = "auto_offset_enabled"

# History settings
MAX_HISTORY_DAYS: Final = 30  # Keep last 30 days of daily consumption
