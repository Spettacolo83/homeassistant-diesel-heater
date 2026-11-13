"""HeaterCC initialization follows the apps without requiring an initial reply."""

import asyncio
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.diesel_heater import coordinator as source
from custom_components.diesel_heater.hcalory import HcaloryVariant
from tests.test_abba_fff0_probe import candidate
from tests.test_audit_repairs import abba_status
from tests.test_pr_readiness_review import hcalory_status


def controller(hint=False):
    h, client = candidate("Heater5798")
    if not hint:
        h._hcalory_variant = None
    h._last_update_time = h._last_save_time = time.time()
    h._internal_recovery_threshold = 999
    h._auto_offset_unsub = None
    # Issue165's FFF1 is writable as well as notifying; FFF2 supports both
    # write types. Exercise that exact layout rather than write-only mocks.
    client.services[0].characteristics[0].properties = [
        "read", "write-without-response", "write", "notify"
    ]
    client.services[0].characteristics[1].properties = [
        "write-without-response", "write"
    ]
    client.stop_notify = AsyncMock()
    return h, client


@pytest.mark.asyncio
@pytest.mark.parametrize("hint", [False, True])
async def test_controller_silent_until_app_initialization_loads_without_user_intervention(hint):
    h, client = controller(hint)
    initialized = False
    packets = []

    async def write(char, packet, response):
        nonlocal initialized
        assert client.start_notify.await_count
        packets.append(bytes(packet))
        if packet[:4] == bytes.fromhex("baab05ea"):
            assert packet.hex() == "baab05ea0d0e0f007e"
            initialized = True
        if initialized and packet[:4] == bytes.fromhex("baab04cc"):
            h._notification_callback(0, abba_status(unit=0, target=20))

    client.write_gatt_char = AsyncMock(side_effect=write)
    with (
        patch.object(source, "establish_connection", AsyncMock(return_value=client)),
        patch.object(source.asyncio, "sleep", AsyncMock()),
        patch.object(source.dt_util, "now", return_value=datetime(2026, 11, 8, 13, 14, 15, tzinfo=UTC)),
    ):
        data = await h._async_update_data()
    assert data["connected"]
    assert h.protocol_mode == 5
    assert h._time_synced_this_connection
    assert data["set_temp"] == 20
    assert sum(p[:4] == bytes.fromhex("baab05ea") for p in packets) == 1
    if not hint:
        assert packets[0][:4] == bytes.fromhex("baab05ea")
    else:
        assert packets[0][:4] == bytes.fromhex("baab04cc")
        assert any(p[:2] == bytes((0, 2)) for p in packets)  # Native MVP1 read before alternate init.


@pytest.mark.asyncio
async def test_confirmed_hcalory_candidate_never_receives_abba_clock_packet():
    h, client = controller(True)
    packets = []

    async def write(char, packet, response):
        packets.append(bytes(packet))
        if packet[:2] == bytes((0, 2)):
            h._notification_callback(0, hcalory_status(0, 0))

    client.write_gatt_char = AsyncMock(side_effect=write)
    with (
        patch.object(source, "establish_connection", AsyncMock(return_value=client)),
        patch.object(source.asyncio, "sleep", AsyncMock()),
    ):
        await h._ensure_connected()
    assert h.protocol_mode == 7
    assert not any(p[:4] == bytes.fromhex("baab05ea") for p in packets)


@pytest.mark.asyncio
async def test_no_reply_never_claims_clock_or_protocol_validation():
    h, client = controller()
    client.write_gatt_char = AsyncMock()
    with (
        patch.object(source, "establish_connection", AsyncMock(return_value=client)),
        patch.object(source.asyncio, "sleep", AsyncMock()),
    ):
        data = await h._async_update_data()
    assert not data["connected"]
    assert not h._time_synced_this_connection


@pytest.mark.asyncio
async def test_late_first_status_retries_clock_on_existing_connection():
    h, client = controller()
    client.write_gatt_char = AsyncMock()
    with (
        patch.object(source, "establish_connection", AsyncMock(return_value=client)),
        patch.object(source.asyncio, "sleep", AsyncMock()),
    ):
        await h._ensure_connected()
        assert not h._time_synced_this_connection
        h._notification_callback(0, abba_status(unit=0, target=20))

        async def reply(char, packet, response):
            if packet[:4] == bytes.fromhex("baab04cc"):
                h._notification_callback(0, abba_status(unit=0, target=20))

        client.write_gatt_char.side_effect = reply
        client.write_gatt_char.reset_mock()
        await h._async_update_data()
        assert h._time_synced_this_connection
        packets = [call.args[1] for call in client.write_gatt_char.await_args_list]
        assert sum(p[:4] == bytes.fromhex("baab05ea") for p in packets) == 1
        await h._async_update_data()
        packets = [call.args[1] for call in client.write_gatt_char.await_args_list]
        assert sum(p[:4] == bytes.fromhex("baab05ea") for p in packets) == 1


@pytest.mark.asyncio
async def test_cancelled_initialization_cleans_up_without_marking_synced():
    h, client = controller()
    h._client = client
    h._characteristic = client.services[0].characteristics[0]
    h._abba_write_char = client.services[0].characteristics[1]
    h._is_abba_device = True
    h._active_char_uuid = source.ABBA_NOTIFY_UUID
    entered = asyncio.Event()

    async def write(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    client.write_gatt_char = AsyncMock(side_effect=write)
    task = asyncio.create_task(h._initialize_abba_session())
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    client.stop_notify.assert_awaited_once()
    client.disconnect.assert_awaited_once()
    assert h._client is None
    assert not h._time_synced_this_connection


@pytest.mark.asyncio
async def test_reconnect_reinitializes_but_ordinary_poll_does_not():
    h, client = controller()
    packets = []

    async def write(char, packet, response):
        packets.append(bytes(packet))
        if packet[:4] == bytes.fromhex("baab04cc"):
            h._notification_callback(0, abba_status(unit=0, target=20))

    client.write_gatt_char = AsyncMock(side_effect=write)

    async def connect(*args, **kwargs):
        client.is_connected = True
        return client

    with (
        patch.object(source, "establish_connection", AsyncMock(side_effect=connect)),
        patch.object(source.asyncio, "sleep", AsyncMock()),
    ):
        await h._async_update_data()
        await h._async_update_data()
        assert sum(p[:4] == bytes.fromhex("baab05ea") for p in packets) == 1
        await h._cleanup_connection()
        await h._async_update_data()
        assert sum(p[:4] == bytes.fromhex("baab05ea") for p in packets) == 2


@pytest.mark.asyncio
async def test_nonstatus_reply_during_startup_never_marks_clock_synced():
    h, client = controller()

    async def write(*args, **kwargs):
        frame = bytearray(40)
        frame[:4] = bytes.fromhex("abba24ec")
        h._notification_callback(0, frame)

    client.write_gatt_char = AsyncMock(side_effect=write)
    with (
        patch.object(source, "establish_connection", AsyncMock(return_value=client)),
        patch.object(source.asyncio, "sleep", AsyncMock()),
    ):
        await h._ensure_connected()
    assert not h.data["connected"]
    assert not h._time_synced_this_connection


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", [v for v in HcaloryVariant if v is not HcaloryVariant.MVP1])
async def test_versioned_hcalory_variants_keep_native_startup(variant):
    h, client = controller()
    h._hcalory_variant = variant
    h._initialize_abba_session = AsyncMock(side_effect=AssertionError("Unexpected ABBA initialization"))
    h._async_password_handshake = AsyncMock(return_value=True)
    h._send_wake_up_ping = AsyncMock()
    with (
        patch.object(source, "establish_connection", AsyncMock(return_value=client)),
        patch.object(source.asyncio, "sleep", AsyncMock()),
    ):
        await h._ensure_connected()
    assert h.protocol_mode == 7
    h._initialize_abba_session.assert_not_awaited()
    h._async_password_handshake.assert_awaited_once()
    h._send_wake_up_ping.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("first_write_fails", [False, True])
async def test_unanswered_initialization_retries_without_telemetry(first_write_fails):
    h, client = controller()
    clocks = 0
    queries = []

    async def write(char, packet, response):
        nonlocal clocks
        if packet[:4] == bytes.fromhex("baab05ea"):
            clocks += 1
            if clocks == 1 and first_write_fails:
                raise source.BleakError("Initial write failed")
        elif packet[:4] == bytes.fromhex("baab04cc"):
            queries.append(clocks)
            if clocks >= 2:
                h._notification_callback(0, abba_status(unit=0, target=20))

    client.write_gatt_char = AsyncMock(side_effect=write)
    with (
        patch.object(source, "establish_connection", AsyncMock(return_value=client)),
        patch.object(source.asyncio, "sleep", AsyncMock()),
    ):
        first = await h._async_update_data()
        assert not first["connected"]
        assert not h._time_synced_this_connection
        queries.clear()
        second = await h._async_update_data()
        assert second["connected"]
        assert h._time_synced_this_connection
        assert queries == [2]  # The initialization status needs no duplicate poll.
        await h._async_update_data()
        assert clocks == 2  # Validated sessions stop retrying initialization.
