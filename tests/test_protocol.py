"""Tests for BLE protocol handlers.

These tests are pure Python — no Home Assistant dependency required.
Each protocol class is tested with hand-crafted bytearray data that
exercises the parser and command builder.
"""
from __future__ import annotations

import pytest

from diesel_heater_ble import (
    HeaterProtocol,
    ProtocolAA55,
    ProtocolAA55Encrypted,
    ProtocolAA66,
    ProtocolAA66Encrypted,
    ProtocolABBA,
    ProtocolCBFF,
    VevorCommandMixin,
    _decrypt_data,
    _encrypt_data,
    _u8_to_number,
    _unsign_to_sign,
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    """Tests for module-level helper functions."""

    def test_u8_to_number_positive(self):
        assert _u8_to_number(0) == 0
        assert _u8_to_number(127) == 127
        assert _u8_to_number(255) == 255

    def test_u8_to_number_negative(self):
        """Negative values (Java-style signed bytes) get +256."""
        assert _u8_to_number(-1) == 255
        assert _u8_to_number(-128) == 128

    def test_unsign_to_sign_positive(self):
        assert _unsign_to_sign(0) == 0
        assert _unsign_to_sign(100) == 100
        assert _unsign_to_sign(32767) == 32767

    def test_unsign_to_sign_negative(self):
        """Values above 32767.5 become negative (two's complement)."""
        assert _unsign_to_sign(65535) == -1
        assert _unsign_to_sign(65534) == -2
        assert _unsign_to_sign(32768) == -32768

    def test_decrypt_encrypt_roundtrip(self):
        """Encryption is symmetric XOR — decrypt(encrypt(x)) == x."""
        original = bytearray(range(48))
        encrypted = _encrypt_data(original)
        decrypted = _decrypt_data(encrypted)
        assert decrypted == original

    def test_decrypt_data_modifies_first_48_bytes(self):
        """XOR encryption covers 6 blocks of 8 bytes = 48 bytes."""
        data = bytearray(48)
        encrypted = _encrypt_data(data)
        # At least some bytes should differ (key is not all zeros)
        assert encrypted != data

    def test_encrypt_is_decrypt(self):
        """_encrypt_data is literally _decrypt_data (symmetric XOR)."""
        data = bytearray([0x42] * 48)
        assert _encrypt_data(data) == _decrypt_data(data)


# ---------------------------------------------------------------------------
# VevorCommandMixin (shared AA55 command builder)
# ---------------------------------------------------------------------------

class TestVevorCommandMixin:
    """Tests for the AA55 8-byte command builder."""

    def setup_method(self):
        self.proto = ProtocolAA55()  # Uses VevorCommandMixin

    def test_command_header(self):
        pkt = self.proto.build_command(1, 0, 1234)
        assert pkt[0] == 0xAA
        assert pkt[1] == 0x55

    def test_command_passkey(self):
        pkt = self.proto.build_command(1, 0, 1234)
        assert pkt[2] == 12  # 1234 // 100
        assert pkt[3] == 34  # 1234 % 100

    def test_command_code(self):
        pkt = self.proto.build_command(3, 1, 1234)
        assert pkt[4] == 3

    def test_command_argument_low_byte(self):
        pkt = self.proto.build_command(2, 5, 1234)
        assert pkt[5] == 5
        assert pkt[6] == 0

    def test_command_argument_high_byte(self):
        pkt = self.proto.build_command(2, 300, 1234)
        assert pkt[5] == 300 % 256  # 44
        assert pkt[6] == 300 // 256  # 1

    def test_command_checksum(self):
        pkt = self.proto.build_command(1, 0, 1234)
        expected_checksum = (pkt[2] + pkt[3] + pkt[4] + pkt[5] + pkt[6]) % 256
        assert pkt[7] == expected_checksum

    def test_command_length(self):
        pkt = self.proto.build_command(1, 0, 0)
        assert len(pkt) == 8

    def test_status_request(self):
        """Command 1 = status request."""
        pkt = self.proto.build_command(1, 0, 1234)
        assert pkt[4] == 1
        assert pkt[5] == 0


# ---------------------------------------------------------------------------
# ProtocolAA55 (mode=1, 18-20 bytes, unencrypted)
# ---------------------------------------------------------------------------

def _make_aa55_data(
    running_state=0,
    error_code=0,
    running_step=0,
    altitude_lo=0,
    altitude_hi=0,
    running_mode=1,
    byte9=5,
    byte10=0,
    voltage_lo=0xC8,
    voltage_hi=0x00,
    case_lo=0x96,
    case_hi=0x00,
    cab_lo=0xE8,
    cab_hi=0x00,
    extra_bytes=None,
) -> bytearray:
    """Build a valid AA55 packet (18 bytes minimum)."""
    data = bytearray(18)
    data[0] = 0xAA
    data[1] = 0x55
    data[2] = 0x00  # unused
    data[3] = running_state
    data[4] = error_code
    data[5] = running_step
    data[6] = altitude_lo
    data[7] = altitude_hi
    data[8] = running_mode
    data[9] = byte9
    data[10] = byte10
    data[11] = voltage_lo
    data[12] = voltage_hi
    data[13] = case_lo
    data[14] = case_hi
    data[15] = cab_lo
    data[16] = cab_hi
    data[17] = 0x00  # padding
    if extra_bytes:
        data.extend(extra_bytes)
    return data


class TestProtocolAA55:
    """Tests for AA55 unencrypted protocol (mode=1)."""

    def setup_method(self):
        self.proto = ProtocolAA55()

    def test_protocol_properties(self):
        assert self.proto.protocol_mode == 1
        assert self.proto.name == "AA55"
        assert self.proto.needs_calibration is True
        assert self.proto.needs_post_status is False

    def test_parse_level_mode(self):
        """Level mode: set_level from byte 9."""
        data = _make_aa55_data(running_state=1, running_mode=1, byte9=7)
        result = self.proto.parse(data)
        assert result["running_state"] == 1
        assert result["running_mode"] == 1
        assert result["set_level"] == 7

    def test_parse_temperature_mode(self):
        """Temperature mode: set_temp from byte 9, set_level from byte 10 + 1."""
        data = _make_aa55_data(running_mode=2, byte9=22, byte10=4)
        result = self.proto.parse(data)
        assert result["running_mode"] == 2
        assert result["set_temp"] == 22
        assert result["set_level"] == 5  # byte10 + 1

    def test_parse_manual_mode(self):
        """Manual mode: set_level from byte 10 + 1."""
        data = _make_aa55_data(running_mode=0, byte10=3)
        result = self.proto.parse(data)
        assert result["running_mode"] == 0
        assert result["set_level"] == 4  # byte10 + 1

    def test_parse_voltage(self):
        """Voltage = (256 * byte12 + byte11) / 10."""
        # 12.0V → voltage_lo=120, voltage_hi=0 → (0*256+120)/10=12.0
        data = _make_aa55_data(voltage_lo=120, voltage_hi=0)
        result = self.proto.parse(data)
        assert result["supply_voltage"] == 12.0

    def test_parse_voltage_high(self):
        """24.5V → voltage value = 245 → lo=245, hi=0."""
        data = _make_aa55_data(voltage_lo=245, voltage_hi=0)
        result = self.proto.parse(data)
        assert result["supply_voltage"] == 24.5

    def test_parse_case_temperature_positive(self):
        """Case temperature: signed 16-bit (256 * byte14 + byte13)."""
        # 150°C → case_lo=150, case_hi=0
        data = _make_aa55_data(case_lo=150, case_hi=0)
        result = self.proto.parse(data)
        assert result["case_temperature"] == 150

    def test_parse_case_temperature_negative(self):
        """Negative case temperature via _unsign_to_sign."""
        # -10 in uint16 = 65526 → hi=0xFF, lo=0xF6
        data = _make_aa55_data(case_lo=0xF6, case_hi=0xFF)
        result = self.proto.parse(data)
        assert result["case_temperature"] == -10

    def test_parse_cab_temperature(self):
        """Cabin temperature: signed 16-bit (256 * byte16 + byte15)."""
        # 23°C → cab_lo=23, cab_hi=0
        data = _make_aa55_data(cab_lo=23, cab_hi=0)
        result = self.proto.parse(data)
        assert result["cab_temperature"] == 23

    def test_parse_altitude(self):
        """Altitude = byte6 + 256 * byte7."""
        data = _make_aa55_data(altitude_lo=0xE8, altitude_hi=0x03)
        result = self.proto.parse(data)
        assert result["altitude"] == 1000  # 0xE8 + 256*0x03

    def test_parse_error_code(self):
        data = _make_aa55_data(error_code=5)
        result = self.proto.parse(data)
        assert result["error_code"] == 5

    def test_parse_running_step(self):
        data = _make_aa55_data(running_step=3)
        result = self.proto.parse(data)
        assert result["running_step"] == 3

    def test_parse_20_byte_packet(self):
        """20-byte packets should parse identically (extra bytes ignored)."""
        data = _make_aa55_data(running_state=1, running_mode=1, byte9=5)
        data.extend([0x00, 0x00])  # Extend to 20 bytes
        result = self.proto.parse(data)
        assert result["running_state"] == 1
        assert result["set_level"] == 5

    def test_is_heater_protocol(self):
        assert isinstance(self.proto, HeaterProtocol)

    def test_is_vevor_command_mixin(self):
        assert isinstance(self.proto, VevorCommandMixin)


# ---------------------------------------------------------------------------
# ProtocolAA66 (mode=3, 20 bytes, unencrypted)
# ---------------------------------------------------------------------------

def _make_aa66_data(
    running_state=0,
    error_code=0,
    running_step=0,
    altitude=0,
    running_mode=1,
    byte9=5,
    voltage_lo=120,
    voltage_hi=0,
    case_lo=150,
    case_hi=0,
    cab_temp=23,
) -> bytearray:
    """Build a valid AA66 packet (20 bytes)."""
    data = bytearray(20)
    data[0] = 0xAA
    data[1] = 0x66
    data[2] = 0x00
    data[3] = running_state
    data[4] = error_code
    data[5] = running_step
    data[6] = altitude
    data[7] = 0x00
    data[8] = running_mode
    data[9] = byte9
    data[10] = 0x00
    data[11] = voltage_lo
    data[12] = voltage_hi
    data[13] = case_lo
    data[14] = case_hi
    data[15] = cab_temp
    return data


class TestProtocolAA66:
    """Tests for AA66 unencrypted protocol (mode=3)."""

    def setup_method(self):
        self.proto = ProtocolAA66()

    def test_protocol_properties(self):
        assert self.proto.protocol_mode == 3
        assert self.proto.name == "AA66"
        assert self.proto.needs_calibration is True
        assert self.proto.needs_post_status is False

    def test_parse_level_mode(self):
        data = _make_aa66_data(running_state=1, running_mode=1, byte9=8)
        result = self.proto.parse(data)
        assert result["running_mode"] == 1
        assert result["set_level"] == 8

    def test_parse_level_mode_clamped(self):
        """set_level clamped to 1-10."""
        data = _make_aa66_data(running_mode=1, byte9=15)
        result = self.proto.parse(data)
        assert result["set_level"] == 10  # max(1, min(10, 15))

    def test_parse_temperature_mode(self):
        data = _make_aa66_data(running_mode=2, byte9=25)
        result = self.proto.parse(data)
        assert result["running_mode"] == 2
        assert result["set_temp"] == 25

    def test_parse_temperature_mode_clamped(self):
        """set_temp clamped to 8-36."""
        data = _make_aa66_data(running_mode=2, byte9=50)
        result = self.proto.parse(data)
        assert result["set_temp"] == 36  # max(8, min(36, 50))

    def test_parse_voltage(self):
        """Voltage = (byte11 | byte12<<8) / 10."""
        data = _make_aa66_data(voltage_lo=120, voltage_hi=0)
        result = self.proto.parse(data)
        assert result["supply_voltage"] == 12.0

    def test_parse_case_temperature_direct(self):
        """case_temp <= 350 → direct value."""
        data = _make_aa66_data(case_lo=150, case_hi=0)
        result = self.proto.parse(data)
        assert result["case_temperature"] == 150.0

    def test_parse_case_temperature_scaled(self):
        """case_temp > 350 → divided by 10 (0.1°C scale)."""
        # 1500 = 0x05DC → lo=0xDC, hi=0x05 → 1500/10 = 150.0
        data = _make_aa66_data(case_lo=0xDC, case_hi=0x05)
        result = self.proto.parse(data)
        assert result["case_temperature"] == 150.0

    def test_parse_case_temperature_boundary(self):
        """350 exactly → treated as direct value."""
        # 350 = lo=0x5E, hi=0x01
        data = _make_aa66_data(case_lo=0x5E, case_hi=0x01)
        result = self.proto.parse(data)
        assert result["case_temperature"] == 350.0

    def test_parse_case_temperature_above_boundary(self):
        """351 → treated as 0.1°C scale → 35.1."""
        # 351 = lo=0x5F, hi=0x01
        data = _make_aa66_data(case_lo=0x5F, case_hi=0x01)
        result = self.proto.parse(data)
        assert result["case_temperature"] == 35.1

    def test_parse_cab_temperature(self):
        data = _make_aa66_data(cab_temp=25)
        result = self.proto.parse(data)
        assert result["cab_temperature"] == 25

    def test_parse_altitude(self):
        data = _make_aa66_data(altitude=100)
        result = self.proto.parse(data)
        assert result["altitude"] == 100

    def test_is_heater_protocol(self):
        assert isinstance(self.proto, HeaterProtocol)


# ---------------------------------------------------------------------------
# ProtocolAA55Encrypted (mode=2, 48 bytes, pre-decrypted)
# ---------------------------------------------------------------------------

def _make_aa55enc_data(**overrides) -> bytearray:
    """Build a valid AA55 encrypted packet (48 bytes, pre-decrypted)."""
    data = bytearray(48)
    data[0] = 0xAA
    data[1] = 0x55
    data[3] = overrides.get("running_state", 0)
    data[4] = overrides.get("error_code", 0)
    data[5] = overrides.get("running_step", 0)
    # Altitude: (byte7 + 256*byte6) / 10
    alt = int(overrides.get("altitude_raw", 0))
    data[6] = (alt >> 8) & 0xFF
    data[7] = alt & 0xFF
    data[8] = overrides.get("running_mode", 1)
    data[9] = overrides.get("set_temp", 22)
    data[10] = overrides.get("set_level", 5)
    # Voltage: (256*byte11 + byte12) / 10
    voltage_raw = overrides.get("voltage_raw", 120)
    data[11] = (voltage_raw >> 8) & 0xFF
    data[12] = voltage_raw & 0xFF
    # Case temp: (256*byte13 + byte14) signed
    case = overrides.get("case_temp_raw", 150)
    if case < 0:
        case = case + 65536
    data[13] = (case >> 8) & 0xFF
    data[14] = case & 0xFF
    # Cab temp: (256*byte32 + byte33) / 10 signed
    cab = overrides.get("cab_temp_raw", 230)
    if cab < 0:
        cab = cab + 65536
    data[32] = (cab >> 8) & 0xFF
    data[33] = cab & 0xFF
    # Heater offset (signed byte)
    offset = overrides.get("heater_offset", 0)
    data[34] = offset if offset >= 0 else (offset + 256)
    # Backlight
    data[36] = overrides.get("backlight", 50)
    # CO sensor
    co_present = overrides.get("co_present", 0)
    data[37] = co_present
    co_ppm = overrides.get("co_ppm_raw", 0)
    data[38] = (co_ppm >> 8) & 0xFF
    data[39] = co_ppm & 0xFF
    # Part number (uint32 LE)
    part = overrides.get("part_number_raw", 0)
    data[40] = part & 0xFF
    data[41] = (part >> 8) & 0xFF
    data[42] = (part >> 16) & 0xFF
    data[43] = (part >> 24) & 0xFF
    # Motherboard version
    data[44] = overrides.get("motherboard_version", 0)
    return data


class TestProtocolAA55Encrypted:
    """Tests for AA55 encrypted protocol (mode=2, receives pre-decrypted data)."""

    def setup_method(self):
        self.proto = ProtocolAA55Encrypted()

    def test_protocol_properties(self):
        assert self.proto.protocol_mode == 2
        assert self.proto.name == "AA55 encrypted"
        assert self.proto.needs_calibration is True

    def test_parse_basic_fields(self):
        data = _make_aa55enc_data(running_state=1, error_code=3, running_step=2)
        result = self.proto.parse(data)
        assert result["running_state"] == 1
        assert result["error_code"] == 3
        assert result["running_step"] == 2

    def test_parse_altitude(self):
        """Altitude = (byte7 + 256*byte6) / 10."""
        data = _make_aa55enc_data(altitude_raw=1000)
        result = self.proto.parse(data)
        assert result["altitude"] == 100.0  # 1000/10

    def test_parse_set_level_clamped(self):
        data = _make_aa55enc_data(set_level=15)
        result = self.proto.parse(data)
        assert result["set_level"] == 10  # max(1, min(10, 15))

    def test_parse_set_temp_clamped(self):
        data = _make_aa55enc_data(set_temp=50)
        result = self.proto.parse(data)
        assert result["set_temp"] == 36  # max(8, min(36, 50))

    def test_parse_voltage(self):
        """Voltage = (256*byte11 + byte12) / 10."""
        data = _make_aa55enc_data(voltage_raw=120)
        result = self.proto.parse(data)
        assert result["supply_voltage"] == 12.0

    def test_parse_case_temperature(self):
        data = _make_aa55enc_data(case_temp_raw=200)
        result = self.proto.parse(data)
        assert result["case_temperature"] == 200

    def test_parse_cab_temperature(self):
        """Cab temp = (256*byte32 + byte33) / 10."""
        data = _make_aa55enc_data(cab_temp_raw=230)
        result = self.proto.parse(data)
        assert result["cab_temperature"] == 23.0  # 230/10

    def test_parse_heater_offset_positive(self):
        data = _make_aa55enc_data(heater_offset=5)
        result = self.proto.parse(data)
        assert result["heater_offset"] == 5

    def test_parse_heater_offset_negative(self):
        data = _make_aa55enc_data(heater_offset=-3)
        result = self.proto.parse(data)
        assert result["heater_offset"] == -3

    def test_parse_backlight(self):
        data = _make_aa55enc_data(backlight=75)
        result = self.proto.parse(data)
        assert result["backlight"] == 75

    def test_parse_co_sensor_present(self):
        data = _make_aa55enc_data(co_present=1, co_ppm_raw=150)
        result = self.proto.parse(data)
        assert result["co_ppm"] == 150.0

    def test_parse_co_sensor_absent(self):
        data = _make_aa55enc_data(co_present=0)
        result = self.proto.parse(data)
        assert result["co_ppm"] is None

    def test_parse_part_number(self):
        data = _make_aa55enc_data(part_number_raw=0xDEADBEEF)
        result = self.proto.parse(data)
        assert result["part_number"] == "deadbeef"

    def test_parse_part_number_zero_omitted(self):
        data = _make_aa55enc_data(part_number_raw=0)
        result = self.proto.parse(data)
        assert "part_number" not in result

    def test_parse_motherboard_version(self):
        data = _make_aa55enc_data(motherboard_version=12)
        result = self.proto.parse(data)
        assert result["motherboard_version"] == 12

    def test_parse_motherboard_version_zero_omitted(self):
        data = _make_aa55enc_data(motherboard_version=0)
        result = self.proto.parse(data)
        assert "motherboard_version" not in result


# ---------------------------------------------------------------------------
# ProtocolAA66Encrypted (mode=4, 48 bytes, pre-decrypted)
# ---------------------------------------------------------------------------

def _make_aa66enc_data(**overrides) -> bytearray:
    """Build a valid AA66 encrypted packet (48 bytes, pre-decrypted)."""
    data = bytearray(48)
    data[0] = 0xAA
    data[1] = 0x66
    data[3] = overrides.get("running_state", 0)
    data[5] = overrides.get("running_step", 0)
    alt = int(overrides.get("altitude_raw", 0))
    data[6] = (alt >> 8) & 0xFF
    data[7] = alt & 0xFF
    data[8] = overrides.get("running_mode", 1)
    data[9] = overrides.get("set_temp_raw", 22)
    data[10] = overrides.get("set_level", 5)
    voltage_raw = overrides.get("voltage_raw", 120)
    data[11] = (voltage_raw >> 8) & 0xFF
    data[12] = voltage_raw & 0xFF
    case = overrides.get("case_temp_raw", 150)
    if case < 0:
        case = case + 65536
    data[13] = (case >> 8) & 0xFF
    data[14] = case & 0xFF
    data[26] = overrides.get("language", 0)
    data[27] = overrides.get("temp_unit", 0)
    data[28] = overrides.get("tank_volume", 0)
    data[29] = overrides.get("pump_byte", 0)
    data[30] = overrides.get("altitude_unit", 0)
    data[31] = overrides.get("auto_start_stop", 0)
    cab = overrides.get("cab_temp_raw", 230)
    if cab < 0:
        cab = cab + 65536
    data[32] = (cab >> 8) & 0xFF
    data[33] = cab & 0xFF
    offset = overrides.get("heater_offset", 0)
    data[34] = offset if offset >= 0 else (offset + 256)
    data[35] = overrides.get("error_code", 0)
    data[36] = overrides.get("backlight", 50)
    data[37] = overrides.get("co_present", 0)
    co_ppm = overrides.get("co_ppm_raw", 0)
    data[38] = (co_ppm >> 8) & 0xFF
    data[39] = co_ppm & 0xFF
    part = overrides.get("part_number_raw", 0)
    data[40] = part & 0xFF
    data[41] = (part >> 8) & 0xFF
    data[42] = (part >> 16) & 0xFF
    data[43] = (part >> 24) & 0xFF
    data[44] = overrides.get("motherboard_version", 0)
    return data


class TestProtocolAA66Encrypted:
    """Tests for AA66 encrypted protocol (mode=4, receives pre-decrypted data)."""

    def setup_method(self):
        self.proto = ProtocolAA66Encrypted()

    def test_protocol_properties(self):
        assert self.proto.protocol_mode == 4
        assert self.proto.name == "AA66 encrypted"
        assert self.proto.needs_calibration is True

    def test_parse_error_code_at_byte_35(self):
        """AA66enc has error_code at byte 35 (different from AA55enc byte 4)."""
        data = _make_aa66enc_data(error_code=7)
        result = self.proto.parse(data)
        assert result["error_code"] == 7

    def test_parse_celsius_mode(self):
        """temp_unit=0 → Celsius, set_temp used directly."""
        data = _make_aa66enc_data(temp_unit=0, set_temp_raw=22)
        result = self.proto.parse(data)
        assert result["temp_unit"] == 0
        assert result["set_temp"] == 22

    def test_parse_fahrenheit_mode(self):
        """temp_unit=1 → Fahrenheit, set_temp converted to Celsius."""
        # 72°F → (72-32)*5/9 = 22.2 → round = 22
        data = _make_aa66enc_data(temp_unit=1, set_temp_raw=72)
        result = self.proto.parse(data)
        assert result["temp_unit"] == 1
        assert result["set_temp"] == 22

    def test_parse_fahrenheit_clamped(self):
        """Converted temp clamped to 8-36°C."""
        # 100°F → (100-32)*5/9 = 37.8 → clamped to 36
        data = _make_aa66enc_data(temp_unit=1, set_temp_raw=100)
        result = self.proto.parse(data)
        assert result["set_temp"] == 36

    def test_parse_auto_start_stop(self):
        data = _make_aa66enc_data(auto_start_stop=1)
        result = self.proto.parse(data)
        assert result["auto_start_stop"] is True

    def test_parse_auto_start_stop_off(self):
        data = _make_aa66enc_data(auto_start_stop=0)
        result = self.proto.parse(data)
        assert result["auto_start_stop"] is False

    def test_parse_language(self):
        data = _make_aa66enc_data(language=2)
        result = self.proto.parse(data)
        assert result["language"] == 2

    def test_parse_tank_volume(self):
        data = _make_aa66enc_data(tank_volume=5)
        result = self.proto.parse(data)
        assert result["tank_volume"] == 5

    def test_parse_pump_type_normal(self):
        data = _make_aa66enc_data(pump_byte=2)
        result = self.proto.parse(data)
        assert result["pump_type"] == 2
        assert result["rf433_enabled"] is None

    def test_parse_rf433_off(self):
        data = _make_aa66enc_data(pump_byte=20)
        result = self.proto.parse(data)
        assert result["rf433_enabled"] is False
        assert result["pump_type"] is None

    def test_parse_rf433_on(self):
        data = _make_aa66enc_data(pump_byte=21)
        result = self.proto.parse(data)
        assert result["rf433_enabled"] is True
        assert result["pump_type"] is None

    def test_parse_altitude_unit(self):
        data = _make_aa66enc_data(altitude_unit=1)
        result = self.proto.parse(data)
        assert result["altitude_unit"] == 1

    def test_parse_backlight(self):
        data = _make_aa66enc_data(backlight=80)
        result = self.proto.parse(data)
        assert result["backlight"] == 80

    def test_parse_co_ppm(self):
        data = _make_aa66enc_data(co_present=1, co_ppm_raw=100)
        result = self.proto.parse(data)
        assert result["co_ppm"] == 100.0

    def test_parse_part_number(self):
        """AA66enc also has part_number at bytes 40-43."""
        data = _make_aa66enc_data(part_number_raw=0xABCD1234)
        result = self.proto.parse(data)
        assert result["part_number"] == "abcd1234"

    def test_parse_motherboard_version(self):
        """AA66enc also has motherboard_version at byte 44."""
        data = _make_aa66enc_data(motherboard_version=15)
        result = self.proto.parse(data)
        assert result["motherboard_version"] == 15


# ---------------------------------------------------------------------------
# ProtocolABBA (mode=5, 21+ bytes)
# ---------------------------------------------------------------------------

def _make_abba_data(**overrides) -> bytearray:
    """Build a valid ABBA packet (21 bytes minimum)."""
    data = bytearray(21)
    data[0] = 0xAB
    data[1] = 0xBA
    data[2] = 0x00
    data[3] = 0x00
    data[4] = overrides.get("status_byte", 0x00)
    data[5] = overrides.get("mode_byte", 0x00)
    data[6] = overrides.get("gear_byte", 5)
    data[7] = 0x00
    data[8] = overrides.get("auto_start_stop", 0)
    data[9] = overrides.get("voltage", 12)
    data[10] = overrides.get("temp_unit", 0)
    data[11] = overrides.get("env_temp_raw", 53)  # 53-30=23°C
    data[12] = overrides.get("case_hi", 0x00)
    data[13] = overrides.get("case_lo", 0xDC)  # 220°C
    data[14] = overrides.get("altitude_unit", 0)
    data[15] = overrides.get("high_altitude", 0)
    data[16] = overrides.get("altitude_lo", 0)
    data[17] = overrides.get("altitude_hi", 0)
    data[18] = 0x00
    data[19] = 0x00
    data[20] = 0x00
    return data


class TestProtocolABBA:
    """Tests for ABBA/HeaterCC protocol (mode=5)."""

    def setup_method(self):
        self.proto = ProtocolABBA()

    def test_protocol_properties(self):
        assert self.proto.protocol_mode == 5
        assert self.proto.name == "ABBA"
        assert self.proto.needs_calibration is False
        assert self.proto.needs_post_status is True

    def test_parse_short_data_returns_none(self):
        data = bytearray(20)
        assert self.proto.parse(data) is None

    def test_parse_off_state(self):
        data = _make_abba_data(status_byte=0x00)
        result = self.proto.parse(data)
        assert result["running_state"] == 0
        assert result["running_step"] == 0  # RUNNING_STEP_STANDBY

    def test_parse_heating_state(self):
        data = _make_abba_data(status_byte=0x01)
        result = self.proto.parse(data)
        assert result["running_state"] == 1
        assert result["running_step"] == 3  # RUNNING_STEP_RUNNING

    def test_parse_cooldown_state(self):
        data = _make_abba_data(status_byte=0x02)
        result = self.proto.parse(data)
        assert result["running_state"] == 0
        assert result["running_step"] == 4  # RUNNING_STEP_COOLDOWN

    def test_parse_ventilation_state(self):
        data = _make_abba_data(status_byte=0x04)
        result = self.proto.parse(data)
        assert result["running_state"] == 0
        assert result["running_step"] == 6  # RUNNING_STEP_VENTILATION

    def test_parse_level_mode(self):
        data = _make_abba_data(mode_byte=0x00, gear_byte=7)
        result = self.proto.parse(data)
        assert result["running_mode"] == 1  # RUNNING_MODE_LEVEL
        assert result["set_level"] == 7
        assert result["error_code"] == 0

    def test_parse_temperature_mode(self):
        data = _make_abba_data(mode_byte=0x01, gear_byte=25)
        result = self.proto.parse(data)
        assert result["running_mode"] == 2  # RUNNING_MODE_TEMPERATURE
        assert result["set_temp"] == 25
        assert result["error_code"] == 0

    def test_parse_error_state(self):
        """mode_byte=0xFF → error, byte6 is error code."""
        data = _make_abba_data(mode_byte=0xFF, gear_byte=5)
        result = self.proto.parse(data)
        assert result["error_code"] == 5
        # running_mode should NOT be in result when error
        assert "running_mode" not in result
        # set_level/set_temp should NOT be parsed in error state
        assert "set_level" not in result
        assert "set_temp" not in result

    def test_parse_unknown_mode(self):
        """mode_byte not 0x00/0x01/0xFF → raw value stored."""
        data = _make_abba_data(mode_byte=0x05, gear_byte=3)
        result = self.proto.parse(data)
        assert result["running_mode"] == 5  # raw mode byte
        assert result["error_code"] == 0

    def test_parse_voltage(self):
        data = _make_abba_data(voltage=24)
        result = self.proto.parse(data)
        assert result["supply_voltage"] == 24.0

    def test_parse_celsius_temperature(self):
        """Celsius: env_temp = raw - 30."""
        data = _make_abba_data(temp_unit=0, env_temp_raw=53)
        result = self.proto.parse(data)
        assert result["temp_unit"] == 0
        assert result["cab_temperature"] == 23.0  # 53-30

    def test_parse_fahrenheit_temperature(self):
        """Fahrenheit: env_temp = raw - 22."""
        data = _make_abba_data(temp_unit=1, env_temp_raw=95)
        result = self.proto.parse(data)
        assert result["temp_unit"] == 1
        assert result["cab_temperature"] == 73.0  # 95-22

    def test_parse_case_temperature(self):
        """Case temp: uint16 BE → (byte12 << 8) | byte13."""
        # 220°C → case_hi=0x00, case_lo=0xDC
        data = _make_abba_data(case_hi=0x00, case_lo=0xDC)
        result = self.proto.parse(data)
        assert result["case_temperature"] == 220.0

    def test_parse_auto_start_stop(self):
        data = _make_abba_data(auto_start_stop=1)
        result = self.proto.parse(data)
        assert result["auto_start_stop"] is True

    def test_parse_altitude(self):
        """Altitude: uint16 LE → byte16 | (byte17 << 8)."""
        data = _make_abba_data(altitude_lo=0xE8, altitude_hi=0x03)
        result = self.proto.parse(data)
        assert result["altitude"] == 1000

    def test_parse_high_altitude(self):
        data = _make_abba_data(high_altitude=1)
        result = self.proto.parse(data)
        assert result["high_altitude"] == 1

    def test_parse_connected_always_true(self):
        data = _make_abba_data()
        result = self.proto.parse(data)
        assert result["connected"] is True

    # --- Command building ---

    def test_build_command_status(self):
        """Command 1 → status request."""
        pkt = self.proto.build_command(1, 0, 1234)
        # Should start with baab04cc000000 + checksum
        assert pkt[0] == 0xBA
        assert pkt[1] == 0xAB
        assert pkt[3] == 0xCC  # Status command

    def test_build_command_toggle_on_off(self):
        """Command 3 → heat toggle (0xA1)."""
        pkt = self.proto.build_command(3, 1, 1234)
        assert pkt[0] == 0xBA
        assert pkt[1] == 0xAB
        assert pkt[3] == 0xBB
        assert pkt[4] == 0xA1  # openOnHeat toggle

    def test_build_command_set_temperature(self):
        """Command 4 with argument → set temperature."""
        pkt = self.proto.build_command(4, 25, 1234)
        assert pkt[0] == 0xBA
        assert pkt[1] == 0xAB
        assert pkt[3] == 0xDB
        assert pkt[4] == 25  # Temperature value

    def test_build_command_const_temp_mode(self):
        """Command 2, argument 2 → const temp mode."""
        pkt = self.proto.build_command(2, 2, 1234)
        assert pkt[4] == 0xAC  # openOnPlateau/const temp

    def test_build_command_other_mode(self):
        """Command 2, argument != 2 → other mode."""
        pkt = self.proto.build_command(2, 1, 1234)
        assert pkt[4] == 0xAD  # Other mode

    def test_build_command_fahrenheit(self):
        """Command 15, argument 1 → Fahrenheit."""
        pkt = self.proto.build_command(15, 1, 1234)
        assert pkt[4] == 0xA8

    def test_build_command_celsius(self):
        """Command 15, argument 0 → Celsius."""
        pkt = self.proto.build_command(15, 0, 1234)
        assert pkt[4] == 0xA7

    def test_build_command_feet(self):
        """Command 19, argument 1 → Feet."""
        pkt = self.proto.build_command(19, 1, 1234)
        assert pkt[4] == 0xAA

    def test_build_command_meters(self):
        """Command 19, argument 0 → Meters."""
        pkt = self.proto.build_command(19, 0, 1234)
        assert pkt[4] == 0xA9

    def test_build_command_high_altitude(self):
        """Command 99 → high altitude toggle."""
        pkt = self.proto.build_command(99, 0, 1234)
        assert pkt[4] == 0xA5

    def test_build_command_checksum(self):
        """Last byte is checksum (sum of all previous bytes & 0xFF)."""
        pkt = self.proto.build_command(1, 0, 1234)
        expected = sum(pkt[:-1]) & 0xFF
        assert pkt[-1] == expected

    def test_build_command_unknown_falls_back_to_status(self):
        """Unknown command falls back to status request."""
        pkt = self.proto.build_command(255, 0, 1234)
        assert pkt[3] == 0xCC  # Same as status

    def test_is_heater_protocol(self):
        assert isinstance(self.proto, HeaterProtocol)

    def test_is_not_vevor_command_mixin(self):
        """ABBA has its own command builder, not VevorCommandMixin."""
        assert not isinstance(self.proto, VevorCommandMixin)


# ---------------------------------------------------------------------------
# ProtocolCBFF (mode=6, 47 bytes)
# ---------------------------------------------------------------------------

def _make_cbff_data(**overrides) -> bytearray:
    """Build a valid CBFF packet (47 bytes)."""
    data = bytearray(47)
    data[0] = 0xCB
    data[1] = 0xFF
    data[2] = overrides.get("protocol_version", 0x01)
    # Byte 10: run_state
    data[10] = overrides.get("run_state", 2)  # 2=OFF by default
    # Byte 11: run_mode
    data[11] = overrides.get("run_mode", 1)
    # Byte 12: run_param
    data[12] = overrides.get("run_param", 5)
    # Byte 13: now_gear
    data[13] = overrides.get("now_gear", 3)
    # Byte 14: run_step
    data[14] = overrides.get("run_step", 0)
    # Byte 15: fault_display
    data[15] = overrides.get("fault_display", 0)
    # Byte 17: temp_unit (lower nibble)
    data[17] = overrides.get("temp_unit", 0)
    # Bytes 18-19: cab temp (int16 LE)
    cab = overrides.get("cab_temp", 23)
    if cab < 0:
        cab = cab + 65536
    data[18] = cab & 0xFF
    data[19] = (cab >> 8) & 0xFF
    # Byte 20: altitude_unit
    data[20] = overrides.get("altitude_unit", 0)
    # Bytes 21-22: altitude (uint16 LE)
    alt = overrides.get("altitude", 0)
    data[21] = alt & 0xFF
    data[22] = (alt >> 8) & 0xFF
    # Bytes 23-24: voltage (uint16 LE, /10)
    voltage = overrides.get("voltage_raw", 120)
    data[23] = voltage & 0xFF
    data[24] = (voltage >> 8) & 0xFF
    # Bytes 25-26: case temp (int16 LE, /10)
    case = overrides.get("case_temp_raw", 1500)
    if case < 0:
        case = case + 65536
    data[25] = case & 0xFF
    data[26] = (case >> 8) & 0xFF
    # Bytes 27-28: CO ppm (uint16 LE, /10)
    co = overrides.get("co_raw", 0)
    data[27] = co & 0xFF
    data[28] = (co >> 8) & 0xFF
    # Byte 29: pwr_onoff
    data[29] = overrides.get("pwr_onoff", 0)
    # Bytes 30-31: hardware_version
    hw = overrides.get("hw_version", 0)
    data[30] = hw & 0xFF
    data[31] = (hw >> 8) & 0xFF
    # Bytes 32-33: software_version
    sw = overrides.get("sw_version", 0)
    data[32] = sw & 0xFF
    data[33] = (sw >> 8) & 0xFF
    # Byte 34: temp_comp (heater offset)
    offset = overrides.get("heater_offset", 0)
    data[34] = offset if offset >= 0 else (offset + 256)
    # Byte 35: language
    data[35] = overrides.get("language", 255)
    # Byte 36: tank_volume
    data[36] = overrides.get("tank_volume", 255)
    # Byte 37: pump_model
    data[37] = overrides.get("pump_byte", 255)
    # Byte 38: backlight
    data[38] = overrides.get("backlight", 255)
    # Byte 39: startup_temp_diff
    data[39] = overrides.get("startup_temp_diff", 255)
    # Byte 40: shutdown_temp_diff
    data[40] = overrides.get("shutdown_temp_diff", 255)
    # Byte 41: wifi
    data[41] = overrides.get("wifi", 255)
    # Byte 42: auto_start_stop
    data[42] = overrides.get("auto_start_stop", 0)
    # Byte 43: heater_mode
    data[43] = overrides.get("heater_mode", 0)
    # Bytes 44-45: remain_run_time
    remain = overrides.get("remain_run_time", 65535)
    data[44] = remain & 0xFF
    data[45] = (remain >> 8) & 0xFF
    # Byte 46: padding
    data[46] = 0x00
    return data


class TestProtocolCBFF:
    """Tests for CBFF/Sunster protocol (mode=6)."""

    def setup_method(self):
        self.proto = ProtocolCBFF()

    def test_protocol_properties(self):
        assert self.proto.protocol_mode == 6
        assert self.proto.name == "CBFF"
        assert self.proto.needs_calibration is True
        assert self.proto.needs_post_status is False

    def test_parse_short_data_returns_none(self):
        data = bytearray(45)
        assert self.proto.parse(data) is None

    def test_parse_running_state_off(self):
        """run_state in {2, 5, 6} → OFF."""
        for state in (2, 5, 6):
            data = _make_cbff_data(run_state=state)
            result = self.proto.parse(data)
            assert result["running_state"] == 0, f"run_state={state} should be OFF"

    def test_parse_running_state_on(self):
        """run_state not in {2, 5, 6} → ON."""
        for state in (0, 1, 3, 4):
            data = _make_cbff_data(run_state=state)
            result = self.proto.parse(data)
            assert result["running_state"] == 1, f"run_state={state} should be ON"

    def test_parse_level_mode(self):
        """run_mode 1, 3, 4 → RUNNING_MODE_LEVEL."""
        for mode in (1, 3, 4):
            data = _make_cbff_data(run_mode=mode, run_param=7)
            result = self.proto.parse(data)
            assert result["running_mode"] == 1  # RUNNING_MODE_LEVEL
            assert result["set_level"] == 7

    def test_parse_temperature_mode(self):
        """run_mode 2 → RUNNING_MODE_TEMPERATURE."""
        data = _make_cbff_data(run_mode=2, run_param=25, now_gear=6)
        result = self.proto.parse(data)
        assert result["running_mode"] == 2  # RUNNING_MODE_TEMPERATURE
        assert result["set_temp"] == 25
        assert result["set_level"] == 6  # now_gear in temp mode

    def test_parse_other_mode(self):
        """run_mode not 1-4 → RUNNING_MODE_MANUAL."""
        data = _make_cbff_data(run_mode=0)
        result = self.proto.parse(data)
        assert result["running_mode"] == 0  # RUNNING_MODE_MANUAL

    def test_parse_voltage(self):
        data = _make_cbff_data(voltage_raw=120)
        result = self.proto.parse(data)
        assert result["supply_voltage"] == 12.0

    def test_parse_cab_temperature(self):
        data = _make_cbff_data(cab_temp=23)
        result = self.proto.parse(data)
        assert result["cab_temperature"] == 23.0

    def test_parse_cab_temperature_negative(self):
        data = _make_cbff_data(cab_temp=-5)
        result = self.proto.parse(data)
        assert result["cab_temperature"] == -5.0

    def test_parse_case_temperature(self):
        """Case temp = int16 LE / 10."""
        data = _make_cbff_data(case_temp_raw=1500)
        result = self.proto.parse(data)
        assert result["case_temperature"] == 150.0

    def test_parse_case_temperature_negative(self):
        """Negative case temp (int16 LE / 10)."""
        # -100 raw → -10.0°C
        data = _make_cbff_data(case_temp_raw=-100)
        result = self.proto.parse(data)
        assert result["case_temperature"] == -10.0

    def test_parse_co_ppm(self):
        """CO = uint16 LE / 10."""
        data = _make_cbff_data(co_raw=100)
        result = self.proto.parse(data)
        assert result["co_ppm"] == 10.0

    def test_parse_co_ppm_high_is_none(self):
        """CO >= 6553 → None (sensor not present)."""
        data = _make_cbff_data(co_raw=65530)
        result = self.proto.parse(data)
        assert result["co_ppm"] is None

    def test_parse_error_code(self):
        """Error code: lower 6 bits of byte 15."""
        data = _make_cbff_data(fault_display=0xC3)
        result = self.proto.parse(data)
        assert result["error_code"] == 3  # 0xC3 & 0x3F = 3

    def test_parse_heater_offset_positive(self):
        data = _make_cbff_data(heater_offset=5)
        result = self.proto.parse(data)
        assert result["heater_offset"] == 5

    def test_parse_heater_offset_negative(self):
        data = _make_cbff_data(heater_offset=-3)
        result = self.proto.parse(data)
        assert result["heater_offset"] == -3

    def test_parse_language(self):
        data = _make_cbff_data(language=2)
        result = self.proto.parse(data)
        assert result["language"] == 2

    def test_parse_language_255_omitted(self):
        data = _make_cbff_data(language=255)
        result = self.proto.parse(data)
        assert "language" not in result

    def test_parse_tank_volume(self):
        data = _make_cbff_data(tank_volume=5)
        result = self.proto.parse(data)
        assert result["tank_volume"] == 5

    def test_parse_tank_volume_255_omitted(self):
        data = _make_cbff_data(tank_volume=255)
        result = self.proto.parse(data)
        assert "tank_volume" not in result

    def test_parse_pump_type(self):
        data = _make_cbff_data(pump_byte=2)
        result = self.proto.parse(data)
        assert result["pump_type"] == 2
        assert result["rf433_enabled"] is None

    def test_parse_rf433_off(self):
        data = _make_cbff_data(pump_byte=20)
        result = self.proto.parse(data)
        assert result["rf433_enabled"] is False
        assert result["pump_type"] is None

    def test_parse_rf433_on(self):
        data = _make_cbff_data(pump_byte=21)
        result = self.proto.parse(data)
        assert result["rf433_enabled"] is True
        assert result["pump_type"] is None

    def test_parse_pump_255_omitted(self):
        data = _make_cbff_data(pump_byte=255)
        result = self.proto.parse(data)
        assert "pump_type" not in result
        assert "rf433_enabled" not in result

    def test_parse_backlight(self):
        data = _make_cbff_data(backlight=50)
        result = self.proto.parse(data)
        assert result["backlight"] == 50

    def test_parse_backlight_255_omitted(self):
        data = _make_cbff_data(backlight=255)
        result = self.proto.parse(data)
        assert "backlight" not in result

    def test_parse_wifi_enabled(self):
        data = _make_cbff_data(wifi=1)
        result = self.proto.parse(data)
        assert result["wifi_enabled"] is True

    def test_parse_wifi_disabled(self):
        data = _make_cbff_data(wifi=0)
        result = self.proto.parse(data)
        assert result["wifi_enabled"] is False

    def test_parse_wifi_255_omitted(self):
        data = _make_cbff_data(wifi=255)
        result = self.proto.parse(data)
        assert "wifi_enabled" not in result

    def test_parse_auto_start_stop(self):
        data = _make_cbff_data(auto_start_stop=1)
        result = self.proto.parse(data)
        assert result["auto_start_stop"] is True

    def test_parse_remain_run_time(self):
        data = _make_cbff_data(remain_run_time=120)
        result = self.proto.parse(data)
        assert result["remain_run_time"] == 120

    def test_parse_remain_run_time_65535_omitted(self):
        data = _make_cbff_data(remain_run_time=65535)
        result = self.proto.parse(data)
        assert "remain_run_time" not in result

    def test_parse_hw_sw_versions(self):
        data = _make_cbff_data(hw_version=100, sw_version=200)
        result = self.proto.parse(data)
        assert result["hardware_version"] == 100
        assert result["software_version"] == 200

    def test_parse_hw_sw_zero_omitted(self):
        data = _make_cbff_data(hw_version=0, sw_version=0)
        result = self.proto.parse(data)
        assert "hardware_version" not in result
        assert "software_version" not in result

    def test_parse_protocol_version(self):
        data = _make_cbff_data(protocol_version=0x45)
        result = self.proto.parse(data)
        assert result["cbff_protocol_version"] == 0x45

    def test_parse_connected_always_true(self):
        data = _make_cbff_data()
        result = self.proto.parse(data)
        assert result["connected"] is True

    # --- CBFF encryption ---

    def test_set_device_sn(self):
        self.proto.set_device_sn("E466E5BC086D")
        assert self.proto._device_sn == "E466E5BC086D"

    def test_decrypt_cbff_roundtrip(self):
        """Double-XOR decrypt → re-encrypt should give original."""
        original = _make_cbff_data(voltage_raw=120, cab_temp=23)
        sn = "E466E5BC086D"
        encrypted = ProtocolCBFF._decrypt_cbff(original, sn)
        decrypted = ProtocolCBFF._decrypt_cbff(encrypted, sn)
        assert decrypted == original

    def test_parse_encrypted_data(self):
        """Encrypt valid data, set device_sn, parse should succeed."""
        original = _make_cbff_data(
            voltage_raw=120, cab_temp=23, run_state=2,
        )
        sn = "E466E5BC086D"
        encrypted = ProtocolCBFF._decrypt_cbff(original, sn)
        self.proto.set_device_sn(sn)
        result = self.proto.parse(encrypted)
        assert result is not None
        assert result["supply_voltage"] == 12.0
        assert result["cab_temperature"] == 23.0
        assert result.get("_cbff_decrypted") is True

    def test_suspect_data_detection_high_voltage(self):
        """Voltage > 100 → suspect."""
        parsed = {"supply_voltage": 150, "cab_temperature": 23}
        assert ProtocolCBFF._is_data_suspect(parsed) is True

    def test_suspect_data_detection_high_cab_temp(self):
        """|cab_temp| > 500 → suspect."""
        parsed = {"supply_voltage": 12, "cab_temperature": 600}
        assert ProtocolCBFF._is_data_suspect(parsed) is True

    def test_suspect_data_detection_negative_cab_temp(self):
        """|cab_temp| > 500 negative → suspect."""
        parsed = {"supply_voltage": 12, "cab_temperature": -600}
        assert ProtocolCBFF._is_data_suspect(parsed) is True

    def test_suspect_data_detection_negative_voltage(self):
        """Voltage < 0 → suspect."""
        parsed = {"supply_voltage": -5, "cab_temperature": 23}
        assert ProtocolCBFF._is_data_suspect(parsed) is True

    def test_normal_data_not_suspect(self):
        parsed = {"supply_voltage": 12.0, "cab_temperature": 23}
        assert ProtocolCBFF._is_data_suspect(parsed) is False

    def test_suspect_data_strips_sensor_values(self):
        """When data is suspect and no SN, sensor values should be stripped."""
        # Create data with impossible values (no encryption, just bad data)
        data = _make_cbff_data(voltage_raw=2000, cab_temp=1000)
        result = self.proto.parse(data)
        assert result.get("_cbff_data_suspect") is True
        assert "cab_temperature" not in result
        assert "supply_voltage" not in result

    def test_build_command_uses_aa55(self):
        """CBFF uses standard AA55 command format."""
        pkt = self.proto.build_command(1, 0, 1234)
        assert pkt[0] == 0xAA
        assert pkt[1] == 0x55
        assert len(pkt) == 8

    def test_is_heater_protocol(self):
        assert isinstance(self.proto, HeaterProtocol)

    def test_is_vevor_command_mixin(self):
        assert isinstance(self.proto, VevorCommandMixin)
