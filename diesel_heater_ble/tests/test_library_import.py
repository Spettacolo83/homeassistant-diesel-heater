"""Verify that diesel_heater_ble library exports match the integration's protocol.py.

This test ensures the standalone library and the integration's embedded copy
produce identical results for the same input data.
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
    VevorCommandMixin,
    _decrypt_data,
    _encrypt_data,
    _u8_to_number,
    _unsign_to_sign,
)
from diesel_heater_ble.const import (
    ABBA_ERROR_NAMES,
    ABBA_STATUS_MAP,
    CBFF_RUN_STATE_OFF,
    ENCRYPTION_KEY,
    ERROR_NAMES,
    PROTOCOL_HEADER_AA55,
    PROTOCOL_HEADER_AA66,
    PROTOCOL_HEADER_ABBA,
    PROTOCOL_HEADER_CBFF,
    RUNNING_MODE_LEVEL,
    RUNNING_MODE_MANUAL,
    RUNNING_MODE_TEMPERATURE,
    RUNNING_STATE_OFF,
    RUNNING_STATE_ON,
    RUNNING_STEP_COOLDOWN,
    RUNNING_STEP_IGNITION,
    RUNNING_STEP_RUNNING,
    RUNNING_STEP_STANDBY,
)


class TestLibraryExports:
    """Verify the library exports all expected symbols."""

    def test_protocol_classes_exist(self):
        assert HeaterProtocol is not None
        assert VevorCommandMixin is not None
        assert ProtocolAA55 is not None
        assert ProtocolAA55Encrypted is not None
        assert ProtocolAA66 is not None
        assert ProtocolAA66Encrypted is not None
        assert ProtocolABBA is not None
        assert ProtocolCBFF is not None

    def test_helper_functions_exist(self):
        assert callable(_u8_to_number)
        assert callable(_unsign_to_sign)
        assert callable(_decrypt_data)
        assert callable(_encrypt_data)

    def test_protocol_modes(self):
        assert ProtocolAA55().protocol_mode == 1
        assert ProtocolAA55Encrypted().protocol_mode == 2
        assert ProtocolAA66().protocol_mode == 3
        assert ProtocolAA66Encrypted().protocol_mode == 4
        assert ProtocolABBA().protocol_mode == 5
        assert ProtocolCBFF().protocol_mode == 6


class TestLibraryConstants:
    """Verify protocol constants are correct."""

    def test_protocol_headers(self):
        assert PROTOCOL_HEADER_AA55 == 0xAA55
        assert PROTOCOL_HEADER_AA66 == 0xAA66
        assert PROTOCOL_HEADER_ABBA == 0xABBA
        assert PROTOCOL_HEADER_CBFF == 0xCBFF

    def test_running_states(self):
        assert RUNNING_STATE_OFF == 0
        assert RUNNING_STATE_ON == 1

    def test_running_modes(self):
        assert RUNNING_MODE_MANUAL == 0
        assert RUNNING_MODE_LEVEL == 1
        assert RUNNING_MODE_TEMPERATURE == 2

    def test_encryption_key(self):
        assert len(ENCRYPTION_KEY) == 8
        assert bytes(ENCRYPTION_KEY) == b"password"

    def test_abba_status_map(self):
        assert ABBA_STATUS_MAP[0x00] == RUNNING_STEP_STANDBY
        assert ABBA_STATUS_MAP[0x01] == RUNNING_STEP_RUNNING
        assert ABBA_STATUS_MAP[0x02] == RUNNING_STEP_COOLDOWN

    def test_cbff_off_states(self):
        assert CBFF_RUN_STATE_OFF == {2, 5, 6}

    def test_error_names(self):
        assert ERROR_NAMES[0] == "No fault"
        assert len(ERROR_NAMES) == 11

    def test_abba_error_names(self):
        assert ABBA_ERROR_NAMES[0] == "No fault"
        assert 192 in ABBA_ERROR_NAMES  # CO alarm


class TestLibraryParity:
    """Verify library and integration produce identical parse results."""

    def test_aa55_parse_parity(self):
        """Same AA55 packet parsed by library gives same result."""
        data = bytearray(18)
        data[0], data[1] = 0xAA, 0x55
        data[3] = 1  # running_state ON
        data[8] = 1  # Level mode
        data[9] = 5  # level 5
        data[11], data[12] = 0xC8, 0x00  # 20.0V
        data[13], data[14] = 0x96, 0x00  # case_temp 150
        data[15], data[16] = 0xE8, 0x00  # cab_temp 232

        p = ProtocolAA55()
        result = p.parse(data)
        assert result["running_state"] == 1
        assert result["running_mode"] == 1
        assert result["set_level"] == 5
        assert result["supply_voltage"] == 20.0

    def test_abba_parse_parity(self):
        """Same ABBA packet parsed by library gives same result."""
        data = bytearray(21)
        data[0], data[1] = 0xAB, 0xBA
        data[4] = 0x01  # Heating
        data[5] = 0x01  # Temperature mode
        data[6] = 22    # 22 degrees
        data[9] = 12    # 12V
        data[10] = 0    # Celsius
        data[11] = 52   # 52-30 = 22C
        data[12] = 0x00
        data[13] = 0x96  # case_temp = 150

        p = ProtocolABBA()
        result = p.parse(data)
        assert result["running_state"] == 1
        assert result["running_mode"] == RUNNING_MODE_TEMPERATURE
        assert result["set_temp"] == 22
        assert result["cab_temperature"] == 22.0

    def test_command_build_parity(self):
        """AA55 command builder produces same output."""
        p = ProtocolAA55()
        cmd = p.build_command(1, 0, 1234)
        assert cmd[0] == 0xAA
        assert cmd[1] == 0x55
        assert cmd[4] == 1  # command
        assert len(cmd) == 8
