"""Clock/configuration notifications cannot satisfy ABBA status requests."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.diesel_heater import coordinator as source
from tests.test_audit_repairs import abba_status
from tests.test_coordinator import create_mock_coordinator


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix,size", [("abba24ec", 40), ("abba04dc", 21), ("abba0000", 21), ("ffff11cc", 21)])
async def test_nonstatus_reply_does_not_mutate_telemetry_or_confirm_command(prefix, size):
    h = create_mock_coordinator()
    h._protocol_mode = 5
    h._protocol = h._protocols[5]
    h._is_abba_device = True
    h._abba_write_char = SimpleNamespace(uuid=source.ABBA_WRITE_UUID, properties=["write"])
    h._characteristic = SimpleNamespace(uuid=source.ABBA_NOTIFY_UUID, properties=["notify"])
    h._notification_callback(0, abba_status(unit=0, target=20))
    before = dict(h.data)
    frame = bytearray(size)
    frame[:4] = bytes.fromhex(prefix)

    async def write(*args, **kwargs):
        h._notification_callback(0, frame)

    h._client = SimpleNamespace(is_connected=True, write_gatt_char=AsyncMock(side_effect=write))
    with patch.object(source.asyncio, "sleep", AsyncMock()):
        assert not await h._send_command(1, 0, timeout=0.1)
    assert h.data == before
    assert h._notification_data is None


@pytest.mark.asyncio
async def test_configuration_during_identity_probe_does_not_confirm_abba():
    h = create_mock_coordinator()
    h._legacy_fff0_candidate = True
    frame = bytearray(40)
    frame[:4] = bytes.fromhex("abba24ec")
    h._notification_data = None
    before = dict(h.data)
    h._notification_callback(0, frame)
    assert h._legacy_fff0_candidate
    assert h._protocol_mode == 0
    assert h._notification_data is None
    assert h.data == before


@pytest.mark.asyncio
@pytest.mark.parametrize("order", [("status", "clock"), ("clock", "status")])
async def test_status_received_before_gatt_ack_survives_adjacent_clock_reply(order):
    h = create_mock_coordinator()
    h._protocol_mode = 5
    h._protocol = h._protocols[5]
    h._is_abba_device = True
    h._abba_write_char = SimpleNamespace(uuid=source.ABBA_WRITE_UUID, properties=["write"])
    h._characteristic = SimpleNamespace(uuid=source.ABBA_NOTIFY_UUID, properties=["notify"])
    entered, acknowledged = asyncio.Event(), asyncio.Event()
    status = abba_status(unit=0, target=20)
    clock = bytearray(40)
    clock[:4] = bytes.fromhex("abba24ec")

    async def write(*args, **kwargs):
        entered.set()
        await acknowledged.wait()

    h._client = SimpleNamespace(is_connected=True, write_gatt_char=AsyncMock(side_effect=write))
    command = asyncio.create_task(h._send_command(1, 0, timeout=0.2))
    await asyncio.wait_for(entered.wait(), 1)
    for frame in order:
        h._notification_callback(0, status if frame == "status" else clock)
    assert not command.done()
    assert h._notification_data == status
    acknowledged.set()
    assert await asyncio.wait_for(command, 1)
    assert h.data["set_temp"] == 20
    assert h.data["cab_temperature"] == 20
