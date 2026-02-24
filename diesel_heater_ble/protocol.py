"""Protocol handlers for diesel heater BLE communication.

Each protocol class encapsulates the byte-level parsing (parse) and
command building (build_command) for a specific BLE protocol variant.
The coordinator uses these classes via a common HeaterProtocol interface.

Protocols supported:
  - AA55 (unencrypted, 18-20 bytes)
  - AA55 encrypted (48 bytes, XOR)
  - AA66 (unencrypted, 20 bytes, BYD variant)
  - AA66 encrypted (48 bytes, XOR)
  - ABBA/HeaterCC (21+ bytes, own command format)
  - CBFF/Sunster v2.1 (47 bytes, optional double-XOR encryption)

This module has no dependency on Home Assistant.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from .const import (
    ABBA_STATUS_MAP,
    CBFF_RUN_STATE_OFF,
    ENCRYPTION_KEY,
    HCALORY_CMD_POWER,
    HCALORY_CMD_SET_ALTITUDE,
    HCALORY_CMD_SET_GEAR,
    HCALORY_CMD_SET_MODE,
    HCALORY_CMD_SET_TEMP,
    HCALORY_MAX_LEVEL,
    HCALORY_MIN_LEVEL,
    HCALORY_POWER_AUTO_OFF,
    HCALORY_POWER_AUTO_ON,
    HCALORY_POWER_CELSIUS,
    HCALORY_POWER_FAHRENHEIT,
    HCALORY_POWER_OFF,
    HCALORY_POWER_ON,
    HCALORY_POWER_QUERY,
    HCALORY_STATE_HEATING_MANUAL_GEAR,
    HCALORY_STATE_HEATING_TEMP_AUTO,
    HCALORY_STATE_MACHINE_FAULT,
    HCALORY_STATE_NATURAL_WIND,
    HCALORY_STATE_STANDBY,
    RUNNING_MODE_LEVEL,
    RUNNING_MODE_MANUAL,
    RUNNING_MODE_TEMPERATURE,
    SUNSTER_V21_KEY,
)

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _u8_to_number(value: int) -> int:
    """Convert unsigned 8-bit value."""
    return (value + 256) if (value < 0) else value


def _unsign_to_sign(value: int) -> int:
    """Convert unsigned to signed value."""
    if value > 32767.5:
        value = value | -65536
    return value


def _decrypt_data(data: bytearray) -> bytearray:
    """Decrypt encrypted data using XOR with password key."""
    decrypted = bytearray(data)
    for j in range(6):
        base_index = 8 * j
        for i in range(8):
            if base_index + i < len(decrypted):
                decrypted[base_index + i] = ENCRYPTION_KEY[i] ^ decrypted[base_index + i]
    return decrypted


def _encrypt_data(data: bytearray) -> bytearray:
    """Encrypt data using XOR with password key (symmetric)."""
    return _decrypt_data(data)


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class HeaterProtocol(ABC):
    """Abstract base class for heater BLE protocol handlers."""

    protocol_mode: int = 0
    name: str = "Unknown"
    needs_calibration: bool = True   # Call _apply_ui_temperature_offset after parse
    needs_post_status: bool = False  # Send follow-up status request after commands

    @abstractmethod
    def parse(self, data: bytearray) -> dict[str, Any] | None:
        """Parse BLE response data into a normalized dict.

        Returns:
            dict with parsed values, or None if data is too short / invalid.
        Raises:
            Exception on parse errors (coordinator handles fallback).
        """

    @abstractmethod
    def build_command(self, command: int, argument: int, passkey: int) -> bytearray:
        """Build a command packet for this protocol."""


# ---------------------------------------------------------------------------
# Shared command builder for Vevor AA55-based protocols
# ---------------------------------------------------------------------------

class VevorCommandMixin:
    """Shared AA55 8-byte command builder used by protocols 1, 2, 3, 4, 6."""

    def build_command(self, command: int, argument: int, passkey: int) -> bytearray:
        """Build 8-byte AA55 command packet (always unencrypted)."""
        packet = bytearray([0xAA, 0x55, 0, 0, 0, 0, 0, 0])
        packet[2] = passkey // 100
        packet[3] = passkey % 100
        packet[4] = command % 256
        packet[5] = argument % 256
        packet[6] = (argument // 256) % 256
        packet[7] = (packet[2] + packet[3] + packet[4] + packet[5] + packet[6]) % 256
        return packet


# ---------------------------------------------------------------------------
# Protocol implementations
# ---------------------------------------------------------------------------

class ProtocolAA55(VevorCommandMixin, HeaterProtocol):
    """AA55 unencrypted protocol (mode=1, 18-20 bytes)."""

    protocol_mode = 1
    name = "AA55"

    def parse(self, data: bytearray) -> dict[str, Any] | None:
        parsed: dict[str, Any] = {}

        parsed["running_state"] = _u8_to_number(data[3])
        parsed["error_code"] = _u8_to_number(data[4])
        parsed["running_step"] = _u8_to_number(data[5])
        parsed["altitude"] = _u8_to_number(data[6]) + 256 * _u8_to_number(data[7])
        parsed["running_mode"] = _u8_to_number(data[8])

        if parsed["running_mode"] == RUNNING_MODE_LEVEL:
            parsed["set_level"] = _u8_to_number(data[9])
        elif parsed["running_mode"] == RUNNING_MODE_TEMPERATURE:
            parsed["set_temp"] = _u8_to_number(data[9])
            parsed["set_level"] = _u8_to_number(data[10]) + 1
        elif parsed["running_mode"] == RUNNING_MODE_MANUAL:
            parsed["set_level"] = _u8_to_number(data[10]) + 1

        parsed["supply_voltage"] = (
            (256 * _u8_to_number(data[12]) + _u8_to_number(data[11])) / 10
        )
        parsed["case_temperature"] = _unsign_to_sign(256 * data[14] + data[13])
        parsed["cab_temperature"] = _unsign_to_sign(256 * data[16] + data[15])

        return parsed


class ProtocolAA66(VevorCommandMixin, HeaterProtocol):
    """AA66 unencrypted protocol (mode=3, 20 bytes) - BYD/Vevor variant."""

    protocol_mode = 3
    name = "AA66"

    def parse(self, data: bytearray) -> dict[str, Any] | None:
        parsed: dict[str, Any] = {}

        parsed["running_state"] = _u8_to_number(data[3])
        parsed["error_code"] = _u8_to_number(data[4])
        parsed["running_step"] = _u8_to_number(data[5])
        parsed["altitude"] = _u8_to_number(data[6])
        parsed["running_mode"] = _u8_to_number(data[8])

        if parsed["running_mode"] == RUNNING_MODE_LEVEL:
            parsed["set_level"] = max(1, min(10, _u8_to_number(data[9])))
        elif parsed["running_mode"] == RUNNING_MODE_TEMPERATURE:
            parsed["set_temp"] = max(8, min(36, _u8_to_number(data[9])))

        voltage_raw = _u8_to_number(data[11]) | (_u8_to_number(data[12]) << 8)
        parsed["supply_voltage"] = voltage_raw / 10.0

        # Auto-detect case temp format: >350 means 0.1°C scale
        case_temp_raw = _u8_to_number(data[13]) | (_u8_to_number(data[14]) << 8)
        if case_temp_raw > 350:
            parsed["case_temperature"] = case_temp_raw / 10.0
        else:
            parsed["case_temperature"] = float(case_temp_raw)

        parsed["cab_temperature"] = _u8_to_number(data[15])

        return parsed


class ProtocolAA55Encrypted(VevorCommandMixin, HeaterProtocol):
    """AA55 encrypted protocol (mode=2, 48 bytes decrypted).

    Receives already-decrypted data from coordinator._detect_protocol.
    """

    protocol_mode = 2
    name = "AA55 encrypted"

    def parse(self, data: bytearray) -> dict[str, Any] | None:
        parsed: dict[str, Any] = {}

        parsed["running_state"] = _u8_to_number(data[3])
        parsed["error_code"] = _u8_to_number(data[4])
        parsed["running_step"] = _u8_to_number(data[5])
        parsed["altitude"] = (_u8_to_number(data[7]) + 256 * _u8_to_number(data[6])) / 10
        parsed["running_mode"] = _u8_to_number(data[8])
        parsed["set_level"] = max(1, min(10, _u8_to_number(data[10])))
        parsed["set_temp"] = max(8, min(36, _u8_to_number(data[9])))

        parsed["supply_voltage"] = (256 * data[11] + data[12]) / 10
        parsed["case_temperature"] = _unsign_to_sign(256 * data[13] + data[14])
        parsed["cab_temperature"] = _unsign_to_sign(256 * data[32] + data[33]) / 10

        # Byte 34: Temperature offset (signed)
        if len(data) > 34:
            raw = data[34]
            parsed["heater_offset"] = (raw - 256) if raw > 127 else raw

        # Byte 36: Backlight brightness
        if len(data) > 36:
            parsed["backlight"] = _u8_to_number(data[36])

        # Byte 37: CO sensor present, Bytes 38-39: CO PPM (big endian)
        if len(data) > 39:
            if _u8_to_number(data[37]) == 1:
                parsed["co_ppm"] = float(
                    (_u8_to_number(data[38]) << 8) | _u8_to_number(data[39])
                )
            else:
                parsed["co_ppm"] = None

        # Bytes 40-43: Part number (uint32 LE, hex string)
        if len(data) > 43:
            part = (
                _u8_to_number(data[40])
                | (_u8_to_number(data[41]) << 8)
                | (_u8_to_number(data[42]) << 16)
                | (_u8_to_number(data[43]) << 24)
            )
            if part != 0:
                parsed["part_number"] = format(part, 'x')

        # Byte 44: Motherboard version
        if len(data) > 44:
            mb = _u8_to_number(data[44])
            if mb != 0:
                parsed["motherboard_version"] = mb

        return parsed


class ProtocolAA66Encrypted(VevorCommandMixin, HeaterProtocol):
    """AA66 encrypted protocol (mode=4, 48 bytes decrypted).

    Receives already-decrypted data from coordinator._detect_protocol.
    Includes configuration settings (language, tank volume, pump type, etc.).
    """

    protocol_mode = 4
    name = "AA66 encrypted"

    def parse(self, data: bytearray) -> dict[str, Any] | None:
        parsed: dict[str, Any] = {}

        parsed["running_state"] = _u8_to_number(data[3])
        parsed["error_code"] = _u8_to_number(data[35])  # Different position!
        parsed["running_step"] = _u8_to_number(data[5])
        parsed["altitude"] = (_u8_to_number(data[7]) + 256 * _u8_to_number(data[6])) / 10
        parsed["running_mode"] = _u8_to_number(data[8])
        parsed["set_level"] = max(1, min(10, _u8_to_number(data[10])))

        # Byte 27: Temperature unit (0=Celsius, 1=Fahrenheit)
        temp_unit_byte = _u8_to_number(data[27])
        parsed["temp_unit"] = temp_unit_byte
        heater_uses_fahrenheit = (temp_unit_byte == 1)

        # Byte 9: Set temperature (convert from F to C if needed)
        raw_set_temp = _u8_to_number(data[9])
        if heater_uses_fahrenheit:
            parsed["set_temp"] = max(8, min(36, round((raw_set_temp - 32) * 5 / 9)))
        else:
            parsed["set_temp"] = max(8, min(36, raw_set_temp))

        # Byte 31: Automatic Start/Stop flag
        parsed["auto_start_stop"] = (_u8_to_number(data[31]) == 1)

        # Configuration settings (bytes 26, 28, 29, 30)
        if len(data) > 26:
            parsed["language"] = _u8_to_number(data[26])

        if len(data) > 28:
            parsed["tank_volume"] = _u8_to_number(data[28])

        # Byte 29: Pump type / RF433 status (20=off, 21=on)
        if len(data) > 29:
            pump_byte = _u8_to_number(data[29])
            if pump_byte == 20:
                parsed["rf433_enabled"] = False
                parsed["pump_type"] = None
            elif pump_byte == 21:
                parsed["rf433_enabled"] = True
                parsed["pump_type"] = None
            else:
                parsed["pump_type"] = pump_byte
                parsed["rf433_enabled"] = None

        if len(data) > 30:
            parsed["altitude_unit"] = _u8_to_number(data[30])

        parsed["supply_voltage"] = (256 * data[11] + data[12]) / 10
        parsed["case_temperature"] = _unsign_to_sign(256 * data[13] + data[14])
        parsed["cab_temperature"] = _unsign_to_sign(256 * data[32] + data[33]) / 10

        # Byte 34: Temperature offset (signed)
        if len(data) > 34:
            raw = data[34]
            parsed["heater_offset"] = (raw - 256) if raw > 127 else raw

        # Byte 36: Backlight brightness
        if len(data) > 36:
            parsed["backlight"] = _u8_to_number(data[36])

        # Byte 37: CO sensor present, Bytes 38-39: CO PPM (big endian)
        if len(data) > 39:
            if _u8_to_number(data[37]) == 1:
                parsed["co_ppm"] = float(
                    (_u8_to_number(data[38]) << 8) | _u8_to_number(data[39])
                )
            else:
                parsed["co_ppm"] = None

        # Bytes 40-43: Part number (uint32 LE, hex string)
        if len(data) > 43:
            part = (
                _u8_to_number(data[40])
                | (_u8_to_number(data[41]) << 8)
                | (_u8_to_number(data[42]) << 16)
                | (_u8_to_number(data[43]) << 24)
            )
            if part != 0:
                parsed["part_number"] = format(part, 'x')

        # Byte 44: Motherboard version
        if len(data) > 44:
            mb = _u8_to_number(data[44])
            if mb != 0:
                parsed["motherboard_version"] = mb

        return parsed


class ProtocolABBA(HeaterProtocol):
    """ABBA/HeaterCC protocol (mode=5, 21+ bytes).

    Uses its own command format (BAAB header) instead of AA55.
    Does NOT need temperature calibration (sets cab_temperature_raw directly).

    Byte mapping (verified by @Xev and @postal):
    - Byte 4: Status (0=Off, 1=Heating, 2=Cooldown, 4=Ventilation, 6=Standby)
    - Byte 5: Mode (0=Level, 1=Temperature, 0xFF=Error)
    - Byte 6: Gear/Target temp or Error code
    - Byte 8: Auto Start/Stop
    - Byte 9: Voltage (decimal V)
    - Byte 10: Temperature Unit (0=C, 1=F)
    - Byte 11: Environment Temp (subtract 30 for C, 22 for F)
    - Bytes 12-13: Case Temperature (uint16 LE)
    - Byte 14: Altitude unit
    - Byte 15: High-altitude mode
    - Bytes 16-17: Altitude (uint16 LE)
    """

    protocol_mode = 5
    name = "ABBA"
    needs_calibration = False
    needs_post_status = True

    def parse(self, data: bytearray) -> dict[str, Any] | None:
        if len(data) < 21:
            return None

        parsed: dict[str, Any] = {"connected": True}

        # Byte 4: Status
        status_byte = _u8_to_number(data[4])
        parsed["running_state"] = 1 if status_byte == 0x01 else 0
        parsed["running_step"] = ABBA_STATUS_MAP.get(status_byte, status_byte)

        # Byte 5: Mode (0x00=Level, 0x01=Temperature, 0xFF=Error)
        mode_byte = _u8_to_number(data[5])
        if mode_byte == 0xFF:
            parsed["error_code"] = _u8_to_number(data[6])
            # Keep last known mode — don't set running_mode
        else:
            parsed["error_code"] = 0
            if mode_byte == 0x00:
                parsed["running_mode"] = RUNNING_MODE_LEVEL
            elif mode_byte == 0x01:
                parsed["running_mode"] = RUNNING_MODE_TEMPERATURE
            else:
                parsed["running_mode"] = mode_byte

        # Byte 6: Gear/Target temp — only parse if NOT in error state
        # (when mode_byte == 0xFF, byte 6 is the error code, not gear)
        if "running_mode" in parsed:
            gear_byte = _u8_to_number(data[6])
            if parsed["running_mode"] == RUNNING_MODE_LEVEL:
                parsed["set_level"] = max(1, min(10, gear_byte))
            else:
                parsed["set_temp"] = max(8, min(36, gear_byte))

        # Byte 8: Auto Start/Stop
        parsed["auto_start_stop"] = (_u8_to_number(data[8]) == 1)

        # Byte 9: Supply voltage
        parsed["supply_voltage"] = float(_u8_to_number(data[9]))

        # Byte 10: Temperature unit
        parsed["temp_unit"] = _u8_to_number(data[10])
        uses_fahrenheit = (parsed["temp_unit"] == 1)

        # Byte 11: Environment/Cabin temperature
        env_temp_raw = _u8_to_number(data[11])
        env_temp = env_temp_raw - (22 if uses_fahrenheit else 30)
        parsed["cab_temperature"] = float(env_temp)
        parsed["cab_temperature_raw"] = float(env_temp)

        # Bytes 12-13: Case temperature (uint16 BE)
        parsed["case_temperature"] = float(
            (_u8_to_number(data[12]) << 8) | _u8_to_number(data[13])
        )

        # Byte 14: Altitude unit
        parsed["altitude_unit"] = _u8_to_number(data[14])

        # Byte 15: High-altitude mode
        parsed["high_altitude"] = _u8_to_number(data[15])

        # Bytes 16-17: Altitude (uint16 LE)
        parsed["altitude"] = _u8_to_number(data[16]) | (_u8_to_number(data[17]) << 8)

        return parsed

    def build_command(self, command: int, argument: int, passkey: int) -> bytearray:
        """Build ABBA protocol command by translating Vevor command codes."""
        # Map Vevor commands to ABBA hex commands
        if command == 1:
            return self._build_abba("baab04cc000000")
        elif command == 3:
            # ABBA uses openOnHeat (0xA1) as a toggle: same command for
            # both ON and OFF.  The AirHeaterCC app has no explicit "off"
            # function — the Heat button toggles between heating and
            # cooldown.  The old 0xA4 (openOnBlow/ventilation) was ignored
            # by the heater while actively heating.
            return self._build_abba("baab04bba10000")
        elif command == 4:
            temp_hex = format(argument, '02x')
            return self._build_abba(f"baab04db{temp_hex}0000")
        elif command == 2:
            if argument == 2:
                return self._build_abba("baab04bbac0000")  # Const temp mode
            elif argument == 3:
                # Ventilation mode (fan-only) - 0xA4
                # Only works when heater is in standby/off state
                return self._build_abba("baab04bba40000")
            else:
                return self._build_abba("baab04bbad0000")  # Other mode
        elif command == 15:
            if argument == 1:
                return self._build_abba("baab04bba80000")  # Fahrenheit
            else:
                return self._build_abba("baab04bba70000")  # Celsius
        elif command == 19:
            if argument == 1:
                return self._build_abba("baab04bbaa0000")  # Feet
            else:
                return self._build_abba("baab04bba90000")  # Meters
        elif command == 99:
            return self._build_abba("baab04bba50000")  # High altitude toggle
        elif command == 101:
            # Ventilation command (direct) - 0xA4
            return self._build_abba("baab04bba40000")
        else:
            # Unknown command — send status request as fallback
            return self._build_abba("baab04cc000000")

    @staticmethod
    def _build_abba(cmd_hex: str) -> bytearray:
        """Build ABBA packet with checksum."""
        cmd_bytes = bytes.fromhex(cmd_hex.replace(" ", ""))
        checksum = sum(cmd_bytes) & 0xFF
        return bytearray(cmd_bytes) + bytearray([checksum])


class ProtocolCBFF(HeaterProtocol):
    """CBFF/Sunster v2.1 protocol (mode=6, 47 bytes).

    Newer protocol used by Sunster TB10Pro WiFi and similar heaters.
    Heater sends 47-byte CBFF notifications; commands use FEAA format,
    heater ACKs with AA77.

    FEAA Command Format (reverse-engineered by @Xev):
    - Bytes 0-1: FEAA header
    - Byte 2: version_num (0=heater, 10=AC)
    - Byte 3: package_num (0)
    - Bytes 4-5: total_length (uint16 LE)
    - Byte 6: cmd_1 (command code, +128 for request)
    - Byte 7: cmd_2 (0=read, 1=response, 2=cmd w/o payload, 3=cmd w/ payload)
    - Bytes 8+: payload (command-specific)
    - Last byte: checksum (sum of all previous bytes & 0xFF)

    V2.1 Protocol (AA77 beacon):
    When the heater sends 0xAA77, it's in "locked state" and requires:
    1. Handshake command (CMD1=0x06) with PIN
    2. All commands must be encrypted using double-XOR

    Encryption (discovered by @Xev from the Sunster app):
      key1 = "passwordA2409PW" (15 bytes, hardcoded)
      key2 = BLE MAC address without colons, uppercased (12 bytes)
      Apply key1 first, then key2 (XOR is order-dependent with different key lengths)

    Byte mapping (reverse-engineered from Sunster app by @Xev).
    """

    protocol_mode = 6
    name = "CBFF"

    def __init__(self) -> None:
        self._device_sn: str | None = None
        self._v21_mode: bool = False  # Enable V2.1 encrypted mode

    def set_device_sn(self, sn: str) -> None:
        """Set the device serial number (BLE MAC without colons, uppercased).

        Used as key2 for CBFF double-XOR encryption/decryption.
        """
        self._device_sn = sn

    def set_v21_mode(self, enabled: bool) -> None:
        """Enable or disable V2.1 encrypted mode.

        When enabled, all outgoing commands will be encrypted with double-XOR.
        This should be enabled when the heater sends AA77 (locked state).
        """
        self._v21_mode = enabled

    @property
    def v21_mode(self) -> bool:
        """Return True if V2.1 encrypted mode is enabled."""
        return self._v21_mode

    def build_handshake(self, passkey: int) -> bytearray:
        """Build V2.1 handshake/authentication command.

        The handshake is required when the heater sends AA77 (locked state).
        The PIN is encoded as two bytes: [PIN % 100, PIN // 100].

        Args:
            passkey: 4-digit PIN code (0000-9999)

        Returns:
            Encrypted FEAA handshake packet
        """
        # PIN encoding: e.g., 1234 -> [34, 12]
        payload = bytes([passkey % 100, passkey // 100])
        packet = self._build_feaa(cmd_1=0x86, cmd_2=0x00, payload=payload)

        # Handshake is always encrypted in V2.1
        if self._device_sn:
            return self._encrypt_cbff(packet, self._device_sn)
        return packet

    def build_command(self, command: int, argument: int, passkey: int) -> bytearray:
        """Build FEAA command packet for CBFF/Sunster heaters.

        Command mapping:
        - cmd 0: Status request (FEAA cmd_1=0x80, cmd_2=0x00)
        - cmd 1: Status request (same as 0)
        - cmd 3: Power on/off (FEAA cmd_1=0x81, cmd_2=0x03, payload=arg)
        - cmd 4: Set temperature (FEAA cmd_1=0x81, cmd_2=0x03, payload=[2, temp])
        - cmd 5: Set level (FEAA cmd_1=0x81, cmd_2=0x03, payload=[1, level])
        - cmd 14-21: Config commands (use AA55 fallback for compatibility)

        In V2.1 mode, commands are encrypted with double-XOR before sending.
        """
        # Status request
        if command in (0, 1):
            packet = self._build_feaa(cmd_1=0x80, cmd_2=0x00)

        # Power on/off (cmd 3: argument=1 for on, 0 for off)
        elif command == 3:
            # V2.1: Power ON needs mode+param+time, OFF is simpler
            if self._v21_mode and argument == 1:
                # Power ON with default settings: mode=1 (level), param=5, time=0xFFFF (infinite)
                payload = bytes([1, 5, 0xFF, 0xFF])
                packet = self._build_feaa(cmd_1=0x81, cmd_2=0x01, payload=payload)
            elif self._v21_mode and argument == 0:
                # Power OFF: 9-byte packet (no payload needed)
                packet = self._build_feaa(cmd_1=0x81, cmd_2=0x00)
            else:
                packet = self._build_feaa(cmd_1=0x81, cmd_2=0x03, payload=bytes([argument]))

        # Set temperature (cmd 4)
        elif command == 4:
            if self._v21_mode:
                # V2.1: mode=2 (temp), param=temp, time=0xFFFF
                payload = bytes([2, argument, 0xFF, 0xFF])
                packet = self._build_feaa(cmd_1=0x81, cmd_2=0x01, payload=payload)
            else:
                packet = self._build_feaa(cmd_1=0x81, cmd_2=0x03, payload=bytes([2, argument]))

        # Set level (cmd 5)
        elif command == 5:
            if self._v21_mode:
                # V2.1: mode=1 (level), param=level, time=0xFFFF
                payload = bytes([1, argument, 0xFF, 0xFF])
                packet = self._build_feaa(cmd_1=0x81, cmd_2=0x01, payload=payload)
            else:
                packet = self._build_feaa(cmd_1=0x81, cmd_2=0x03, payload=bytes([1, argument]))

        # Set mode (cmd 2)
        elif command == 2:
            packet = self._build_feaa(cmd_1=0x81, cmd_2=0x02)

        # Config commands (14-21): Fall back to AA55 for now
        elif command in (14, 15, 16, 17, 19, 20, 21):
            return self._build_aa55_fallback(command, argument, passkey)

        # Default: status request
        else:
            packet = self._build_feaa(cmd_1=0x80, cmd_2=0x00)

        # Encrypt if V2.1 mode is enabled
        if self._v21_mode and self._device_sn:
            return self._encrypt_cbff(packet, self._device_sn)
        return packet

    @staticmethod
    def _build_feaa(cmd_1: int, cmd_2: int, payload: bytes = b"") -> bytearray:
        """Build FEAA packet with checksum.

        Format: FEAA + version + pkg_num + length(2) + cmd_1 + cmd_2 + payload + checksum
        """
        # Base length: header(2) + version(1) + pkg_num(1) + length(2) + cmd_1(1) + cmd_2(1) = 8
        # Plus payload + checksum
        total_length = 8 + len(payload) + 1

        packet = bytearray([
            0xFE, 0xAA,          # Header
            0x00,                # version_num (0=heater)
            0x00,                # package_num
            total_length & 0xFF, # length LSB
            (total_length >> 8) & 0xFF,  # length MSB
            cmd_1,               # command code
            cmd_2,               # command type
        ])
        packet.extend(payload)

        # Checksum: sum of all bytes & 0xFF
        checksum = sum(packet) & 0xFF
        packet.append(checksum)

        return packet

    @staticmethod
    def _build_aa55_fallback(command: int, argument: int, passkey: int) -> bytearray:
        """Build 8-byte AA55 command packet (fallback for config commands)."""
        packet = bytearray([0xAA, 0x55, 0, 0, 0, 0, 0, 0])
        packet[2] = passkey // 100
        packet[3] = passkey % 100
        packet[4] = command % 256
        packet[5] = argument % 256
        packet[6] = (argument // 256) % 256
        packet[7] = (packet[2] + packet[3] + packet[4] + packet[5] + packet[6]) % 256
        return packet

    def parse(self, data: bytearray) -> dict[str, Any] | None:
        if len(data) < 46:
            return None

        # Try parsing raw data first (unencrypted CBFF)
        parsed = self._parse_cbff_fields(data)
        if not self._is_data_suspect(parsed):
            return parsed

        # Raw data looks wrong — try decryption if device_sn is available
        if self._device_sn:
            decrypted = self._decrypt_cbff(data, self._device_sn)
            parsed_dec = self._parse_cbff_fields(decrypted)
            if not self._is_data_suspect(parsed_dec):
                parsed_dec["_cbff_decrypted"] = True
                return parsed_dec

        # Neither raw nor decrypted data is valid
        parsed["_cbff_data_suspect"] = True
        for key in (
            "cab_temperature", "case_temperature", "supply_voltage",
            "altitude", "co_ppm", "heater_offset", "error_code",
            "running_step", "running_mode", "set_level", "set_temp",
            "temp_unit", "altitude_unit", "language", "tank_volume",
            "pump_type", "rf433_enabled", "backlight", "startup_temp_diff",
            "shutdown_temp_diff", "wifi_enabled", "auto_start_stop",
            "heater_mode", "remain_run_time", "hardware_version",
            "software_version", "pwr_onoff",
        ):
            parsed.pop(key, None)
        return parsed

    @staticmethod
    def _is_data_suspect(parsed: dict[str, Any]) -> bool:
        """Check if parsed CBFF data has physically impossible values."""
        voltage = parsed.get("supply_voltage", 0)
        cab_temp = parsed.get("cab_temperature", 0)
        return voltage > 100 or voltage < 0 or abs(cab_temp) > 500

    @staticmethod
    def _encrypt_cbff(data: bytearray, device_sn: str) -> bytearray:
        """Encrypt CBFF data using double-XOR (key1 + key2).

        This is symmetric with decryption (XOR is its own inverse).

        key1 = "passwordA2409PW" (15 bytes, hardcoded in Sunster app)
        key2 = device_sn.upper() (BLE MAC without colons)
        """
        key1 = bytearray(SUNSTER_V21_KEY)
        key2 = bytearray(device_sn.upper().encode("ascii"))
        out = bytearray(data)

        j = 0
        for i in range(len(out)):
            out[i] ^= key1[j]
            j = (j + 1) % len(key1)

        j = 0
        for i in range(len(out)):
            out[i] ^= key2[j]
            j = (j + 1) % len(key2)

        return out

    @staticmethod
    def _decrypt_cbff(data: bytearray, device_sn: str) -> bytearray:
        """Decrypt CBFF data using double-XOR (key1 + key2).

        Same algorithm as encrypt (XOR is symmetric).
        key1 = "passwordA2409PW" (15 bytes, hardcoded in Sunster app)
        key2 = device_sn.upper() (BLE MAC without colons)
        """
        return ProtocolCBFF._encrypt_cbff(data, device_sn)

    @staticmethod
    def _parse_cbff_fields(data: bytearray) -> dict[str, Any]:
        """Parse CBFF byte fields into a dict."""
        parsed: dict[str, Any] = {"connected": True}

        # Byte 2: protocol_version (stored for diagnostics)
        parsed["cbff_protocol_version"] = _u8_to_number(data[2])

        # Byte 10: run_state (2/5/6 = OFF)
        parsed["running_state"] = 0 if _u8_to_number(data[10]) in CBFF_RUN_STATE_OFF else 1

        # Byte 14: run_step
        parsed["running_step"] = _u8_to_number(data[14])

        # Byte 11: run_mode (1/3/4=Level, 2=Temperature)
        run_mode = _u8_to_number(data[11])
        if run_mode in (1, 3, 4):
            parsed["running_mode"] = RUNNING_MODE_LEVEL
        elif run_mode == 2:
            parsed["running_mode"] = RUNNING_MODE_TEMPERATURE
        else:
            parsed["running_mode"] = RUNNING_MODE_MANUAL

        # Byte 12: run_param
        run_param = _u8_to_number(data[12])
        if parsed["running_mode"] == RUNNING_MODE_LEVEL:
            parsed["set_level"] = max(1, min(10, run_param))
        else:
            parsed["set_temp"] = max(8, min(36, run_param))

        # Byte 13: now_gear (current gear even in temp mode)
        if parsed["running_mode"] == RUNNING_MODE_TEMPERATURE:
            parsed["set_level"] = max(1, min(10, _u8_to_number(data[13])))

        # Byte 15: fault_display
        parsed["error_code"] = _u8_to_number(data[15]) & 0x3F

        # Byte 17: temp_unit (lower nibble)
        parsed["temp_unit"] = _u8_to_number(data[17]) & 0x0F

        # Bytes 18-19: cabin temperature (int16 LE)
        cab = data[18] | (data[19] << 8)
        if cab >= 32768:
            cab -= 65536
        parsed["cab_temperature"] = float(cab)

        # Byte 20: altitude_unit (lower nibble)
        parsed["altitude_unit"] = _u8_to_number(data[20]) & 0x0F

        # Bytes 21-22: altitude (uint16 LE)
        parsed["altitude"] = data[21] | (data[22] << 8)

        # Bytes 23-24: voltage (uint16 LE, /10)
        parsed["supply_voltage"] = (data[23] | (data[24] << 8)) / 10.0

        # Bytes 25-26: case temperature (int16 LE, /10)
        case = data[25] | (data[26] << 8)
        if case >= 32768:
            case -= 65536
        parsed["case_temperature"] = case / 10.0

        # Bytes 27-28: CO sensor (uint16 LE, /10)
        co_ppm = (data[27] | (data[28] << 8)) / 10.0
        parsed["co_ppm"] = co_ppm if co_ppm < 6553 else None

        # Byte 34: temp_comp (int8)
        temp_comp = data[34]
        parsed["heater_offset"] = (temp_comp - 256) if temp_comp > 127 else temp_comp

        # Byte 35: language
        lang = _u8_to_number(data[35])
        if lang != 255:
            parsed["language"] = lang

        # Byte 36: tank volume index
        tank = _u8_to_number(data[36])
        if tank != 255:
            parsed["tank_volume"] = tank

        # Byte 37: pump_model / RF433
        pump = _u8_to_number(data[37])
        if pump != 255:
            if pump == 20:
                parsed["rf433_enabled"] = False
                parsed["pump_type"] = None
            elif pump == 21:
                parsed["rf433_enabled"] = True
                parsed["pump_type"] = None
            else:
                parsed["pump_type"] = pump
                parsed["rf433_enabled"] = None

        # Byte 29: pwr_onoff
        parsed["pwr_onoff"] = _u8_to_number(data[29])

        # Bytes 30-31: hardware_version (uint16 LE)
        hw_ver = data[30] | (data[31] << 8)
        if hw_ver != 0:
            parsed["hardware_version"] = hw_ver

        # Bytes 32-33: software_version (uint16 LE)
        sw_ver = data[32] | (data[33] << 8)
        if sw_ver != 0:
            parsed["software_version"] = sw_ver

        # Byte 38: back_light (255=not available)
        backlight = _u8_to_number(data[38])
        if backlight != 255:
            parsed["backlight"] = backlight

        # Byte 39: startup_temp_difference (255=not available)
        startup_diff = _u8_to_number(data[39])
        if startup_diff != 255:
            parsed["startup_temp_diff"] = startup_diff

        # Byte 40: shutdown_temp_difference (255=not available)
        shutdown_diff = _u8_to_number(data[40])
        if shutdown_diff != 255:
            parsed["shutdown_temp_diff"] = shutdown_diff

        # Byte 41: wifi (255=not available)
        wifi = _u8_to_number(data[41])
        if wifi != 255:
            parsed["wifi_enabled"] = (wifi == 1)

        # Byte 42: auto start/stop
        parsed["auto_start_stop"] = (_u8_to_number(data[42]) == 1)

        # Byte 43: heater_mode
        parsed["heater_mode"] = _u8_to_number(data[43])

        # Bytes 44-45: remain_run_time (uint16 LE, 65535=not available)
        remain = data[44] | (data[45] << 8)
        if remain != 65535:
            parsed["remain_run_time"] = remain

        return parsed


class ProtocolHcalory(HeaterProtocol):
    """Hcalory MVP1/MVP2 protocol (mode=7).

    Used by Hcalory HBU1S and similar heaters.
    Completely different packet structure from AA55/ABBA/CBFF.

    MVP1: Service UUID 0000FFF0-..., older models
    MVP2: Service UUID 0000BD39-..., newer models (e.g., HBU1S)

    Protocol reverse-engineered by @Xev from Hcalory APK.
    """

    protocol_mode = 7
    name = "Hcalory"
    needs_calibration = True
    needs_post_status = True

    def __init__(self) -> None:
        """Initialize Hcalory protocol handler."""
        self._is_mvp2: bool = True  # Default to MVP2, can be set by coordinator
        self._password_sent: bool = False  # Track if MVP2 password handshake was sent

    def set_mvp_version(self, is_mvp2: bool) -> None:
        """Set MVP version (MVP1 vs MVP2) based on service UUID detection."""
        self._is_mvp2 = is_mvp2
        self._password_sent = False  # Reset password state on version change

    def reset_password_state(self) -> None:
        """Reset password handshake state (call on reconnect)."""
        self._password_sent = False

    @property
    def needs_password_handshake(self) -> bool:
        """Check if MVP2 password handshake is needed."""
        return self._is_mvp2 and not self._password_sent

    def mark_password_sent(self) -> None:
        """Mark password handshake as completed."""
        self._password_sent = True

    def parse(self, data: bytearray) -> dict[str, Any] | None:
        """Parse Hcalory response data.

        Response structure (hex character positions from protocol docs):
        - 0-3: device_id (4 chars)
        - 4-7: timestamp (4 chars)
        - 8-11: reserved (4 chars)
        - 12-13: highland_gear (2 chars)
        - 14-15: reserved (2 chars)
        - 16-17: status_flags (2 chars)
        - 18-19: device_state (2 chars)
        - 20-21: temp_or_gear (2 chars)
        - 22-23: auto_start_stop (2 chars)
        - 24-27: voltage_raw (4 chars, x10)
        - 28-29: shell_temp_sign (2 chars)
        - 30-33: shell_temp_raw (4 chars, x10)
        - 34-35: ambient_temp_sign (2 chars)
        - 36-39: ambient_temp_raw (4 chars, x10)
        - 40-45: reserved (6 chars)
        - 46-47: scene_id (2 chars)
        - 48-49: highland_mode (2 chars)
        - 50-51: temp_unit (2 chars)
        MVP2 extended (60+ chars):
        - 52-53: height_unit (2 chars)
        - 54-55: altitude_sign (2 chars)
        - 56-59: altitude_raw (4 chars)
        """
        # Convert to hex string for character-based parsing
        hex_str = data.hex().upper()

        # Minimum length: 52 hex chars (26 bytes) for basic parsing
        if len(hex_str) < 52:
            return None

        parsed: dict[str, Any] = {"connected": True}

        try:
            # Status flags (chars 16-17)
            if len(hex_str) >= 18:
                status_flags = self._parse_status_flags(hex_str[16:18])
                parsed.update(status_flags)

            # Device state (chars 18-19)
            if len(hex_str) >= 20:
                device_state = int(hex_str[18:20], 16)
                parsed["hcalory_device_state"] = device_state

                # Map to running_state
                if device_state == HCALORY_STATE_STANDBY:
                    parsed["running_state"] = 0
                    parsed["running_step"] = 0  # Standby
                elif device_state == HCALORY_STATE_MACHINE_FAULT:
                    parsed["running_state"] = 0
                    # Error code will be in operative state
                else:
                    parsed["running_state"] = 1

                # Map to running_mode
                if device_state == HCALORY_STATE_HEATING_TEMP_AUTO:
                    parsed["running_mode"] = RUNNING_MODE_TEMPERATURE
                elif device_state == HCALORY_STATE_HEATING_MANUAL_GEAR:
                    parsed["running_mode"] = RUNNING_MODE_LEVEL
                elif device_state == HCALORY_STATE_NATURAL_WIND:
                    parsed["running_mode"] = RUNNING_MODE_MANUAL  # Fan-only
                else:
                    parsed["running_mode"] = RUNNING_MODE_MANUAL

            # Temp or gear (chars 20-21)
            if len(hex_str) >= 22:
                temp_or_gear = int(hex_str[20:22], 16)
                if parsed.get("running_mode") == RUNNING_MODE_TEMPERATURE:
                    parsed["set_temp"] = max(8, min(36, temp_or_gear))
                else:
                    # Beta.33: Hcalory uses 1-6 gear levels directly (no mapping, issue #40)
                    hcalory_level = max(HCALORY_MIN_LEVEL, min(HCALORY_MAX_LEVEL, temp_or_gear))
                    parsed["set_level"] = hcalory_level

            # Auto start/stop (chars 22-23)
            if len(hex_str) >= 24:
                parsed["auto_start_stop"] = (int(hex_str[22:24], 16) == 1)

            # Voltage (chars 24-27, 4 chars = 16-bit, /10)
            if len(hex_str) >= 28:
                voltage_raw = int(hex_str[24:28], 16)
                parsed["supply_voltage"] = voltage_raw / 10.0

            # Shell/Case temperature sign (chars 28-29) and value (chars 30-33)
            if len(hex_str) >= 34:
                shell_sign = hex_str[28:30]
                shell_value = int(hex_str[30:34], 16)
                sign = -1 if shell_sign == "01" else 1
                parsed["case_temperature"] = (sign * shell_value) / 10.0

            # Ambient/Cabin temperature sign (chars 34-35) and value (chars 36-39)
            if len(hex_str) >= 40:
                ambient_sign = hex_str[34:36]
                ambient_value = int(hex_str[36:40], 16)
                sign = -1 if ambient_sign == "01" else 1
                parsed["cab_temperature"] = (sign * ambient_value) / 10.0

            # Highland mode (chars 48-49)
            if len(hex_str) >= 50:
                parsed["high_altitude"] = int(hex_str[48:50], 16)

            # Temperature unit (chars 50-51)
            if len(hex_str) >= 52:
                parsed["temp_unit"] = int(hex_str[50:52], 16)

            # MVP2 extended fields (chars 52-59)
            if len(hex_str) >= 60:
                # Height unit (chars 52-53)
                parsed["altitude_unit"] = int(hex_str[52:54], 16)

                # Altitude sign (chars 54-55) and value (chars 56-59)
                altitude_sign = hex_str[54:56]
                altitude_value = int(hex_str[56:60], 16)
                sign = -1 if altitude_sign == "01" else 1
                parsed["altitude"] = sign * altitude_value

            # Check for error state
            if parsed.get("hcalory_device_state") == HCALORY_STATE_MACHINE_FAULT:
                # Error code from operative state bits
                op_bits = parsed.get("operative_state_bits", "00")
                parsed["error_code"] = int(op_bits, 2) if op_bits else 0
            else:
                parsed["error_code"] = 0

        except (ValueError, IndexError):
            # Parse error - return minimal data
            parsed["_hcalory_parse_error"] = True

        return parsed

    @staticmethod
    def _parse_status_flags(flags_hex: str) -> dict[str, Any]:
        """Parse Hcalory status flags byte (bit-reversed).

        Returns dict with:
        - heating_is_starting: bool
        - heating_is_stopping: bool
        - fan_is_running: bool
        - ignition_plug_running: bool
        - oil_pump_running: bool
        - operative_state_bits: str (2-char binary)
        """
        result: dict[str, Any] = {}
        try:
            flags_byte = int(flags_hex, 16)
            # Reverse the bits
            reversed_binary = format(flags_byte, '08b')[::-1]

            result["heating_is_starting"] = reversed_binary[0] == '1'
            result["heating_is_stopping"] = reversed_binary[1] == '1'
            result["fan_is_running"] = reversed_binary[2] == '1'
            result["ignition_plug_running"] = reversed_binary[3] == '1'
            result["oil_pump_running"] = reversed_binary[4] == '1'
            result["operative_state_bits"] = reversed_binary[6:8]

            # Map operative state to running_step
            op_state = reversed_binary[6:8]
            if op_state == "00":
                result["running_step"] = 0  # Stopped
            elif op_state == "01":
                result["running_step"] = 3  # Running/Heating
            elif op_state == "10":
                result["running_step"] = 4  # Cooldown
            elif op_state == "11":
                result["running_step"] = 6  # Fan/Natural wind

        except (ValueError, IndexError):
            pass

        return result

    @staticmethod
    def _map_hcalory_to_standard_level(hcalory_level: int) -> int:
        """Map Hcalory 1-6 gear to standard 1-10 level.

        Hcalory: 1, 2, 3, 4, 5, 6
        Standard: 2, 4, 5, 6, 8, 10
        """
        mapping = {1: 2, 2: 4, 3: 5, 4: 6, 5: 8, 6: 10}
        return mapping.get(hcalory_level, max(1, min(10, hcalory_level * 2)))

    @staticmethod
    def _map_standard_to_hcalory_level(standard_level: int) -> int:
        """Map standard 1-10 level to Hcalory 1-6 gear.

        Standard: 1-2->1, 3-4->2, 5->3, 6->4, 7-8->5, 9-10->6
        """
        if standard_level <= 2:
            return 1
        elif standard_level <= 4:
            return 2
        elif standard_level == 5:
            return 3
        elif standard_level == 6:
            return 4
        elif standard_level <= 8:
            return 5
        else:
            return 6

    def build_command(self, command: int, argument: int, passkey: int) -> bytearray:
        """Build Hcalory command packet.

        Command mapping from standard Vevor commands:
        - 0, 1: Status query
        - 2: Set mode (Temperature=2, Level=1)
        - 3: Power on/off
        - 4: Set temperature
        - 5: Set gear level
        - 14: Set altitude
        - 15: Set temp unit (Celsius/Fahrenheit)

        MVP1 vs MVP2 differences:
        - MVP1: Uses dpID 0E04 for query with 9-byte payload
        - MVP2: Uses dpID 0A0A for query with timestamp payload
        """
        # Status request - different for MVP1 vs MVP2
        if command in (0, 1):
            if self._is_mvp2:
                # MVP2: Use 0A0A with timestamp
                return self._build_mvp2_query_cmd()
            else:
                # MVP1: Use 0E04 with query byte
                return self._build_hcalory_cmd(
                    HCALORY_CMD_POWER,
                    bytes([0, 0, 0, 0, 0, 0, 0, 0, HCALORY_POWER_QUERY])
                )

        # Set mode (cmd 2) - Temperature=2, Level=1
        if command == 2:
            # argument: 1=Level mode, 2=Temperature mode
            mode_value = max(1, min(2, argument))
            return self._build_hcalory_cmd(
                HCALORY_CMD_SET_MODE,
                bytes([mode_value, 0])  # mode, padding
            )

        # Power on/off (cmd 3)
        if command == 3:
            power_arg = HCALORY_POWER_ON if argument == 1 else HCALORY_POWER_OFF
            return self._build_hcalory_cmd(
                HCALORY_CMD_POWER,
                bytes([0, 0, 0, 0, 0, 0, 0, 0, power_arg])
            )

        # Set temperature (cmd 4)
        if command == 4:
            temp = max(8, min(36, argument))
            # Unit: 0=Celsius, 1=Fahrenheit
            return self._build_hcalory_cmd(
                HCALORY_CMD_SET_TEMP,
                bytes([temp, 0])  # temp, unit=Celsius
            )

        # Set level (cmd 5)
        if command == 5:
            # Beta.33: Use level 1-6 directly, no mapping (issue #40)
            level = max(HCALORY_MIN_LEVEL, min(HCALORY_MAX_LEVEL, argument))
            return self._build_hcalory_cmd(
                HCALORY_CMD_SET_GEAR,
                bytes([level])
            )

        # Set auto start/stop (custom: cmd 22)
        if command == 22:
            auto_arg = HCALORY_POWER_AUTO_ON if argument == 1 else HCALORY_POWER_AUTO_OFF
            return self._build_hcalory_cmd(
                HCALORY_CMD_POWER,
                bytes([0, 0, 0, 0, 0, 0, 0, 0, auto_arg])
            )

        # Set temperature unit (cmd 15)
        if command == 15:
            temp_unit_arg = HCALORY_POWER_FAHRENHEIT if argument == 1 else HCALORY_POWER_CELSIUS
            return self._build_hcalory_cmd(
                HCALORY_CMD_POWER,
                bytes([0, 0, 0, 0, 0, 0, 0, 0, temp_unit_arg])
            )

        # Set altitude (cmd 14)
        if command == 14:
            # argument is altitude in meters
            sign = 0x00 if argument >= 0 else 0x01
            alt_abs = abs(argument)
            unit = 0x00  # Meters
            return self._build_hcalory_cmd(
                HCALORY_CMD_SET_ALTITUDE,
                bytes([sign, (alt_abs >> 8) & 0xFF, alt_abs & 0xFF, unit])
            )

        # Default: status query
        return self._build_hcalory_cmd(
            HCALORY_CMD_POWER,
            bytes([0, 0, 0, 0, 0, 0, 0, 0, HCALORY_POWER_QUERY])
        )

    @staticmethod
    def _build_hcalory_cmd(cmd_type: int, payload: bytes) -> bytearray:
        """Build Hcalory command packet with checksum.

        Format (based on @Xev's analysis, issue #34):
        - Bytes 0-7: Header (00 02 00 01 00 01 00 XX)
          - Bytes 0-1: Protocol ID (00 02)
          - Bytes 2-3: Reserved (00 01)
          - Bytes 4-5: Flags (00 01 = expects response)
          - Bytes 6-7: Command type high byte (00 XX)
        - Bytes 8+: Payload for checksum calculation:
          - Byte 8: Command type low byte (YY)
          - Bytes 9-10: Padding (00 00)
          - Byte 11: Payload length
          - Bytes 12+: Actual payload data
        - Last byte: Checksum = sum(bytes 8 onwards) & 0xFF

        Example - Set Temperature to 20:
          00 02 00 01 00 01 00 07 | 06 00 00 02 14 00 | 1C
          Header (0-7)            | Payload (8-13)    | Checksum=28
        """
        cmd_hi = (cmd_type >> 8) & 0xFF
        cmd_lo = cmd_type & 0xFF
        payload_len = len(payload)

        # Build header (bytes 0-7)
        packet = bytearray([
            0x00, 0x02,  # Protocol ID (bytes 0-1)
            0x00, 0x01,  # Reserved (bytes 2-3)
            0x00, 0x01,  # Flags (bytes 4-5)
            0x00, cmd_hi,  # Command high (bytes 6-7)
        ])

        # Build payload for checksum calculation (bytes 8+)
        payload_for_checksum = bytearray([
            cmd_lo,  # Command low (byte 8)
            0x00, 0x00,  # Padding (bytes 9-10)
            payload_len,  # Payload length (byte 11)
        ])
        payload_for_checksum.extend(payload)

        packet.extend(payload_for_checksum)

        # Calculate checksum on payload portion only (bytes 8 onwards)
        checksum = sum(payload_for_checksum) & 0xFF
        packet.append(checksum)

        return packet

    @staticmethod
    def _to_bcd(num: int) -> int:
        """Convert a decimal number (0-99) to a single BCD byte."""
        return ((num // 10) << 4) | (num % 10)

    def _build_mvp2_query_cmd(self) -> bytearray:
        """Build MVP2 query state command with timestamp.

        MVP2 uses dpID 0A0A with timestamp payload:
        Template: 00 02 00 01 00 01 00 0A 0A 00 00 05 [TIMESTAMP] 00 + checksum

        Timestamp is 6 bytes: HH MM SS 00 00 00 (BCD encoded)
        """
        now = datetime.now()
        timestamp = bytes([
            self._to_bcd(now.hour),
            self._to_bcd(now.minute),
            self._to_bcd(now.second),
            0x00, 0x00, 0x00  # Padding
        ])

        # Build packet: header + dpID 0A0A + payload length (5) + timestamp + 00
        packet = bytearray([
            0x00, 0x02,  # Protocol ID
            0x00, 0x01,  # Reserved
            0x00, 0x01,  # Flags (expects response)
            0x00, 0x0A, 0x0A, 0x00,  # dpID 0A0A
            0x00, 0x05,  # Payload length = 5 (timestamp bytes used)
        ])

        # Add timestamp (first 5 bytes: HH MM SS 00 00) + trailing 00
        packet.extend(timestamp[:5])
        packet.append(0x00)

        # Calculate checksum
        checksum = sum(packet) & 0xFF
        packet.append(checksum)

        return packet

    def build_password_handshake(self, passkey: int = 1234) -> bytearray:
        """Build MVP2 password handshake command.

        MVP2 requires password authentication before accepting commands.
        dpID 0A0C with payload: 05 01 [D1] [D2] [D3] [D4]

        Password encoding: each digit as separate byte with leading zero
        Example: "1234" -> 01 02 03 04

        Args:
            passkey: 4-digit PIN code (default 1234)

        Returns:
            Password handshake command packet
        """
        # Extract individual digits from passkey
        digits = []
        pk = passkey
        for _ in range(4):
            digits.insert(0, pk % 10)
            pk //= 10

        # Build packet according to @Xev's analysis (issue #34)
        # Correct structure for PIN=0: 00 02 00 01 00 01 00 0A 0C 00 00 05 01 00 00 00 00 12
        # Header (bytes 0-7): 00 02 00 01 00 01 00 0A
        # Payload for checksum (bytes 8-16): 0C 00 00 05 01 D1 D2 D3 D4
        # Checksum (byte 17): sum(bytes 8-16) & 0xFF

        packet = bytearray([
            0x00, 0x02,  # Protocol ID (bytes 0-1)
            0x00, 0x01,  # Reserved (bytes 2-3)
            0x00, 0x01,  # Flags (bytes 4-5)
            0x00, 0x0A,  # Command 0A (bytes 6-7)
        ])

        # Payload for checksum calculation starts here (byte 8)
        # Structure: 0C 00 00 05 01 D1 D2 D3 D4
        payload_for_checksum = bytearray([
            0x0C, 0x00, 0x00,  # dpID continuation + padding
            0x05,  # Payload type/length indicator
            0x01,  # Fixed byte
        ])
        payload_for_checksum.extend(digits)  # Add 4 PIN digits

        packet.extend(payload_for_checksum)

        # Calculate checksum on bytes 8 onwards
        checksum = sum(payload_for_checksum) & 0xFF
        packet.append(checksum)

        return packet
