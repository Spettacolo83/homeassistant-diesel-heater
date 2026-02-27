"""Protocol constants for diesel heater BLE communication.

These constants are used by the protocol parsers and command builders.
They have no dependency on Home Assistant.
"""
from typing import Final

# Protocol headers
PROTOCOL_HEADER_AA55: Final = 0xAA55  # Protocol type 1 (Vevor)
PROTOCOL_HEADER_AA66: Final = 0xAA66  # Protocol type 2 (Vevor encrypted)
PROTOCOL_HEADER_ABBA: Final = 0xABBA  # Protocol type 5 (HeaterCC/ABBA)
PROTOCOL_HEADER_BAAB: Final = 0xBAAB  # ABBA command header (reversed)
PROTOCOL_HEADER_CBFF: Final = 0xCBFF  # Protocol type 6 (Sunster/v2.1)
PROTOCOL_HEADER_AA77: Final = 0xAA77  # Sunster V2.1 locked state / ACK header
PROTOCOL_HEADER_FEAA: Final = 0xFEAA  # Sunster V2.1 command header

# Sunster V2.1 double-XOR encryption key (15 bytes)
SUNSTER_V21_KEY: Final = b"passwordA2409PW"

# Hcalory Protocol headers
PROTOCOL_HEADER_HCALORY: Final = 0x0002  # Hcalory MVP1/MVP2 protocol ID

# Hcalory Service UUIDs
HCALORY_MVP1_SERVICE_UUID: Final = "0000fff0-0000-1000-8000-00805f9b34fb"
HCALORY_MVP2_SERVICE_UUID: Final = "0000bd39-0000-1000-8000-00805f9b34fb"

# Hcalory Characteristic UUIDs
HCALORY_MVP1_WRITE_UUID: Final = "0000fff2-0000-1000-8000-00805f9b34fb"
HCALORY_MVP1_NOTIFY_UUID: Final = "0000fff1-0000-1000-8000-00805f9b34fb"
HCALORY_MVP2_WRITE_UUID: Final = "0000bdf7-0000-1000-8000-00805f9b34fb"
HCALORY_MVP2_NOTIFY_UUID: Final = "0000bdf8-0000-1000-8000-00805f9b34fb"

# XOR encryption key for encrypted protocols
ENCRYPTION_KEY: Final = [112, 97, 115, 115, 119, 111, 114, 100]  # "password"

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

# Running modes
RUNNING_MODE_MANUAL: Final = 0
RUNNING_MODE_LEVEL: Final = 1
RUNNING_MODE_TEMPERATURE: Final = 2
RUNNING_MODE_VENTILATION: Final = 3  # ABBA only: fan-only mode when heater is off

RUNNING_MODE_NAMES: Final = {
    RUNNING_MODE_MANUAL: "Off",
    RUNNING_MODE_LEVEL: "Level",
    RUNNING_MODE_TEMPERATURE: "Temperature",
    RUNNING_MODE_VENTILATION: "Ventilation",
}

# ABBA Protocol status mapping (byte 4)
ABBA_STATUS_MAP: Final = {
    0x00: RUNNING_STEP_STANDBY,      # Powered Off
    0x01: RUNNING_STEP_RUNNING,      # Running/Heating
    0x02: RUNNING_STEP_COOLDOWN,     # Cooldown
    0x04: RUNNING_STEP_VENTILATION,  # Ventilation
    0x06: RUNNING_STEP_STANDBY,      # Standby
}

# CBFF Protocol (Sunster/v2.1) run_state mapping (byte 10)
CBFF_RUN_STATE_OFF: Final = {2, 5, 6}

# ABBA Protocol error codes
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
ABBA_ERROR_CO_ALARM: Final = 192

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
    ABBA_ERROR_CO_ALARM: "EC0 - Carbon monoxide alarm",
}

# ABBA Protocol commands
ABBA_CMD_HEAT_ON: Final = bytes.fromhex("baab04bba10000")
ABBA_CMD_HEAT_OFF: Final = bytes.fromhex("baab04bba40000")  # Also used for ventilation
ABBA_CMD_VENTILATION: Final = bytes.fromhex("baab04bba40000")  # 0xA4 = fan-only mode
ABBA_CMD_TEMP_UP: Final = bytes.fromhex("baab04bba20000")
ABBA_CMD_TEMP_DOWN: Final = bytes.fromhex("baab04bba30000")
ABBA_CMD_HIGH_ALTITUDE: Final = bytes.fromhex("baab04bba50000")
ABBA_CMD_AUTO: Final = bytes.fromhex("baab04bba60000")
ABBA_CMD_CONST_TEMP: Final = bytes.fromhex("baab04bbac0000")
ABBA_CMD_OTHER_MODE: Final = bytes.fromhex("baab04bbad0000")
ABBA_CMD_GET_TIME: Final = bytes.fromhex("baab04ec000000")
ABBA_CMD_GET_AUTO_CONFIG: Final = bytes.fromhex("baab04dc000000")
ABBA_CMD_STATUS: Final = bytes.fromhex("baab04cc00000035")

# Error codes (AA55 protocols)
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

# Limits - AAXX protocols (Vevor, BYD, Sunster, HeaterCC)
MIN_LEVEL: Final = 1
MAX_LEVEL: Final = 10
MIN_TEMP_CELSIUS: Final = 8
MAX_TEMP_CELSIUS: Final = 36

# Hcalory-specific temperature limits (wider range than AAXX)
HCALORY_MIN_TEMP_CELSIUS: Final = 0   # 0°C (32°F)
HCALORY_MAX_TEMP_CELSIUS: Final = 40  # 40°C (104°F)
HCALORY_MIN_TEMP_FAHRENHEIT: Final = 32   # 32°F (0°C)
HCALORY_MAX_TEMP_FAHRENHEIT: Final = 104  # 104°F (40°C)

# Hcalory specific limits (6 gear levels instead of 10)
HCALORY_MIN_LEVEL: Final = 1
HCALORY_MAX_LEVEL: Final = 10  # Beta.36: Confirmed by @Xev and @smaj100, issue #46

# Hcalory device states (byte position 18-19 in response)
HCALORY_STATE_STANDBY: Final = 0x00
HCALORY_STATE_HEATING_TEMP_AUTO: Final = 0x01
HCALORY_STATE_HEATING_MANUAL_GEAR: Final = 0x02
HCALORY_STATE_NATURAL_WIND: Final = 0x03
HCALORY_STATE_MACHINE_FAULT: Final = 0xFF

HCALORY_STATE_NAMES: Final = {
    HCALORY_STATE_STANDBY: "Standby",
    HCALORY_STATE_HEATING_TEMP_AUTO: "Temperature Mode",
    HCALORY_STATE_HEATING_MANUAL_GEAR: "Gear Mode",
    HCALORY_STATE_NATURAL_WIND: "Fan Only",
    HCALORY_STATE_MACHINE_FAULT: "Fault",
}

# Hcalory operative states (from status flags parsing)
HCALORY_OP_STATE_STOPPED: Final = 0x00
HCALORY_OP_STATE_HEATING: Final = 0x01
HCALORY_OP_STATE_COOLING: Final = 0x10
HCALORY_OP_STATE_NATURAL_WIND: Final = 0x11

# Hcalory error codes (when device_state = 0xFF)
HCALORY_ERROR_NONE: Final = 0
HCALORY_ERROR_IGNITION: Final = 1
HCALORY_ERROR_FLAME_OUT: Final = 2
HCALORY_ERROR_OVERHEAT: Final = 3
HCALORY_ERROR_FAN: Final = 4
HCALORY_ERROR_PUMP: Final = 5
HCALORY_ERROR_SENSOR: Final = 6
HCALORY_ERROR_VOLTAGE_LOW: Final = 7
HCALORY_ERROR_VOLTAGE_HIGH: Final = 8
HCALORY_ERROR_COMMUNICATION: Final = 9
HCALORY_ERROR_CO_HIGH: Final = 10
HCALORY_ERROR_CO_CRITICAL: Final = 11

HCALORY_ERROR_NAMES: Final = {
    HCALORY_ERROR_NONE: "No fault",
    HCALORY_ERROR_IGNITION: "E01 - Ignition failure",
    HCALORY_ERROR_FLAME_OUT: "E02 - Flame out",
    HCALORY_ERROR_OVERHEAT: "E03 - Overheat",
    HCALORY_ERROR_FAN: "E04 - Fan failure",
    HCALORY_ERROR_PUMP: "E05 - Pump failure",
    HCALORY_ERROR_SENSOR: "E06 - Sensor failure",
    HCALORY_ERROR_VOLTAGE_LOW: "E07 - Low voltage",
    HCALORY_ERROR_VOLTAGE_HIGH: "E08 - High voltage",
    HCALORY_ERROR_COMMUNICATION: "E09 - Communication error",
    HCALORY_ERROR_CO_HIGH: "E10 - CO concentration high",
    HCALORY_ERROR_CO_CRITICAL: "E11 - CO concentration critical",
}

# Hcalory command types
# MVP1 commands (older models with service FFF0)
HCALORY_CMD_SET_GEAR: Final = 0x0607
HCALORY_CMD_SET_TEMP: Final = 0x0706
HCALORY_CMD_SET_MODE: Final = 0x070B
HCALORY_CMD_POWER: Final = 0x0E04  # MVP1 query/power (dpID 0E04)
HCALORY_CMD_SET_ALTITUDE: Final = 0x0909
# MVP2 commands (newer models with service BD39)
HCALORY_CMD_QUERY_STATE: Final = 0x0A0A  # MVP2 query state (dpID 0A0A)
HCALORY_CMD_PASSWORD: Final = 0x0A0C  # MVP2 password handshake (dpID 0A0C)

# Hcalory power command arguments (for CMD_POWER)
HCALORY_POWER_QUERY: Final = 0x00
HCALORY_POWER_OFF: Final = 0x01  # Fixed: was 0x02 (swapped with ON)
HCALORY_POWER_ON: Final = 0x02  # Fixed: was 0x01 (swapped with OFF)
HCALORY_POWER_AUTO_ON: Final = 0x03
HCALORY_POWER_AUTO_OFF: Final = 0x04
HCALORY_POWER_MODE_LEVEL: Final = 0x06  # Switch to Level mode (@Xev btsnoop, issue #43)
HCALORY_POWER_MODE_TEMP: Final = 0x07  # Switch to Temperature mode (@Xev btsnoop, issue #43)
HCALORY_POWER_CELSIUS: Final = 0x0A
HCALORY_POWER_FAHRENHEIT: Final = 0x0B
HCALORY_POWER_QUERY_ALTITUDE: Final = 0x0D

# Hcalory altitude mode states (@Xev, issue #34)
HCALORY_ALTITUDE_OFF: Final = 0x00
HCALORY_ALTITUDE_MODE_1: Final = 0x01
HCALORY_ALTITUDE_MODE_2: Final = 0x02
HCALORY_ALTITUDE_TOGGLE_CMD: Final = 0x09  # Command value for toggle

# Hcalory MVP2 Running Status (byte 20, high nibble) - @Xev analysis (issue #34)
HCALORY_RUNNING_STATUS_OFF: Final = 0x00
HCALORY_RUNNING_STATUS_TURNING_OFF: Final = 0x04
HCALORY_RUNNING_STATUS_HEATING: Final = 0x08
HCALORY_RUNNING_STATUS_VENTILATION: Final = 0x0C
HCALORY_RUNNING_STATUS_ERROR: Final = 0x0F

HCALORY_RUNNING_STATUS_NAMES: Final = {
    HCALORY_RUNNING_STATUS_OFF: "Off",
    HCALORY_RUNNING_STATUS_TURNING_OFF: "Turning Off",
    HCALORY_RUNNING_STATUS_HEATING: "Heating",
    HCALORY_RUNNING_STATUS_VENTILATION: "Ventilation",
    HCALORY_RUNNING_STATUS_ERROR: "Error",
}

# Hcalory MVP2 Running Steps (byte 20, low nibble) - @Xev analysis (issue #34)
HCALORY_RUNNING_STEP_INACTIVE: Final = 0x00
HCALORY_RUNNING_STEP_FAN: Final = 0x01  # Blowing air
HCALORY_RUNNING_STEP_IGNITION: Final = 0x03  # Igniting
HCALORY_RUNNING_STEP_COOLDOWN: Final = 0x04  # Synthetic state (created from TURNING_OFF status)
HCALORY_RUNNING_STEP_RUNNING: Final = 0x05  # Heating/Running
HCALORY_RUNNING_STEP_STANDBY: Final = 0x07  # Standby (temp reached with auto on)

HCALORY_RUNNING_STEP_NAMES: Final = {
    HCALORY_RUNNING_STEP_INACTIVE: "Inactive",
    HCALORY_RUNNING_STEP_FAN: "Blowing Air",
    HCALORY_RUNNING_STEP_IGNITION: "Igniting",
    HCALORY_RUNNING_STEP_RUNNING: "Heating",
    HCALORY_RUNNING_STEP_STANDBY: "Standby",
    HCALORY_RUNNING_STEP_COOLDOWN: "Cooldown",
}

# Hcalory MVP2 Set Modes (byte 21) - @Xev analysis (issue #34)
HCALORY_MODE_OFF: Final = 0x00
HCALORY_MODE_TEMPERATURE: Final = 0x01
HCALORY_MODE_LEVEL: Final = 0x02
HCALORY_MODE_VENTILATION: Final = 0x03

HCALORY_MODE_NAMES: Final = {
    HCALORY_MODE_OFF: "Off",
    HCALORY_MODE_TEMPERATURE: "Temperature",
    HCALORY_MODE_LEVEL: "Level",
    HCALORY_MODE_VENTILATION: "Ventilation",
}

# Hcalory MVP2 Temperature Units (byte 37)
HCALORY_TEMP_CELSIUS: Final = 0x00
HCALORY_TEMP_FAHRENHEIT: Final = 0x01

# Hcalory MVP2 Altitude Modes (byte 18) - NOTE: No actual sensor, UI removed (issue #34)
HCALORY_ALTITUDE_OFF: Final = 0x00
HCALORY_ALTITUDE_LOW: Final = 0x01
HCALORY_ALTITUDE_MEDIUM: Final = 0x02
HCALORY_ALTITUDE_HIGH: Final = 0x03
