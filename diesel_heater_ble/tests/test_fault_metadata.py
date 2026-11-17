"""Fault metadata extracted from the Sunster APK's byte-level call paths."""

import pytest

from diesel_heater_ble.protocol import ProtocolAA66, ProtocolAA66Encrypted, ProtocolCBFF


@pytest.mark.parametrize("raw", range(256))
@pytest.mark.parametrize("cls,offset", [(ProtocolAA66, 17), (ProtocolAA66Encrypted, 35)])
def test_aa66_preserves_raw_and_family_for_every_byte(cls, offset, raw):
    frame = bytearray(48)
    frame[8] = 1
    frame[offset] = raw
    state = cls().parse(frame)
    assert state["error_code_raw"] == raw
    assert state["error_code"] == raw % 64
    assert state["error_family"] == ("XMZ", "JW", "unknown", "unknown")[raw // 64]


@pytest.mark.parametrize("display", range(256))
@pytest.mark.parametrize("detail", [0, 127, 128, 129, 130, 131, 255])
def test_cbff_tag_and_override_are_independent(display, detail):
    frame = bytearray(47)
    frame[:2] = b"\xcb\xff"
    frame[15] = display
    frame[16] = detail
    frame[-1] = sum(frame[:-1]) & 255
    p = ProtocolCBFF()
    state = p.parse(frame)
    assert state is not None
    assert state["error_display_raw"] == display
    assert state["error_detail_raw"] == detail
    if detail < 128:
        assert state["error_code"] == display % 64
        assert state["error_family"] == ("XMZ", "TY", "DD1", "DD2")[display // 64]
    else:
        assert state["error_code"] == display
        assert state["error_family"] == {128: "XMZ", 129: "TY", 130: "JW"}.get(detail, "unknown")
    assert p.parse_to_state(frame).as_dict()["error_family"] == state["error_family"]
