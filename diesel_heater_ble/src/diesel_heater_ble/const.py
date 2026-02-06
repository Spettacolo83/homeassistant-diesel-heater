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
PROTOCOL_HEADER_AA77: Final = 0xAA77  # Sunster command ACK header

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

RUNNING_MODE_NAMES: Final = {
    RUNNING_MODE_MANUAL: "Off",
    RUNNING_MODE_LEVEL: "Level",
    RUNNING_MODE_TEMPERATURE: "Temperature",
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
ABBA_CMD_HEAT_OFF: Final = bytes.fromhex("baab04bba40000")
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

# Limits
MIN_LEVEL: Final = 1
MAX_LEVEL: Final = 10
MIN_TEMP_CELSIUS: Final = 8
MAX_TEMP_CELSIUS: Final = 36
