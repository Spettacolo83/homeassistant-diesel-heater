"""HeatGenie fault display follows the app's 16-bit mask, not the AA55 table."""

import pytest
from diesel_heater_ble.protocol import ProtocolHeatGenie

from custom_components.diesel_heater.const import ERROR_NAMES, WARM_DRIVE_ERROR_NAMES
from custom_components.diesel_heater.sensor import VevorErrorCodeSensor
from tests.test_sensor import create_mock_coordinator


def status_frame(error_mask: int, length: int) -> bytearray:
    frame = bytearray(length)
    frame[0] = 0xAA
    frame[1] = 9
    frame[7] = 0xF2
    frame[8] = 6
    frame[9] = 0x20
    frame[28:30] = error_mask.to_bytes(2, "little")
    frame[-2:] = ProtocolHeatGenie.crc16(frame[:-2]).to_bytes(2, "big")
    return frame


@pytest.mark.parametrize("length", [50, 52])
@pytest.mark.parametrize("number", range(1, 17))
def test_parsed_fault_bit_displays_matching_e_code(number, length):
    coordinator = create_mock_coordinator(protocol_mode=8)
    parsed = ProtocolHeatGenie().parse(status_frame(1 << (number - 1), length))
    assert parsed is not None
    assert parsed["error_code"] == 1 << (number - 1)
    coordinator.data.update(parsed)
    assert VevorErrorCodeSensor(coordinator).native_value == f"E{number:02d}"


@pytest.mark.parametrize("mask,expected", [(0, "No fault"), (0x0080, "E08"), (0x0083, "E01"), (0x8080, "E08")])
def test_no_fault_reported_e08_and_multiple_bit_priority(mask, expected):
    coordinator = create_mock_coordinator(protocol_mode=8)
    parsed = ProtocolHeatGenie().parse(status_frame(mask, 52))
    assert parsed is not None
    coordinator.data.update(parsed)
    assert VevorErrorCodeSensor(coordinator).native_value == expected


@pytest.mark.parametrize("mode", [0, 1, 2, 3, 4, 5, 6, 7, 9])
@pytest.mark.parametrize("error", range(11))
def test_other_protocol_display_mappings_are_unchanged(mode, error):
    coordinator = create_mock_coordinator(protocol_mode=mode)
    coordinator.data["error_code"] = error
    assert VevorErrorCodeSensor(coordinator).native_value == ERROR_NAMES[error]


@pytest.mark.parametrize("error", range(11))
def test_warm_drive_mapping_is_unchanged(error):
    coordinator = create_mock_coordinator(protocol_mode=0)
    coordinator.is_warm_drive_controller = True
    coordinator.data["error_code"] = error
    assert VevorErrorCodeSensor(coordinator).native_value == WARM_DRIVE_ERROR_NAMES[error]


@pytest.mark.parametrize("error", [-1, 3, 65536, None])
def test_malformed_heatgenie_code_is_not_mislabeled(error):
    coordinator = create_mock_coordinator(protocol_mode=8)
    coordinator.data["error_code"] = error
    assert VevorErrorCodeSensor(coordinator).native_value == f"Unknown error ({error})"
