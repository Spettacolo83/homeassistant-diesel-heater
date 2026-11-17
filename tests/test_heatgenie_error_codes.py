"""HeatGenie fault display follows the app's 16-bit mask, not the AA55 table."""

import pytest
from diesel_heater_ble.protocol import ProtocolHeatGenie

from custom_components.diesel_heater.const import ERROR_NAMES, WARM_DRIVE_ERROR_NAMES
from custom_components.diesel_heater.sensor import VevorErrorCodeSensor
from tests.test_sensor import create_mock_coordinator

APP_ERROR_LABELS = (
    "Undervoltage fault",
    "Overvoltage fault",
    "Ignition plug fault",
    "Oil pump failure",
    "Machine overheating fault",
    "Motor fault",
    "Short line fault",
    "Flame extinction fault",
    "Sensor fault",
    "Ignition fault",
    "Temperature sensor fault",
    "Overtemperature fault",
    "Air inlet high temperature protection",
    "Air outlet high temperature protection",
    "Air inlet temperature sensor fault",
    "Air outlet temperature sensor fault",
)


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
    assert VevorErrorCodeSensor(coordinator).native_value == f"E{number:02d} - {APP_ERROR_LABELS[number - 1]}"


@pytest.mark.parametrize(
    "mask,expected",
    [
        (0, "No fault"),
        (0x0080, "E08 - Flame extinction fault"),
        (0x0083, "E01 - Undervoltage fault"),
        (0x8080, "E08 - Flame extinction fault"),
    ],
)
def test_no_fault_reported_e08_and_multiple_bit_priority(mask, expected):
    coordinator = create_mock_coordinator(protocol_mode=8)
    parsed = ProtocolHeatGenie().parse(status_frame(mask, 52))
    assert parsed is not None
    coordinator.data.update(parsed)
    assert VevorErrorCodeSensor(coordinator).native_value == expected


@pytest.mark.parametrize("mode", [0, 1, 2])
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
    coordinator.is_dz06_neo = True
    coordinator.data["neo_controller_type"] = "air"
    expected = (f"E{error:02d} - {WARM_DRIVE_ERROR_NAMES[error]}" if error else "No fault")
    assert VevorErrorCodeSensor(coordinator).native_value == expected


@pytest.mark.parametrize("error", [-1, 3, 65536, None])
def test_malformed_heatgenie_code_is_not_mislabeled(error):
    coordinator = create_mock_coordinator(protocol_mode=8)
    coordinator.data["error_code"] = error
    expected = f"Unknown error ({error})" if isinstance(error, int) and error >= 0 else None
    assert VevorErrorCodeSensor(coordinator).native_value == expected
