"""ABBA transport respects write-only FFF2 without changing other families."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.diesel_heater import coordinator as source
from tests.test_abba_fff0_probe import candidate
from tests.test_audit_repairs import abba_status
from tests.test_coordinator import create_mock_coordinator


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "properties,expected",
    [(["write"], True), (["write-without-response"], False), (["write", "write-without-response"], False)],
)
@pytest.mark.parametrize("command,argument", [(1, 0), (4, 23), (10, 0x0C223801)])
async def test_abba_status_roundtrip_uses_supported_write_type(properties, expected, command, argument):
    h = create_mock_coordinator()
    h._protocol_mode = 5
    h._protocol = h._protocols[5]
    h._is_abba_device = True
    h._abba_write_char = SimpleNamespace(uuid=source.ABBA_WRITE_UUID, properties=properties)
    h._characteristic = SimpleNamespace(uuid=source.ABBA_NOTIFY_UUID, properties=["notify"])

    async def write(char, packet, response):
        assert char is h._abba_write_char
        assert response is expected
        assert packet == h._protocol.build_command(command, argument, h._passkey) or packet.hex() == "baab04cc00000035"
        h._notification_callback(0, abba_status(unit=0, target=20))

    h._client = SimpleNamespace(is_connected=True, write_gatt_char=AsyncMock(side_effect=write))
    with patch.object(source.asyncio, "sleep", AsyncMock()):
        assert await h._send_command(command, argument)
    assert h.data["set_temp"] == 20


@pytest.mark.asyncio
async def test_write_only_abba_identity_probe_works_before_hcalory_hint_is_resolved():
    h, client = candidate(None)

    async def write(char, packet, response):
        assert response is True
        h._notification_callback(0, abba_status(unit=0, target=20))

    client.write_gatt_char = AsyncMock(side_effect=write)
    with (
        patch.object(source, "establish_connection", AsyncMock(return_value=client)),
        patch.object(source.asyncio, "sleep", AsyncMock()),
    ):
        await h._ensure_connected()
    assert h.protocol_mode == 5
    assert not h._is_hcalory_device


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "family,uuid,packet",
    [
        ("AA55", source.CHARACTERISTIC_UUID, "aa550c220100002f"),
        ("AA55 Encrypted", source.CHARACTERISTIC_UUID, "aa550c220100002f"),
        ("AA66", source.CHARACTERISTIC_UUID, "aa550c220100002f"),
        ("AA66 Encrypted", source.CHARACTERISTIC_UUID, "aa550c220100002f"),
        ("CBFF", source.CHARACTERISTIC_UUID, "feaa030100000000"),
        ("HeatGenie", "heatgenie-write", "aa00610101000000"),
        ("Cronus", "cronus-write", "550100"),
        ("DZ06 Neo", source.DZ06_NEO_WRITE_UUID, "a50901000114000001"),
        ("Warm Drive", source.DZ06_NEO_WRITE_UUID, "2612010108230f37060e1193050100000101ea86"),
        ("Hcalory MVP1", source.HCALORY_MVP1_WRITE_UUID, "000200010001000e040000090000000000000000000d"),
        ("Hcalory MVP2", source.HCALORY_MVP2_WRITE_UUID, "000200010001000a0a00000600000000000000"),
        ("Hcalory numbered", source.HCALORY_MVP1_WRITE_UUID, "000200010001000a0a00000600000000000000"),
    ],
)
async def test_other_protocol_write_types_are_unchanged(family, uuid, packet):
    h = create_mock_coordinator()
    h._characteristic = SimpleNamespace(uuid=uuid, properties=["write"])
    if family.startswith("Hcalory"):
        h._is_hcalory_device = True
        h._hcalory_write_char = h._characteristic
    elif family == "HeatGenie":
        h._is_heatgenie_device = True
        h._heatgenie_write_char = h._characteristic
    elif family == "Cronus":
        h._is_cronus_device = True
        h._cronus_write_char = h._characteristic
    elif family in ("DZ06 Neo", "Warm Drive"):
        h._is_abba_device = True
        h._abba_write_char = h._characteristic
    h._client = SimpleNamespace(is_connected=True, write_gatt_char=AsyncMock())
    await h._write_gatt(bytearray.fromhex(packet))
    h._client.write_gatt_char.assert_awaited_once_with(h._characteristic, bytearray.fromhex(packet), response=False)


@pytest.mark.asyncio
async def test_gatt_ack_without_status_does_not_confirm_abba_command():
    h = create_mock_coordinator()
    h._protocol_mode = 5
    h._protocol = h._protocols[5]
    h._is_abba_device = True
    h._abba_write_char = SimpleNamespace(uuid=source.ABBA_WRITE_UUID, properties=["write"])
    h._characteristic = SimpleNamespace(uuid=source.ABBA_NOTIFY_UUID, properties=["notify"])
    h._client = SimpleNamespace(is_connected=True, write_gatt_char=AsyncMock())
    assert not await h._send_command(1, 0, timeout=0)
    assert h._client.write_gatt_char.await_args.kwargs["response"] is True
    assert not h.data["connected"]
