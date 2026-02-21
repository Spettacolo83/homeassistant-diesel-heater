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

        MVP2 Byte mapping (reverse-engineered by @Xev, issue #34):
        - Byte 18: Altitude mode (0-2)
        - Byte 20: Complete state byte (high nibble=status, low nibble=running_step)
        - Byte 21: Set mode (0=Off, 1=Temperature, 2=Level, 3=Ventilation)
        - Byte 22: Set value (temperature or gear level)
        - Byte 23: Auto start/stop (1=on, 2=off per @Xev's dumps)
        - Bytes 24-25: Voltage (uint16 LE, /10)
        - Bytes 27-28: Shell/Case temperature (uint16 LE, /10)
        - Bytes 30-31: Ambient/Cabin temperature (uint16 LE, /10)
        - Byte 37: Temperature unit (0=C, 1=F)

        Status byte (byte 20) parsing:
        - High nibble (bits 4-7): Running status (0x0=Off, 0x4=Turning Off, 0x8=Heating, 0xC=Ventilation, 0xF=Error)
        - Low nibble (bits 0-3): Running step (0x0=Inactive, 0x1=Fan, 0x3=Ignition, 0x5=Running, 0x7=Standby)
        """
        # Minimum length: 38 bytes for MVP2
        if len(data) < 38:
            return None

        parsed: dict[str, Any] = {"connected": True}

        try:
            # Import MVP2 constants
            from .const import (
                HCALORY_RUNNING_STATUS_OFF,
                HCALORY_RUNNING_STATUS_TURNING_OFF,
                HCALORY_RUNNING_STATUS_HEATING,
                HCALORY_RUNNING_STATUS_VENTILATION,
                HCALORY_RUNNING_STATUS_ERROR,
                HCALORY_RUNNING_STEP_INACTIVE,
                HCALORY_RUNNING_STEP_FAN,
                HCALORY_RUNNING_STEP_IGNITION,
                HCALORY_RUNNING_STEP_COOLDOWN,
                HCALORY_RUNNING_STEP_RUNNING,
                HCALORY_RUNNING_STEP_STANDBY,
                HCALORY_MODE_OFF,
                HCALORY_MODE_TEMPERATURE,
                HCALORY_MODE_LEVEL,
                HCALORY_MODE_VENTILATION,
            )

            # Byte 20: Complete state byte (status in high nibble, running_step in low nibble)
            complete_state_byte = _u8_to_number(data[20])
            status = (complete_state_byte & 0xF0) >> 4  # High nibble
            running_step_raw = complete_state_byte & 0x0F  # Low nibble

            # Synthetic COOLDOWN state: when status is TURNING_OFF, set running_step to COOLDOWN
            if status == HCALORY_RUNNING_STATUS_TURNING_OFF:
                running_step = HCALORY_RUNNING_STEP_COOLDOWN
            else:
                running_step = running_step_raw

            # Store raw values for diagnostics
            parsed["hcalory_status"] = status
            parsed["hcalory_running_step"] = running_step

            # Map status to running_state (0=off, 1=on)
            if status in (HCALORY_RUNNING_STATUS_OFF, HCALORY_RUNNING_STATUS_ERROR):
                parsed["running_state"] = 0
            else:
                parsed["running_state"] = 1

            # Map running_step to standard running_step
            # MVP2 steps: 0x0=Inactive, 0x1=Fan, 0x3=Ignition, 0x4=Cooldown, 0x5=Running, 0x7=Standby
            # Standard steps: 0=Standby, 1=Self-test, 2=Ignition, 3=Running, 4=Cooldown, 6=Ventilation
            step_mapping = {
                HCALORY_RUNNING_STEP_INACTIVE: 0,  # Standby
                HCALORY_RUNNING_STEP_FAN: 6,  # Ventilation/Fan
                HCALORY_RUNNING_STEP_IGNITION: 2,  # Ignition
                HCALORY_RUNNING_STEP_COOLDOWN: 4,  # Cooldown
                HCALORY_RUNNING_STEP_RUNNING: 3,  # Running
                HCALORY_RUNNING_STEP_STANDBY: 0,  # Standby
            }
            parsed["running_step"] = step_mapping.get(running_step, running_step)

            # Byte 21: Set mode (0=Off, 1=Temperature, 2=Level, 3=Ventilation)
            set_mode = _u8_to_number(data[21])
            parsed["hcalory_set_mode"] = set_mode

            # Map set_mode to running_mode
            if set_mode == HCALORY_MODE_TEMPERATURE:
                parsed["running_mode"] = RUNNING_MODE_TEMPERATURE
            elif set_mode == HCALORY_MODE_LEVEL:
                parsed["running_mode"] = RUNNING_MODE_LEVEL
            elif set_mode == HCALORY_MODE_VENTILATION:
                parsed["running_mode"] = RUNNING_MODE_MANUAL  # Fan-only
            else:
                parsed["running_mode"] = RUNNING_MODE_MANUAL

            # Byte 22: Set value (temperature or gear) - BUT can be None when heater is OFF
            set_value_raw = _u8_to_number(data[22])

            # Critical: set_value is None when heater is OFF, TURNING_OFF, or ERROR (@Xev's discovery)
            if complete_state_byte == HCALORY_RUNNING_STATUS_OFF or status in (HCALORY_RUNNING_STATUS_TURNING_OFF, HCALORY_RUNNING_STATUS_ERROR):
                # Heater is OFF - don't parse set_value (coordinator must remember last value)
                parsed["hcalory_set_value_none"] = True
            else:
                # Heater is ON - parse set_value based on mode
                if parsed.get("running_mode") == RUNNING_MODE_TEMPERATURE:
                    parsed["set_temp"] = max(8, min(36, set_value_raw))
                else:
                    # Hcalory uses 1-6 gear levels, map to 1-10
                    hcalory_level = max(HCALORY_MIN_LEVEL, min(HCALORY_MAX_LEVEL, set_value_raw))
                    parsed["set_level"] = self._map_hcalory_to_standard_level(hcalory_level)
                    parsed["hcalory_gear"] = hcalory_level

            # Byte 23: Auto start/stop (@Xev note 2026-02-19: was swapped, now fixed)
            # 1 = enabled, 2 = disabled (corrected from initial analysis)
            auto_byte = _u8_to_number(data[23])
            parsed["auto_start_stop"] = (auto_byte == 1)  # 1 = enabled (fixed swap)

            # Bytes 24-25: Voltage (uint16 LE, /10)
            voltage_raw = (_u8_to_number(data[24]) | (_u8_to_number(data[25]) << 8))
            parsed["supply_voltage"] = voltage_raw / 10.0

            # Bytes 27-28: Shell/Case temperature (uint16 LE, /10)
            case_temp_raw = (_u8_to_number(data[27]) | (_u8_to_number(data[28]) << 8))
            parsed["case_temperature"] = case_temp_raw / 10.0

            # Bytes 30-31: Ambient/Cabin temperature (uint16 LE, /10)
            ambient_raw = (_u8_to_number(data[30]) | (_u8_to_number(data[31]) << 8))
            parsed["cab_temperature"] = ambient_raw / 10.0

            # Byte 18: Altitude mode
            if len(data) > 18:
                parsed["high_altitude"] = _u8_to_number(data[18])

            # Byte 37: Temperature unit (0=C, 1=F)
            if len(data) > 37:
                parsed["temp_unit"] = _u8_to_number(data[37])

            # Error handling: when status == ERROR (0xF), byte 22 contains error code
            if status == HCALORY_RUNNING_STATUS_ERROR:
                parsed["error_code"] = set_value_raw
            else:
                parsed["error_code"] = 0

        except (ValueError, IndexError) as e:
            # Parse error - return minimal data
            parsed["_hcalory_parse_error"] = True
            parsed["_parse_error_msg"] = str(e)

        return parsed


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
            # Map standard 1-10 to Hcalory 1-6
            hcalory_level = self._map_standard_to_hcalory_level(argument)
            return self._build_hcalory_cmd(
                HCALORY_CMD_SET_GEAR,
                bytes([hcalory_level])
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

        # Time sync (cmd 10) - MVP2 uses query command with timestamp to sync time
        # The query packet (dpID 0x0A0A) contains HH:MM:SS:DOW which the heater uses to sync
        if command == 10:
            if self._is_mvp2:
                # MVP2: Send query with current timestamp (heater syncs from it)
                return self._build_mvp2_query_cmd()
            else:
                # MVP1: Fallback to query (MVP1 may not support explicit time sync)
                return self._build_hcalory_cmd(
                    HCALORY_CMD_POWER,
                    bytes([0, 0, 0, 0, 0, 0, 0, 0, HCALORY_POWER_QUERY])
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

        MVP2 uses dpID 0A0A with timestamp payload (@Xev's analysis, issue #34):
        Template: 00 02 00 01 00 01 00 0A 0A 00 00 05 [HH MM SS DOW] 00 + checksum

        Timestamp is 4 bytes (NOT BCD): hour, minute, second, isoweekday (1-7)
        """
        now = datetime.now()
        # @Xev: timestamp is NOT BCD encoded, just raw bytes + isoweekday()
        timestamp = bytes([
            now.hour,
            now.minute,
            now.second,
            now.isoweekday()  # 1=Monday, 7=Sunday
        ])

        # Build packet: header + dpID 0A0A + payload length (5) + timestamp + 00
        packet = bytearray([
            0x00, 0x02,  # Protocol ID
            0x00, 0x01,  # Reserved
            0x00, 0x01,  # Flags (expects response)
            0x00, 0x0A, 0x0A, 0x00,  # dpID 0A0A
            0x00, 0x05,  # Payload length = 5
        ])

        # Add timestamp (4 bytes: HH MM SS DOW) + trailing 00
        packet.extend(timestamp)
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

    # -------------------------
    # Convenience command builders (@Xev's improvements from issue #34)
    # -------------------------

    def set_temperature_celsius(self, temp: int) -> bytearray:
        """Set temperature in Celsius mode.

        Args:
            temp: Temperature in Celsius (8-36)

        Returns:
            Command packet to set temperature
        """
        temp_clamped = max(8, min(36, temp))
        # Use CMD_SET_TEMP (0x0706) with [temp, unit=0]
        from .const import HCALORY_CMD_SET_TEMP
        return self._build_hcalory_cmd(
            HCALORY_CMD_SET_TEMP,
            bytes([temp_clamped, 0x00])  # temp, unit=Celsius
        )

    def set_temperature_fahrenheit(self, temp_f: int) -> bytearray:
        """Set temperature in Fahrenheit mode.

        Args:
            temp_f: Temperature in Fahrenheit

        Returns:
            Command packet to set temperature
        """
        from .const import HCALORY_CMD_SET_TEMP
        return self._build_hcalory_cmd(
            HCALORY_CMD_SET_TEMP,
            bytes([temp_f, 0x01])  # temp, unit=Fahrenheit
        )

    def set_level_mode(self) -> bytearray:
        """Switch to Level/Gear mode.

        @Xev identified (issue #34, 2026-02-19) that the command is likely:
        00 02 00 01 00 01 00 0e 04 00 00 09 00 00 00 00 00 00 00 00 07 14
        Which translates to: dpID 0x0E04 with payload [00 00 00 00 00 00 00 00 07]

        Testing needed to confirm if this works better than CMD_SET_MODE approach.

        Returns:
            Command packet to switch to level mode
        """
        from .const import HCALORY_CMD_POWER
        # Use the command identified by @Xev from packet capture
        return self._build_hcalory_cmd(
            HCALORY_CMD_POWER,
            bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x07])
        )

    def set_temperature_mode(self) -> bytearray:
        """Switch to Temperature mode.

        Returns:
            Command packet to switch to temperature mode
        """
        from .const import HCALORY_CMD_SET_MODE, HCALORY_MODE_TEMPERATURE
        return self._build_hcalory_cmd(
            HCALORY_CMD_SET_MODE,
            bytes([HCALORY_MODE_TEMPERATURE, 0x00])
        )

    def set_ventilation_mode(self) -> bytearray:
        """Switch to Ventilation/Fan-only mode.

        Note: Ventilation only works when heater is in standby/off state.

        Returns:
            Command packet to enable ventilation mode
        """
        from .const import HCALORY_CMD_POWER, HCALORY_POWER_VENTILATION
        return self._build_hcalory_cmd(
            HCALORY_CMD_POWER,
            bytes([0, 0, 0, 0, 0, 0, 0, 0, HCALORY_POWER_VENTILATION])
        )

    def enable_auto_start_stop(self) -> bytearray:
        """Enable automatic start/stop feature.

        Returns:
            Command packet to enable auto start/stop
        """
        from .const import HCALORY_CMD_POWER, HCALORY_POWER_AUTO_ENABLE
        return self._build_hcalory_cmd(
            HCALORY_CMD_POWER,
            bytes([0, 0, 0, 0, 0, 0, 0, 0, HCALORY_POWER_AUTO_ENABLE])
        )

    def disable_auto_start_stop(self) -> bytearray:
        """Disable automatic start/stop feature.

        Returns:
            Command packet to disable auto start/stop
        """
        from .const import HCALORY_CMD_POWER, HCALORY_POWER_AUTO_DISABLE
        return self._build_hcalory_cmd(
            HCALORY_CMD_POWER,
            bytes([0, 0, 0, 0, 0, 0, 0, 0, HCALORY_POWER_AUTO_DISABLE])
        )

    def set_temperature_unit_celsius(self) -> bytearray:
        """Set temperature display unit to Celsius.

        Returns:
            Command packet to switch to Celsius
        """
        from .const import HCALORY_CMD_POWER, HCALORY_POWER_CELSIUS
        return self._build_hcalory_cmd(
            HCALORY_CMD_POWER,
            bytes([0, 0, 0, 0, 0, 0, 0, 0, HCALORY_POWER_CELSIUS])
        )

    def set_temperature_unit_fahrenheit(self) -> bytearray:
        """Set temperature display unit to Fahrenheit.

        Returns:
            Command packet to switch to Fahrenheit
        """
        from .const import HCALORY_CMD_POWER, HCALORY_POWER_FAHRENHEIT
        return self._build_hcalory_cmd(
            HCALORY_CMD_POWER,
            bytes([0, 0, 0, 0, 0, 0, 0, 0, HCALORY_POWER_FAHRENHEIT])
        )
