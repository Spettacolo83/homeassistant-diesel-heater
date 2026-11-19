"""Parser-to-entity regressions from the saved APK fault-display call paths."""

from unittest.mock import MagicMock

import pytest
from diesel_heater_ble.protocol import (
    ProtocolAA55,
    ProtocolAA55Encrypted,
    ProtocolAA66,
    ProtocolAA66Encrypted,
    ProtocolABBA,
    ProtocolCBFF,
    ProtocolHcalory,
)

from custom_components.diesel_heater.binary_sensor import VevorHeaterProblemSensor
from custom_components.diesel_heater.faults import SUNSTER_ERROR_NAMES
from custom_components.diesel_heater.hcalory import HcaloryVariant, uses_extended_error_codes
from custom_components.diesel_heater.sensor import VevorErrorCodeSensor
from tests.test_dz06_neo import coordinator_for_layout
from tests.test_protocol import _make_abba_data, _make_cbff_data
from tests.test_sensor import create_mock_coordinator


def display(mode, parsed, **flags):
    c = create_mock_coordinator(mode)
    c.data.update(parsed)
    for key, value in flags.items():
        setattr(c, key, value)
    return VevorErrorCodeSensor(c).native_value, VevorHeaterProblemSensor(c).is_on


@pytest.mark.parametrize("proto,offset", [(ProtocolAA55, 4), (ProtocolAA55Encrypted, 4)])
@pytest.mark.parametrize(
    "raw,label", [(1, "Startup failure"), (9, "Overheating"), (11, "CO warning"), (50, "Low battery")]
)
def test_aa55_correct_table_and_co(proto, offset, raw, label):
    frame = bytearray(48)
    frame[offset] = raw
    frame[8] = 1
    parsed = proto().parse(frame)
    assert display(proto.protocol_mode, parsed) == (label, True)


@pytest.mark.parametrize("proto,offset", [(ProtocolAA66, 17), (ProtocolAA66Encrypted, 35)])
@pytest.mark.parametrize(
    "raw,label",
    [
        (1, "Voltage fault"),
        (2, "Low battery"),
        (7, "Intake air sensor fault"),
        (3, "Ignition unit fault"),
        (4, "Fuel pump fault"),
        (5, "Overheating"),
        (6, "Fan fault"),
        (8, "Lack of fuel / flameout"),
        (9, "Overheat sensor fault"),
        (10, "Second startup failure"),
        (11, "CO warning"),
    ],
)
def test_aa66_alternate_table(proto, offset, raw, label):
    frame = bytearray(48)
    frame[offset] = raw
    frame[8] = 1
    parsed = proto().parse(frame)
    assert parsed["error_code_raw"] == raw
    assert display(proto.protocol_mode, parsed) == (f"E{raw:02d} - {label}", True)


@pytest.mark.parametrize("proto,offset", [(ProtocolAA55Encrypted, 4), (ProtocolAA66Encrypted, 35)])
def test_motherboard_six_uses_twx_not_standard_table(proto, offset):
    frame = bytearray(48)
    frame[offset] = 6
    frame[44] = 6
    frame[8] = 1
    parsed = proto().parse(frame)
    assert parsed["error_family"] == "TWX"
    assert display(proto.protocol_mode, parsed) == ("E-06: Intake sensor anomaly", True)


@pytest.mark.parametrize(
    "raw,label",
    [
        (2, "E2 - Voltage fault"),
        (3, "E3 - Igniter fault"),
        (5, "E5 - Over-temperature"),
        (8, "E8 - Flameout"),
        (10, "E10 - Startup failure"),
        (11, "ECO - Carbon monoxide alarm"),
    ],
)
def test_abba_raw_codes_use_heatercc_table(raw, label):
    parsed = ProtocolABBA().parse(_make_abba_data(mode_byte=255, gear_byte=raw))
    assert display(5, parsed) == (label, True)


def cbff(display_byte, detail=0, encrypted=False):
    frame = _make_cbff_data(fault_display=display_byte)
    frame[16] = detail
    frame[-1] = sum(frame[:-1]) & 255
    p = ProtocolCBFF()
    p.set_device_sn("AABBCCDDEEFF")
    return p.parse(p._encrypt_cbff(frame, "AABBCCDDEEFF") if encrypted else frame)


@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize(
    "byte,detail,family,code,label",
    [
        (1, 0, "XMZ", 1, "E-01: Voltage anomaly"),
        (65, 0, "TY", 1, "E-01: Startup failed"),
        (3, 130, "JW", 3, "E-03, Power supply voltage too low"),
        (33, 130, "JW", 33, "E-00, Combustion sensor open circuit"),
        (65, 128, "XMZ", 65, "Unknown error (65, family=XMZ)"),
        (65, 129, "TY", 65, "Unknown error (65, family=TY)"),
        (129, 0, "DD1", 1, "Unknown error (1, family=DD1)"),
        (193, 0, "DD2", 1, "Unknown error (1, family=DD2)"),
        (7, 131, "unknown", 7, "Unknown error (7, family=unknown)"),
    ],
)
def test_cbff_family_override_encryption_and_unknowns(encrypted, byte, detail, family, code, label):
    parsed = cbff(byte, detail, encrypted)
    assert parsed["error_family"] == family
    assert parsed["error_code"] == code
    assert parsed["error_display_raw"] == byte and parsed["error_detail_raw"] == detail
    assert display(6, parsed) == (label, True)


@pytest.mark.parametrize("variant", list(HcaloryVariant))
@pytest.mark.parametrize("raw", [1, 8, 10, 11, 32, 33])
def test_all_mvp_variants_preserve_apk_code_format(variant, raw):
    frame = bytearray(40)
    frame[8] = 3
    frame[20] = 255
    frame[22] = raw
    frame[-1] = sum(frame[8:-1]) & 255
    parsed = ProtocolHcalory().parse(frame)
    extended = uses_extended_error_codes(variant, {})
    parsed["hcalory_error_extended"] = extended
    if extended:
        major, minor = raw >> 4, raw & 15
        expected = f"E{major:02d}" + (str(minor) if minor else "")
    else:
        expected = f"E{raw}" if raw in (10, 11) else f"E0{raw}"
    assert display(7, parsed) == (expected, True)


@pytest.mark.parametrize("variant", list(HcaloryVariant))
def test_manufacturer_05bd_selects_extended_format_independent_of_variant(variant):
    assert uses_extended_error_codes(variant, {0: bytes.fromhex("0000000005bd0000000000000000")})
    assert uses_extended_error_codes(variant, {}) is (variant == HcaloryVariant.MVP3_3)


@pytest.mark.parametrize("raw,code", [(0, 0), (1, 1), (2, 1), (6, 5), (11, 10)])
@pytest.mark.parametrize("kind", ["air", "water"])
def test_legacy_neo_populates_fault_field_without_water_description_assumption(raw, code, kind):
    c = coordinator_for_layout(True, name="Neo")
    c.data["neo_controller_type"] = kind
    c._burnoff = MagicMock()
    frame = bytearray(39)
    frame[:2] = b"\x5a\x25"
    frame[4] = raw
    c._handle_legacy_dz06_neo_status(frame)
    assert c.data["error_code"] == code
    expected = "No fault" if code == 0 else (f"E{code:02d}" if kind == "water" else None)
    text, problem = display(0, c.data, is_dz06_neo=True)
    if expected is not None:
        assert text == expected
    else:
        assert text.startswith(f"E{code:02d} - ")
    assert problem is (code != 0)


@pytest.mark.parametrize("mode", range(9))
@pytest.mark.parametrize("error", [None, -1, True, "8"])
def test_invalid_fault_telemetry_is_unknown_not_no_fault(mode, error):
    assert display(mode, {"error_code": error}) == (None, None)


@pytest.mark.parametrize("mode", range(9))
def test_fault_clear_is_no_fault_for_every_family(mode):
    assert display(mode, {"error_code": 0}) == ("No fault", False)


def test_jw_same_code_differs_from_aa66_default():
    frame = bytearray(48)
    frame[17] = 0x43
    frame[8] = 1
    parsed = ProtocolAA66().parse(frame)
    assert parsed["error_code_raw"] == 67
    assert display(3, parsed) == ("E-03, Power supply voltage too low", True)


@pytest.mark.parametrize(
    "family,number,label",
    [(family, number, label) for family, table in SUNSTER_ERROR_NAMES.items() for number, label in table.items()],
)
def test_every_saved_sunster_mapping_reaches_sensor(family, number, label):
    code = 33 if family == "JW" and number == 0 else number
    if family == "TWX":
        frame = bytearray(48)
        frame[4] = code
        frame[44] = 6
        frame[8] = 1
        parsed = ProtocolAA55Encrypted().parse(frame)
        mode = 2
    else:
        detail = {"XMZ": 128, "TY": 129, "JW": 130}[family]
        parsed = cbff(code, detail)
        mode = 6
    text, problem = display(mode, parsed)
    expected = label if label.startswith("E") else f"E{number:02d} - {label}"
    assert text == expected
    assert problem is True


def test_fault_family_does_not_leak_into_aa55_after_protocol_reselection():
    # A coordinator merges dictionaries; a previous family's metadata can remain.
    old = cbff(3, 130)
    frame = bytearray(48)
    frame[4] = 3
    frame[8] = 1
    old.update(ProtocolAA55Encrypted().parse(frame))
    assert display(2, old) == ("Supply voltage overrun", True)


@pytest.mark.parametrize("variant", list(HcaloryVariant))
@pytest.mark.parametrize("advertisement", [False, True])
def test_real_notification_sets_hcalory_formatter_metadata(monkeypatch, variant, advertisement):
    from types import SimpleNamespace

    from custom_components.diesel_heater import coordinator as module
    from tests.test_coordinator import create_mock_coordinator as real_coordinator

    c = real_coordinator()
    c._hcalory_variant = variant
    c._is_hcalory_device = True
    c._protocols[7] = ProtocolHcalory()
    manufacturer = {0: bytes.fromhex("0000000005bd0000000000000000")} if advertisement else {}
    monkeypatch.setattr(
        module.bluetooth,
        "async_last_service_info",
        lambda *a, **k: SimpleNamespace(name="Heater", manufacturer_data=manufacturer),
    )
    frame = bytearray(40)
    frame[:2] = b"\x00\x02"
    frame[8] = 3
    frame[20] = 255
    frame[22] = 33
    frame[-1] = sum(frame[8:-1]) & 255
    c._notification_callback(0, frame)
    expected = advertisement or variant == HcaloryVariant.MVP3_3
    assert "hcalory_error_extended" in c.data, c._logger.error.call_args_list
    assert c.data["hcalory_error_extended"] is expected
    assert VevorErrorCodeSensor(c).native_value == ("E021" if expected else "E033")


@pytest.mark.parametrize("kind", ["air", "water"])
async def test_cronus_keeps_interlock_and_does_not_create_aa55_fault_entities(kind):
    from types import SimpleNamespace

    from custom_components.diesel_heater.binary_sensor import async_setup_entry as setup_binary
    from custom_components.diesel_heater.sensor import async_setup_entry as setup_sensors

    c = create_mock_coordinator(9)
    c.data["cronus_controller_type"] = kind
    added = []
    entry = SimpleNamespace(runtime_data=c)
    await setup_sensors(None, entry, added.extend)
    await setup_binary(None, entry, added.extend)
    assert not any(isinstance(e, (VevorErrorCodeSensor, VevorHeaterProblemSensor)) for e in added)
    assert any(type(e).__name__ == "VevorCronusInterlockSensor" for e in added)


@pytest.mark.parametrize("variant", list(HcaloryVariant))
def test_hcalory_explicit_fault_state_with_zero_code_is_still_fault(variant):
    frame = bytearray(40)
    frame[8] = 3
    frame[20] = 255
    frame[22] = 0
    frame[-1] = sum(frame[8:-1]) & 255
    parsed = ProtocolHcalory().parse(frame)
    parsed["hcalory_error_extended"] = uses_extended_error_codes(variant, {})
    assert display(7, parsed) == ("E00", True)


def test_validated_hcalory_format_survives_missing_advertisement(monkeypatch):
    from custom_components.diesel_heater import coordinator as module
    from tests.test_coordinator import create_mock_coordinator as real_coordinator

    c = real_coordinator()
    c._protocols[7] = ProtocolHcalory()
    c._is_hcalory_device = True
    c._hcalory_error_extended = True
    monkeypatch.setattr(module.bluetooth, "async_last_service_info", lambda *a, **k: None)
    frame = bytearray(40)
    frame[:2] = b"\x00\x02"
    frame[8] = 3
    frame[20] = 255
    frame[22] = 33
    frame[-1] = sum(frame[8:-1]) & 255
    c._notification_callback(0, frame)
    assert c.data["hcalory_error_extended"] is True
    assert VevorErrorCodeSensor(c).native_value == "E021"
