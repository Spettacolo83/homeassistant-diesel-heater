"""Regressions for confirmed audit findings."""
import pytest

from diesel_heater_ble.protocol import ProtocolAA55, ProtocolAA66, ProtocolCronus


@pytest.mark.parametrize("protocol", [ProtocolAA55, ProtocolAA66])
def test_short_plain_aa_payload_does_not_raise(protocol):
    assert protocol().parse(bytearray()) is None


@pytest.mark.parametrize("payload", [b"", b"\x00", b"\xff", b"\x00\x02"])
def test_cronus_does_not_infer_air_from_invalid_type(payload):
    assert ProtocolCronus().parse_records({"h1_available": payload}) is None
