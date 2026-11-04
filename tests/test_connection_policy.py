"""Experimental AA66-only release policy, exercising full production methods."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.diesel_heater.ble_operation import transaction_context
from custom_components.diesel_heater.const import CONF_CONNECTION_POLICY, CONNECTION_RELEASE

from .test_ble_operations import heater


def releasing_heater(mode=4):
    h = heater()
    h._protocol_mode = mode
    h.config_entry.data[CONF_CONNECTION_POLICY] = CONNECTION_RELEASE
    h._stopping = False
    h._ble_release_pending = False
    h._active_char_uuid = "aa66-notify"
    c = SimpleNamespace(is_connected=True, stop_notify=AsyncMock())

    async def disconnect():
        c.is_connected = False

    c.disconnect = AsyncMock(side_effect=disconnect)
    h._client = c
    return h, c


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [0, 1, 2, 3, 5, 6, 7, 8, 9])
async def test_unsupported_protocol_never_releases_even_with_stored_option(mode):
    h, c = releasing_heater(mode)
    await h._finish_ble_operation()
    c.disconnect.assert_not_awaited()
    assert h._client is c


@pytest.mark.asyncio
async def test_default_persistent_even_for_aa66_encrypted():
    h, c = releasing_heater()
    h.config_entry.data.pop(CONF_CONNECTION_POLICY)
    await h._finish_ble_operation()
    c.disconnect.assert_not_awaited()


@pytest.mark.asyncio
async def test_idle_release_retains_validated_status_and_clock():
    h, c = releasing_heater()
    h.data.update(connected=True, current_temp=21, running_state=1)
    before = dict(h.data)
    h._time_synced_this_connection = True
    await h._finish_ble_operation()
    assert h._client is None
    assert h.data == before
    assert h._time_synced_this_connection
    assert h.update_interval.total_seconds() == 60
    c.stop_notify.assert_awaited_once()
    c.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_nested_writes_have_one_release_after_all_writes():
    h, c = releasing_heater()
    h._ensure_connected_with_timeout = AsyncMock()
    h._send_command = AsyncMock(return_value=True)
    async with h.ble_operation():
        async with h.ble_operation():
            c.disconnect.assert_not_awaited()
        c.disconnect.assert_not_awaited()
    c.disconnect.assert_awaited_once()
    h._send_command.assert_awaited_once_with(1, 0)


@pytest.mark.asyncio
async def test_new_control_requires_reconnect_and_fresh_status_before_write():
    h, c = releasing_heater()
    h._client = None
    order = []

    async def connect():
        order.append("connect")
        c.is_connected = True
        h._client = c

    async def send(command, argument):
        order.append((command, argument))
        return True

    h._ensure_connected_with_timeout = AsyncMock(side_effect=connect)
    h._send_command = AsyncMock(side_effect=send)
    h._refresh_after_control_command = AsyncMock()
    h._burnoff.cancel = AsyncMock()
    await h.async_turn_on()
    assert order == ["connect", (1, 0), (3, 1)]
    c.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_control_refused_without_fresh_status():
    h, c = releasing_heater()
    h._time_synced_this_connection = True
    h._ensure_connected_with_timeout = AsyncMock()
    h._send_command = AsyncMock(return_value=False)
    with pytest.raises(Exception, match="fresh status"):
        await h._async_turn_on_scheduled()
    h._send_command.assert_awaited_once_with(1, 0)
    assert not h._time_synced_this_connection
    # A failed entry must still release a transport opened during preparation.
    assert h._client is None


@pytest.mark.asyncio
async def test_unconfirmed_disconnect_retains_client_and_prevents_new_connection():
    h, c = releasing_heater()
    c.disconnect = AsyncMock()  # Returns but transport still reports connected.
    with pytest.raises(Exception, match="did not release"):
        await h._finish_ble_operation()
    assert h._client is c
    assert h._ble_release_pending
    h._ensure_connected_with_timeout = AsyncMock()
    with pytest.raises(Exception, match="did not release"):
        await h._prepare_ble_operation("async_set_level")
    h._ensure_connected_with_timeout.assert_not_awaited()
    assert h._client is c


@pytest.mark.asyncio
async def test_cancellation_waits_for_bounded_disconnect_before_unlock():
    h, c = releasing_heater()
    started, finish = asyncio.Event(), asyncio.Event()

    async def disconnect():
        started.set()
        await finish.wait()
        c.is_connected = False

    c.disconnect.side_effect = disconnect
    task = asyncio.create_task(h._release_ble_connection())
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    assert h._client is c
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert h._client is None


@pytest.mark.asyncio
async def test_failed_poll_is_not_converted_into_success_by_release():
    h, c = releasing_heater()
    h._send_command = AsyncMock(return_value=False)
    h._consecutive_failures = h._max_stale_cycles
    h._handle_connection_failure = lambda err: setattr(h, "_consecutive_failures", h._consecutive_failures + 1)
    with pytest.raises(Exception, match="No status"):
        await h._async_update_data()
    assert h._client is None


@pytest.mark.asyncio
async def test_repeated_cancel_does_not_unlock_before_disconnect_finishes():
    h, c = releasing_heater()
    started, finish = asyncio.Event(), asyncio.Event()

    async def disconnect():
        started.set()
        await finish.wait()
        c.is_connected = False

    c.disconnect.side_effect = disconnect

    async def operation():
        async with transaction_context(h, "maintenance"):
            pass

    task = asyncio.create_task(operation())
    await started.wait()
    for _ in range(3):
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert h._ble_operation_lock.owner is task
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert h._ble_operation_lock.owner is None
    assert h._client is None


@pytest.mark.asyncio
async def test_disconnect_timeout_retains_handle_until_retry_confirms_release():
    from unittest.mock import patch

    from custom_components.diesel_heater import coordinator as source

    h, c = releasing_heater()

    async def hanging_disconnect():
        await asyncio.sleep(1)

    c.disconnect.side_effect = hanging_disconnect
    timeout = asyncio.timeout
    with patch.object(source.asyncio, "timeout", lambda duration: timeout(0.01)), pytest.raises(TimeoutError):
        await h._release_ble_connection()
    assert h._client is c
    assert h._ble_release_pending

    async def disconnected():
        c.is_connected = False

    c.disconnect.side_effect = disconnected
    await h._release_ble_connection()
    assert h._client is None
    assert not h._ble_release_pending


@pytest.mark.asyncio
async def test_clock_is_preserved_only_for_intentional_release():
    h, _ = releasing_heater()
    h._time_synced_this_connection = True
    await h._release_ble_connection()
    assert h._time_synced_this_connection
    h._handle_connection_failure(Exception("no fresh status"))
    assert not h._time_synced_this_connection


@pytest.mark.asyncio
async def test_options_default_roundtrip_survives_new_coordinator_policy_read():
    from custom_components.diesel_heater.const import CONNECTION_PERSISTENT

    from .test_config_flow import TestOptionsFlow

    flow = TestOptionsFlow()._create_flow()
    form = await flow.async_step_init()
    field = next(k for k in form["data_schema"].schema if k.schema == CONF_CONNECTION_POLICY)
    assert field.default() == CONNECTION_PERSISTENT
    await flow.async_step_init({CONF_CONNECTION_POLICY: CONNECTION_RELEASE})
    updated = flow.hass.config_entries.async_update_entry.call_args.kwargs["data"]
    h = heater()
    h.config_entry.data = updated
    h._protocol_mode = 4
    assert h.release_between_polls
    h._protocol_mode = 8
    assert not h.release_between_polls


@pytest.mark.asyncio
async def test_multiple_short_polls_do_not_repeat_native_clock_write():
    h, _ = releasing_heater()
    h._client = None
    h._time_synced_this_connection = False
    clients = []

    async def connect():
        _, c = releasing_heater()
        h._client = c
        clients.append(c)

    h._ensure_connected = AsyncMock(side_effect=connect)
    h._send_command = AsyncMock(return_value=True)
    for _ in range(3):
        await h._async_update_data()
    assert h._ensure_connected.await_count == 3
    assert h._send_command.await_count == 4  # Three fresh polls + one native clock write.
    assert h._time_synced_this_connection
    assert h.data["connected"]
    assert h._consecutive_failures == 0
    assert h._client is None
    for c in clients:
        c.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_cancels_owned_lock_waiter_before_waiting_for_lock():
    h = heater()
    h._auto_offset_unsub = None
    h._cleanup_connection = AsyncMock()
    cancelled = asyncio.Event()

    async def waiting_writer():
        try:
            async with h.ble_operation():
                raise AssertionError("Unloaded writer must not execute")
        finally:
            cancelled.set()

    h.hass.async_create_task = asyncio.create_task
    async with h.ble_operation():
        writer = h.create_background_task(waiting_writer())
        await asyncio.sleep(0)
        shutdown = asyncio.create_task(h.async_shutdown())
        await asyncio.wait_for(cancelled.wait(), 0.5)
        assert writer.cancelled()
        assert not shutdown.done()  # Final cleanup waits, cancellation did not.
    await asyncio.wait_for(shutdown, 0.5)
    h._cleanup_connection.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("unexpected_disconnect", [False, True])
async def test_actual_connect_preserves_clock_only_after_intentional_idle_release(unexpected_disconnect):
    from unittest.mock import patch

    from custom_components.diesel_heater import coordinator as source

    from .test_ble_operations import characteristic, client_for

    h, old = releasing_heater()
    h._time_synced_this_connection = True
    if unexpected_disconnect:
        old.is_connected = False
    else:
        await h._release_ble_connection()
    new = client_for(source.SERVICE_UUID, characteristic(source.CHARACTERISTIC_UUID, "notify", "write"))
    h._send_wake_up_ping = AsyncMock()
    with patch.object(source, "establish_connection", AsyncMock(return_value=new)):
        await h._ensure_connected()
    assert h._time_synced_this_connection is not unexpected_disconnect
    assert h._client is new
    new.start_notify.assert_awaited_once()
