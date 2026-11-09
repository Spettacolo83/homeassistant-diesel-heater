"""AirHeaterCC dispatches telemetry only for AB BA 11 CC replies."""

import pytest

from diesel_heater_ble import ProtocolABBA


@pytest.mark.parametrize(
    "prefix,size",
    [
        ("abba24ec", 40),
        ("abba04dc", 8),
        ("abba04dc", 21),
        ("abba05ea", 21),
        ("abba0000", 21),
        ("ffff11cc", 21),
        ("baab04cc", 21),
        ("abba11cc", 20),
    ],
)
def test_nonstatus_or_truncated_reply_is_rejected(prefix, size):
    p = ProtocolABBA()
    data = bytearray(size)
    data[:4] = bytes.fromhex(prefix)
    if size > 10:
        data[10] = 1
    assert p.parse(data) is None
    assert p._uses_fahrenheit is False


@pytest.mark.parametrize("size", [21, 22, 40])
def test_status_prefix_retains_compatible_extended_notifications(size):
    data = bytearray(size)
    data[:4] = bytes.fromhex("abba11cc")
    data[4:7] = bytes((1, 1, 20))
    data[11] = 50
    parsed = ProtocolABBA().parse(data)
    assert parsed["connected"]
    assert parsed["set_temp"] == 20
    assert parsed["cab_temperature"] == 20
