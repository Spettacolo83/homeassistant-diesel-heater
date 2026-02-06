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
from typing import Any

from .const import (
    ABBA_STATUS_MAP,
    CBFF_RUN_STATE_OFF,
    ENCRYPTION_KEY,
    RUNNING_MODE_LEVEL,
    RUNNING_MODE_MANUAL,
    RUNNING_MODE_TEMPERATURE,
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
        else:
            # Unknown command — send status request as fallback
            return self._build_abba("baab04cc000000")

    @staticmethod
    def _build_abba(cmd_hex: str) -> bytearray:
        """Build ABBA packet with checksum."""
        cmd_bytes = bytes.fromhex(cmd_hex.replace(" ", ""))
        checksum = sum(cmd_bytes) & 0xFF
        return bytearray(cmd_bytes) + bytearray([checksum])


class ProtocolCBFF(VevorCommandMixin, HeaterProtocol):
    """CBFF/Sunster v2.1 protocol (mode=6, 47 bytes).

    Newer protocol used by Sunster TB10Pro WiFi and similar heaters.
    Heater sends 47-byte CBFF notifications; commands use AA55 format,
    heater ACKs with AA77.

    Some CBFF heaters send encrypted data using double-XOR:
      key1 = "passwordA2409PW" (15 bytes, hardcoded)
      key2 = BLE MAC address without colons, uppercased (12 bytes)
    Discovered by @Xev from the Sunster app source code.

    Byte mapping (reverse-engineered from Sunster app by @Xev).
    """

    protocol_mode = 6
    name = "CBFF"

    def __init__(self) -> None:
        self._device_sn: str | None = None

    def set_device_sn(self, sn: str) -> None:
        """Set the device serial number (BLE MAC without colons, uppercased).

        Used as key2 for CBFF double-XOR decryption.
        """
        self._device_sn = sn

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
    def _decrypt_cbff(data: bytearray, device_sn: str) -> bytearray:
        """Decrypt CBFF data using double-XOR (key1 + key2).

        key1 = "passwordA2409PW" (15 bytes, hardcoded in Sunster app)
        key2 = device_sn.upper() (BLE MAC without colons)
        """
        key1 = bytearray(b"passwordA2409PW")
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
