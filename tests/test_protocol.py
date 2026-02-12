"""Tests for BLE protocol handlers.

These tests are pure Python — no Home Assistant dependency required.
Each protocol class is tested with hand-crafted bytearray data that
exercises the parser and command builder.
"""
from __future__ import annotations

from diesel_heater_ble import (
    HeaterProtocol,
    ProtocolAA55,
    ProtocolAA55Encrypted,
    ProtocolAA66,
    ProtocolAA66Encrypted,
    ProtocolABBA,
    ProtocolCBFF,
    ProtocolHcalory,
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

    # --- FEAA command building ---

    def test_build_command_status_request(self):
        """Status request uses FEAA format with cmd_1=0x80, cmd_2=0x00."""
        pkt = self.proto.build_command(1, 0, 1234)
        assert pkt[0] == 0xFE
        assert pkt[1] == 0xAA
        assert pkt[6] == 0x80  # cmd_1 (status query)
        assert pkt[7] == 0x00  # cmd_2 (read)
        # Checksum is sum of all previous bytes & 0xFF
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_build_command_power_on(self):
        """Power on uses FEAA with cmd_1=0x81, cmd_2=0x03, payload=1."""
        pkt = self.proto.build_command(3, 1, 1234)  # cmd=3 (power), arg=1 (on)
        assert pkt[0] == 0xFE
        assert pkt[1] == 0xAA
        assert pkt[6] == 0x81  # cmd_1 (power command)
        assert pkt[7] == 0x03  # cmd_2 (with payload)
        assert pkt[8] == 0x01  # payload: on
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_build_command_power_off(self):
        """Power off uses FEAA with cmd_1=0x81, cmd_2=0x03, payload=0."""
        pkt = self.proto.build_command(3, 0, 1234)  # cmd=3 (power), arg=0 (off)
        assert pkt[0] == 0xFE
        assert pkt[1] == 0xAA
        assert pkt[6] == 0x81  # cmd_1 (power command)
        assert pkt[7] == 0x03  # cmd_2 (with payload)
        assert pkt[8] == 0x00  # payload: off
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_build_command_set_temperature(self):
        """Set temperature uses FEAA with cmd_1=0x81, payload=[2, temp]."""
        pkt = self.proto.build_command(4, 25, 1234)  # cmd=4 (set temp), arg=25
        assert pkt[0] == 0xFE
        assert pkt[1] == 0xAA
        assert pkt[6] == 0x81  # cmd_1 (control command)
        assert pkt[7] == 0x03  # cmd_2 (with payload)
        assert pkt[8] == 0x02  # run_mode: temperature
        assert pkt[9] == 25    # run_param: temperature value
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_build_command_set_level(self):
        """Set level uses FEAA with cmd_1=0x81, payload=[1, level]."""
        pkt = self.proto.build_command(5, 7, 1234)  # cmd=5 (set level), arg=7
        assert pkt[0] == 0xFE
        assert pkt[1] == 0xAA
        assert pkt[6] == 0x81  # cmd_1 (control command)
        assert pkt[7] == 0x03  # cmd_2 (with payload)
        assert pkt[8] == 0x01  # run_mode: level
        assert pkt[9] == 7     # run_param: level value
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_build_command_set_mode(self):
        """Set mode uses FEAA with cmd_1=0x81, cmd_2=0x02."""
        pkt = self.proto.build_command(2, 1, 1234)
        assert pkt[0] == 0xFE
        assert pkt[1] == 0xAA
        assert pkt[6] == 0x81  # cmd_1 (control command)
        assert pkt[7] == 0x02  # cmd_2 (without payload)
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_build_command_config_uses_aa55_fallback(self):
        """Config commands (14-21) fall back to AA55 format."""
        for cmd in (14, 15, 16, 17, 19, 20, 21):
            pkt = self.proto.build_command(cmd, 0, 1234)
            assert pkt[0] == 0xAA
            assert pkt[1] == 0x55
            assert len(pkt) == 8

    def test_build_command_unknown_defaults_to_status(self):
        """Unknown command defaults to status request."""
        pkt = self.proto.build_command(99, 0, 1234)
        assert pkt[0] == 0xFE
        assert pkt[1] == 0xAA
        assert pkt[6] == 0x80  # status query
        assert pkt[7] == 0x00  # read

    def test_feaa_packet_length_field(self):
        """FEAA packet length field is correct (uint16 LE)."""
        pkt = self.proto.build_command(1, 0, 1234)  # status request (9 bytes)
        # Length field is bytes 4-5 (LE), should be 9
        length = pkt[4] | (pkt[5] << 8)
        assert length == len(pkt)

    def test_feaa_checksum_calculation(self):
        """Verify FEAA checksum is sum of all previous bytes & 0xFF."""
        pkt = self.proto.build_command(3, 1, 1234)  # power on
        expected_checksum = sum(pkt[:-1]) & 0xFF
        assert pkt[-1] == expected_checksum

    def test_is_heater_protocol(self):
        assert isinstance(self.proto, HeaterProtocol)

    def test_not_vevor_command_mixin(self):
        """CBFF no longer uses VevorCommandMixin (uses FEAA instead)."""
        assert not isinstance(self.proto, VevorCommandMixin)

    # -----------------------------------------------------------------------
    # V2.1 Encrypted Mode Tests
    # -----------------------------------------------------------------------

    def test_v21_mode_default_false(self):
        """V2.1 mode is disabled by default."""
        assert self.proto.v21_mode is False

    def test_set_v21_mode(self):
        """Can enable and disable V2.1 mode."""
        self.proto.set_v21_mode(True)
        assert self.proto.v21_mode is True
        self.proto.set_v21_mode(False)
        assert self.proto.v21_mode is False

    def test_build_handshake_basic(self):
        """Handshake command builds correctly."""
        self.proto.set_device_sn("E466E5BC086D")
        pkt = self.proto.build_handshake(1234)
        # Handshake is always encrypted, so we can't check raw bytes
        # Just verify it's a bytearray with reasonable length
        assert isinstance(pkt, bytearray)
        assert len(pkt) > 8  # At least header + payload + checksum

    def test_build_handshake_pin_encoding(self):
        """Handshake PIN is encoded as [PIN % 100, PIN // 100]."""
        # Build unencrypted handshake (no device_sn)
        proto = ProtocolCBFF()
        pkt = proto.build_handshake(1234)  # Should be [34, 12]
        # Without encryption, we can verify the payload
        # Packet: FEAA + ver + pkg + len(2) + cmd1(0x86) + cmd2(0x00) + payload(2) + checksum
        assert pkt[0] == 0xFE
        assert pkt[1] == 0xAA
        assert pkt[6] == 0x86  # CMD1 for password/handshake
        assert pkt[7] == 0x00  # CMD2
        assert pkt[8] == 34    # 1234 % 100
        assert pkt[9] == 12    # 1234 // 100

    def test_v21_encrypt_decrypt_roundtrip(self):
        """Double-XOR encryption/decryption is symmetric."""
        device_sn = "E466E5BC086D"
        original = bytearray([0xFE, 0xAA, 0x00, 0x00, 0x09, 0x00, 0x80, 0x00, 0x27])
        encrypted = ProtocolCBFF._encrypt_cbff(original, device_sn)
        decrypted = ProtocolCBFF._decrypt_cbff(encrypted, device_sn)
        assert decrypted == original

    def test_v21_known_power_off_encryption(self):
        """Verify Power OFF encryption matches @Xev's documented example.

        From documentation:
        Raw:       FE AA 00 00 09 00 01 00 B8
        Encrypted: CB FF 45 45 3B 5A 31 27 C9
        """
        device_sn = "E466E5BC086D"
        raw = bytearray([0xFE, 0xAA, 0x00, 0x00, 0x09, 0x00, 0x01, 0x00, 0xB8])
        encrypted = ProtocolCBFF._encrypt_cbff(raw, device_sn)
        expected = bytearray([0xCB, 0xFF, 0x45, 0x45, 0x3B, 0x5A, 0x31, 0x27, 0xC9])
        assert encrypted == expected

    def test_v21_command_encrypted_when_enabled(self):
        """Commands are encrypted when V2.1 mode is enabled."""
        self.proto.set_device_sn("E466E5BC086D")
        self.proto.set_v21_mode(False)
        unencrypted = self.proto.build_command(0, 0, 1234)  # Status request

        self.proto.set_v21_mode(True)
        encrypted = self.proto.build_command(0, 0, 1234)

        # Encrypted packet should be different
        assert encrypted != unencrypted
        # Header should be encrypted (not FEAA anymore)
        assert encrypted[:2] != bytearray([0xFE, 0xAA])

    def test_v21_power_on_with_payload(self):
        """V2.1 Power ON includes mode/param/time payload."""
        proto = ProtocolCBFF()
        proto.set_v21_mode(True)
        # Without device_sn, we can see the unencrypted structure
        pkt = proto.build_command(3, 1, 1234)  # Power ON

        # Check packet structure (before encryption, since no device_sn)
        assert pkt[0] == 0xFE
        assert pkt[1] == 0xAA
        assert pkt[6] == 0x81  # CMD1 for control
        assert pkt[7] == 0x01  # CMD2 for power on
        # Payload: [mode, param, time_l, time_h] = [1, 5, 0xFF, 0xFF]
        assert pkt[8] == 1     # run_mode (level)
        assert pkt[9] == 5     # run_param (level 5)
        assert pkt[10] == 0xFF # remain_time low
        assert pkt[11] == 0xFF # remain_time high

    def test_v21_power_off_no_payload(self):
        """V2.1 Power OFF is a simple command without payload."""
        proto = ProtocolCBFF()
        proto.set_v21_mode(True)
        pkt = proto.build_command(3, 0, 1234)  # Power OFF

        assert pkt[6] == 0x81  # CMD1 for control
        assert pkt[7] == 0x00  # CMD2 for power off
        # Length should be 9 bytes (no payload)
        length = pkt[4] | (pkt[5] << 8)
        assert length == 9

    def test_v21_set_temperature_with_payload(self):
        """V2.1 set temperature includes mode/param/time payload."""
        proto = ProtocolCBFF()
        proto.set_v21_mode(True)
        pkt = proto.build_command(4, 25, 1234)  # Set temp to 25°C

        assert pkt[8] == 2     # run_mode (temperature)
        assert pkt[9] == 25    # run_param (25°C)
        assert pkt[10] == 0xFF # remain_time low
        assert pkt[11] == 0xFF # remain_time high

    def test_v21_set_level_with_payload(self):
        """V2.1 set level includes mode/param/time payload."""
        proto = ProtocolCBFF()
        proto.set_v21_mode(True)
        pkt = proto.build_command(5, 7, 1234)  # Set level 7

        assert pkt[8] == 1     # run_mode (level)
        assert pkt[9] == 7     # run_param (level 7)
        assert pkt[10] == 0xFF # remain_time low
        assert pkt[11] == 0xFF # remain_time high


# ---------------------------------------------------------------------------
# ProtocolHcalory (mode=7, MVP1/MVP2, variable length)
# ---------------------------------------------------------------------------

def _make_hcalory_response(
    device_state=0x00,  # 0=standby, 1=temp, 2=gear, 3=fan, FF=fault
    temp_or_gear=20,
    auto_start_stop=0,
    voltage=124,  # raw value, /10 = 12.4V
    shell_temp_sign=0,
    shell_temp=450,  # raw value, /10 = 45.0°C
    ambient_temp_sign=0,
    ambient_temp=200,  # raw value, /10 = 20.0°C
    status_flags=0b00000000,
    highland_mode=0,
    temp_unit=0,
    altitude_unit=0,
    altitude_sign=0,
    altitude=0,
) -> bytearray:
    """Build a Hcalory response packet.

    Response hex char positions (from protocol docs):
    - 0-3: device_id (4 chars)
    - 4-7: timestamp (4 chars)
    - 8-11: reserved (4 chars)
    - 12-13: highland_gear (2 chars)
    - 14-15: reserved (2 chars)
    - 16-17: status_flags (2 chars)
    - 18-19: device_state (2 chars)
    - 20-21: temp_or_gear (2 chars)
    - 22-23: auto_start_stop (2 chars)
    - 24-27: voltage_raw (4 chars)
    - 28-29: shell_temp_sign (2 chars)
    - 30-33: shell_temp_raw (4 chars)
    - 34-35: ambient_temp_sign (2 chars)
    - 36-39: ambient_temp_raw (4 chars)
    - 40-45: reserved (6 chars)
    - 46-47: scene_id (2 chars)
    - 48-49: highland_mode (2 chars)
    - 50-51: temp_unit (2 chars)
    MVP2 extended:
    - 52-53: height_unit (2 chars)
    - 54-55: altitude_sign (2 chars)
    - 56-59: altitude_raw (4 chars)
    """
    hex_data = ""

    # 0-3: device_id (4 chars)
    hex_data += "0000"
    # 4-7: timestamp (4 chars)
    hex_data += "0000"
    # 8-11: reserved (4 chars)
    hex_data += "0000"
    # 12-13: highland_gear (2 chars)
    hex_data += "00"
    # 14-15: reserved (2 chars)
    hex_data += "00"
    # 16-17: status_flags (2 chars)
    hex_data += f"{status_flags:02X}"
    # 18-19: device_state (2 chars)
    hex_data += f"{device_state:02X}"
    # 20-21: temp_or_gear (2 chars)
    hex_data += f"{temp_or_gear:02X}"
    # 22-23: auto_start_stop (2 chars)
    hex_data += f"{auto_start_stop:02X}"
    # 24-27: voltage_raw (4 chars)
    hex_data += f"{voltage:04X}"
    # 28-29: shell_temp_sign (2 chars)
    hex_data += f"{shell_temp_sign:02X}"
    # 30-33: shell_temp_raw (4 chars)
    hex_data += f"{shell_temp:04X}"
    # 34-35: ambient_temp_sign (2 chars)
    hex_data += f"{ambient_temp_sign:02X}"
    # 36-39: ambient_temp_raw (4 chars)
    hex_data += f"{ambient_temp:04X}"
    # 40-45: reserved (6 chars)
    hex_data += "000000"
    # 46-47: scene_id (2 chars)
    hex_data += "00"
    # 48-49: highland_mode (2 chars)
    hex_data += f"{highland_mode:02X}"
    # 50-51: temp_unit (2 chars)
    hex_data += f"{temp_unit:02X}"
    # 52-53: height_unit (2 chars)
    hex_data += f"{altitude_unit:02X}"
    # 54-55: altitude_sign (2 chars)
    hex_data += f"{altitude_sign:02X}"
    # 56-59: altitude_raw (4 chars)
    hex_data += f"{altitude:04X}"

    return bytearray.fromhex(hex_data)


class TestProtocolHcalory:
    """Tests for Hcalory MVP1/MVP2 protocol (mode=7)."""

    def setup_method(self):
        self.proto = ProtocolHcalory()

    def test_protocol_properties(self):
        assert self.proto.protocol_mode == 7
        assert self.proto.name == "Hcalory"
        assert self.proto.needs_calibration is True
        assert self.proto.needs_post_status is True

    def test_is_heater_protocol(self):
        assert isinstance(self.proto, HeaterProtocol)

    def test_not_vevor_command_mixin(self):
        """Hcalory uses its own command format, not VevorCommandMixin."""
        assert not isinstance(self.proto, VevorCommandMixin)

    def test_set_mvp_version(self):
        """Test MVP version setter."""
        self.proto.set_mvp_version(True)
        assert self.proto._is_mvp2 is True
        self.proto.set_mvp_version(False)
        assert self.proto._is_mvp2 is False

    def test_parse_returns_none_for_short_data(self):
        """Data shorter than 26 bytes (52 hex chars) returns None."""
        short_data = bytearray(20)
        result = self.proto.parse(short_data)
        assert result is None

    def test_parse_standby_state(self):
        """Device state 0x00 = standby."""
        data = _make_hcalory_response(device_state=0x00)
        result = self.proto.parse(data)
        assert result is not None
        assert result.get("connected") is True
        assert result.get("running_state") == 0
        assert result.get("hcalory_device_state") == 0x00

    def test_parse_temperature_mode(self):
        """Device state 0x01 = temperature auto mode."""
        data = _make_hcalory_response(device_state=0x01, temp_or_gear=25)
        result = self.proto.parse(data)
        assert result is not None
        assert result.get("running_state") == 1
        assert result.get("running_mode") == 2  # RUNNING_MODE_TEMPERATURE
        assert result.get("set_temp") == 25
        assert result.get("hcalory_device_state") == 0x01

    def test_parse_gear_mode(self):
        """Device state 0x02 = manual gear mode."""
        data = _make_hcalory_response(device_state=0x02, temp_or_gear=3)
        result = self.proto.parse(data)
        assert result is not None
        assert result.get("running_state") == 1
        assert result.get("running_mode") == 1  # RUNNING_MODE_LEVEL
        assert result.get("hcalory_gear") == 3
        # Gear 3 maps to standard level 5
        assert result.get("set_level") == 5

    def test_parse_fan_mode(self):
        """Device state 0x03 = natural wind (fan only)."""
        data = _make_hcalory_response(device_state=0x03)
        result = self.proto.parse(data)
        assert result is not None
        assert result.get("running_state") == 1
        assert result.get("running_mode") == 0  # RUNNING_MODE_MANUAL

    def test_parse_fault_state(self):
        """Device state 0xFF = machine fault."""
        data = _make_hcalory_response(device_state=0xFF)
        result = self.proto.parse(data)
        assert result is not None
        assert result.get("running_state") == 0
        assert result.get("hcalory_device_state") == 0xFF

    def test_parse_auto_start_stop(self):
        """Auto start/stop flag parsing."""
        data = _make_hcalory_response(auto_start_stop=1)
        result = self.proto.parse(data)
        assert result.get("auto_start_stop") is True

        data = _make_hcalory_response(auto_start_stop=0)
        result = self.proto.parse(data)
        assert result.get("auto_start_stop") is False

    def test_parse_voltage(self):
        """Voltage is divided by 10."""
        data = _make_hcalory_response(voltage=124)
        result = self.proto.parse(data)
        assert result.get("supply_voltage") == 12.4

    def test_parse_temperatures(self):
        """Shell and ambient temps are signed and divided by 10."""
        data = _make_hcalory_response(
            shell_temp_sign=0, shell_temp=450,  # +45.0°C
            ambient_temp_sign=0, ambient_temp=200,  # +20.0°C
        )
        result = self.proto.parse(data)
        assert result.get("case_temperature") == 45.0
        assert result.get("cab_temperature") == 20.0

    def test_parse_negative_temperatures(self):
        """Negative temperatures have sign=1."""
        data = _make_hcalory_response(
            shell_temp_sign=1, shell_temp=50,  # -5.0°C
            ambient_temp_sign=1, ambient_temp=100,  # -10.0°C
        )
        result = self.proto.parse(data)
        assert result.get("case_temperature") == -5.0
        assert result.get("cab_temperature") == -10.0

    def test_parse_temp_unit(self):
        """Temperature unit: 0=Celsius, 1=Fahrenheit."""
        data = _make_hcalory_response(temp_unit=0)
        result = self.proto.parse(data)
        assert result.get("temp_unit") == 0

        data = _make_hcalory_response(temp_unit=1)
        result = self.proto.parse(data)
        assert result.get("temp_unit") == 1

    def test_parse_altitude(self):
        """Altitude parsing (MVP2 extended)."""
        data = _make_hcalory_response(
            altitude_unit=0, altitude_sign=0, altitude=1500
        )
        result = self.proto.parse(data)
        assert result.get("altitude") == 1500
        assert result.get("altitude_unit") == 0

    def test_gear_level_mapping(self):
        """Test Hcalory 1-6 to standard 1-10 level mapping."""
        # Test _map_hcalory_to_standard_level
        assert self.proto._map_hcalory_to_standard_level(1) == 2
        assert self.proto._map_hcalory_to_standard_level(2) == 4
        assert self.proto._map_hcalory_to_standard_level(3) == 5
        assert self.proto._map_hcalory_to_standard_level(4) == 6
        assert self.proto._map_hcalory_to_standard_level(5) == 8
        assert self.proto._map_hcalory_to_standard_level(6) == 10

    def test_standard_to_hcalory_level_mapping(self):
        """Test standard 1-10 to Hcalory 1-6 level mapping."""
        # Test _map_standard_to_hcalory_level
        assert self.proto._map_standard_to_hcalory_level(1) == 1
        assert self.proto._map_standard_to_hcalory_level(2) == 1
        assert self.proto._map_standard_to_hcalory_level(3) == 2
        assert self.proto._map_standard_to_hcalory_level(4) == 2
        assert self.proto._map_standard_to_hcalory_level(5) == 3
        assert self.proto._map_standard_to_hcalory_level(6) == 4
        assert self.proto._map_standard_to_hcalory_level(7) == 5
        assert self.proto._map_standard_to_hcalory_level(8) == 5
        assert self.proto._map_standard_to_hcalory_level(9) == 6
        assert self.proto._map_standard_to_hcalory_level(10) == 6

    # --- Command builder tests ---

    def test_build_command_status_request(self):
        """Status request (command 0 or 1) uses HCALORY_CMD_POWER."""
        pkt = self.proto.build_command(1, 0, 1234)
        assert pkt[0] == 0x00
        assert pkt[1] == 0x02  # Protocol ID
        # Checksum is last byte
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_build_command_power_on(self):
        """Power on (cmd=3, arg=1)."""
        pkt = self.proto.build_command(3, 1, 1234)
        assert pkt[0] == 0x00
        assert pkt[1] == 0x02  # Protocol ID
        # Should contain HCALORY_POWER_ON (0x01) in payload
        assert 0x01 in pkt
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_build_command_power_off(self):
        """Power off (cmd=3, arg=0)."""
        pkt = self.proto.build_command(3, 0, 1234)
        assert pkt[0] == 0x00
        assert pkt[1] == 0x02  # Protocol ID
        # Should contain HCALORY_POWER_OFF (0x02) in payload
        assert 0x02 in pkt
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_build_command_set_temperature(self):
        """Set temperature (cmd=4)."""
        pkt = self.proto.build_command(4, 25, 1234)
        assert pkt[0] == 0x00
        assert pkt[1] == 0x02
        # Should contain temperature value in payload
        assert 25 in pkt
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_build_command_set_level(self):
        """Set level (cmd=5) maps standard 1-10 to Hcalory 1-6."""
        # Standard level 5 -> Hcalory gear 3
        pkt = self.proto.build_command(5, 5, 1234)
        assert pkt[0] == 0x00
        assert pkt[1] == 0x02
        # Should contain mapped gear (3) in payload
        assert 3 in pkt
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_build_command_set_temp_unit_celsius(self):
        """Set temp unit to Celsius (cmd=15, arg=0)."""
        pkt = self.proto.build_command(15, 0, 1234)
        assert pkt[0] == 0x00
        assert pkt[1] == 0x02
        # Should contain HCALORY_POWER_CELSIUS (0x0A)
        assert 0x0A in pkt
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_build_command_set_temp_unit_fahrenheit(self):
        """Set temp unit to Fahrenheit (cmd=15, arg=1)."""
        pkt = self.proto.build_command(15, 1, 1234)
        assert pkt[0] == 0x00
        assert pkt[1] == 0x02
        # Should contain HCALORY_POWER_FAHRENHEIT (0x0B)
        assert 0x0B in pkt
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_build_command_auto_start_stop_on(self):
        """Enable auto start/stop (cmd=22, arg=1)."""
        pkt = self.proto.build_command(22, 1, 1234)
        assert pkt[0] == 0x00
        assert pkt[1] == 0x02
        # Should contain HCALORY_POWER_AUTO_ON (0x03)
        assert 0x03 in pkt
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_build_command_auto_start_stop_off(self):
        """Disable auto start/stop (cmd=22, arg=0)."""
        pkt = self.proto.build_command(22, 0, 1234)
        assert pkt[0] == 0x00
        assert pkt[1] == 0x02
        # Should contain HCALORY_POWER_AUTO_OFF (0x04)
        assert 0x04 in pkt
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_build_command_unknown_defaults_to_status(self):
        """Unknown command defaults to status query."""
        pkt = self.proto.build_command(99, 0, 1234)
        assert pkt[0] == 0x00
        assert pkt[1] == 0x02
        # Should contain HCALORY_POWER_QUERY (0x00)
        assert pkt[-1] == sum(pkt[:-1]) & 0xFF

    def test_checksum_calculation(self):
        """Verify checksum is sum of all previous bytes & 0xFF."""
        pkt = self.proto.build_command(3, 1, 1234)
        expected_checksum = sum(pkt[:-1]) & 0xFF
        assert pkt[-1] == expected_checksum

    def test_mvp2_query_uses_0a0a_dpid(self):
        """MVP2 status query should use dpID 0A0A with timestamp."""
        self.proto.set_mvp_version(True)
        pkt = self.proto.build_command(0, 0, 1234)
        # Should contain dpID 0A0A
        assert 0x0A in pkt
        # Check for 0A 0A sequence (dpID)
        hex_str = pkt.hex()
        assert "0a0a" in hex_str.lower()

    def test_mvp1_query_uses_0e04_dpid(self):
        """MVP1 status query should use dpID 0E04."""
        self.proto.set_mvp_version(False)
        pkt = self.proto.build_command(0, 0, 1234)
        # Should contain dpID 0E04
        hex_str = pkt.hex()
        assert "0e04" in hex_str.lower()

    def test_password_handshake_packet_structure(self):
        """MVP2 password handshake should use dpID 0A0C."""
        pkt = self.proto.build_password_handshake(1234)
        # Check header
        assert pkt[0] == 0x00
        assert pkt[1] == 0x02
        # Check dpID 0A0C
        hex_str = pkt.hex()
        assert "0a0c" in hex_str.lower()
        # Check password encoding (1234 -> 01 02 03 04)
        assert 0x01 in pkt
        assert 0x02 in pkt
        assert 0x03 in pkt
        assert 0x04 in pkt

    def test_password_handshake_custom_pin(self):
        """Password handshake with custom PIN."""
        pkt = self.proto.build_password_handshake(5678)
        # PIN 5678 -> digits 5, 6, 7, 8
        assert 0x05 in pkt
        assert 0x06 in pkt
        assert 0x07 in pkt
        assert 0x08 in pkt

    def test_password_state_tracking(self):
        """Test password handshake state tracking."""
        self.proto.set_mvp_version(True)
        # Initially needs password
        assert self.proto.needs_password_handshake is True
        # Mark as sent
        self.proto.mark_password_sent()
        assert self.proto.needs_password_handshake is False
        # Reset state
        self.proto.reset_password_state()
        assert self.proto.needs_password_handshake is True

    def test_mvp1_does_not_need_password(self):
        """MVP1 should not require password handshake."""
        self.proto.set_mvp_version(False)
        assert self.proto.needs_password_handshake is False

    def test_bcd_encoding(self):
        """Test BCD encoding helper."""
        # 12 in BCD is 0x12 (not 0x0C)
        assert self.proto._to_bcd(12) == 0x12
        assert self.proto._to_bcd(59) == 0x59
        assert self.proto._to_bcd(0) == 0x00
        assert self.proto._to_bcd(99) == 0x99
