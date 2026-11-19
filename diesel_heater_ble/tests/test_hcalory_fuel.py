"""Hcalory3.3.1 DPID14 codec, kept separate from ordinary status replies."""

import pytest

from diesel_heater_ble import ProtocolHcalory


def packet(minutes, litres, fraction):
    data = bytearray.fromhex("000200010001000b14000006")
    data += minutes.to_bytes(3, "big") + litres.to_bytes(2, "big") + bytes([fraction])
    data.append(sum(data[8:]) & 255)
    return data


def test_exact_apk_query():
    assert ProtocolHcalory.build_fuel_query().hex() == "0002000100010006140000010015"


@pytest.mark.parametrize("minutes", [0, 1, 60, 65536, 0xFFFFFF])
@pytest.mark.parametrize("litres", [0, 1, 256, 65535])
@pytest.mark.parametrize("fraction", [0, 25, 99, 255])
def test_response_matches_apk_field_extraction(minutes, litres, fraction):
    frame = packet(minutes, litres, fraction)
    assert ProtocolHcalory.parse_fuel_response(frame) == {
        "session_runtime_minutes": minutes,
        "session_fuel_centilitres": litres * 100 + fraction,
    }
    assert ProtocolHcalory().parse(frame) is None


@pytest.mark.parametrize("change", ["short", "checksum", "different_dpid"])
def test_corrupt_or_unrelated_packet_cannot_become_fuel_report(change):
    frame = packet(180, 1, 25)
    if change == "short":
        frame = frame[:-1]
    elif change == "checksum":
        frame[-1] ^= 1
    else:
        frame[8] = 3
        frame[-1] = sum(frame[8:-1]) & 255
    assert ProtocolHcalory.parse_fuel_response(frame) is None
