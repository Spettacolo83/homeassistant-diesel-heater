"""Full production methods retain protocol-owned persistent BLE sessions."""

import ast
import asyncio
import inspect
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.diesel_heater import coordinator as source
from custom_components.diesel_heater.ble_operation import BleOperationScheduler, ble_transaction
from diesel_heater_ble import ProtocolHcalory

from .test_coordinator import create_mock_coordinator


def heater(scheduler=None):
    h = create_mock_coordinator()
    if scheduler is not None:
        h._ble_scheduler = scheduler
    h._last_update_time = h._last_save_time = time.time()
    return h


def client_for(service_uuid, *characteristics):
    return SimpleNamespace(
        is_connected=True,
        services=[SimpleNamespace(uuid=service_uuid, characteristics=list(characteristics))],
        start_notify=AsyncMock(),
        disconnect=AsyncMock(),
    )


def characteristic(uuid, *properties):
    return SimpleNamespace(uuid=uuid, properties=list(properties))


@pytest.mark.asyncio
async def test_heatgenie_second_and_third_poll_use_passive_f2_without_reconnect():
    h = heater()
    h._protocol_mode = 8
    h._is_heatgenie_device = True
    h._protocol = h._protocols[8]
    client = SimpleNamespace(is_connected=True)

    async def connect():
        h._client = client

    h._ensure_connected = AsyncMock(side_effect=connect)
    h._send_command = AsyncMock(return_value=True)
    h._cleanup_connection = AsyncMock()
    await h._async_update_data()
    for state, expected_running in [(1, 1), (4, 0)]:
        h._heatgenie_last_status_at = 0
        poll = asyncio.create_task(h._async_update_data())
        await asyncio.sleep(0)
        assert not poll.done()  # Actual passive wait has no recent report.
        frame = bytearray(50)
        frame[0], frame[1], frame[7], frame[8] = 0xAA, 9, 0xF2, state
        frame[-2:] = h._protocol.crc16(frame[:-2]).to_bytes(2, "big")
        h._notification_callback(0, frame)
        await asyncio.wait_for(poll, 1)
        assert h.data["running_state"] == expected_running
        assert h._heatgenie_status_event.is_set()
    h._ensure_connected.assert_awaited_once()
    assert h._send_command.await_count == 2  # Initial status + app clock only.
    assert h._client is client
    h._cleanup_connection.assert_not_awaited()


@pytest.mark.asyncio
async def test_hcalory_authentication_and_notifications_survive_multiple_polls():
    h = heater()
    h._protocols[7] = ProtocolHcalory()
    c = client_for(
        source.HCALORY_MVP2_SERVICE_UUID,
        characteristic(source.HCALORY_MVP2_NOTIFY_UUID, "notify"),
        characteristic(source.HCALORY_MVP2_WRITE_UUID, "write"),
    )
    h._async_password_handshake = AsyncMock(return_value=True)
    h._send_wake_up_ping = AsyncMock()
    h._send_command = AsyncMock(return_value=True)
    with patch.object(source, "establish_connection", AsyncMock(return_value=c)) as connect:
        for _ in range(3):
            await h._async_update_data()
    connect.assert_awaited_once()
    h._async_password_handshake.assert_awaited_once()
    c.start_notify.assert_awaited_once()
    c.disconnect.assert_not_awaited()
    assert h._client is c


@pytest.mark.asyncio
async def test_warm_drive_startup_reads_and_configuration_cache_survive_polls():
    h = heater()
    h._ble_device.name = "Air Heater"
    c = client_for(
        source.ABBA_SERVICE_UUID,
        characteristic(source.DZ06_NEO_WRITE_UUID, "write"),
        characteristic(source.DZ06_NEO_NOTIFY_UUID, "notify"),
    )
    config = bytearray(range(20))

    async def read_config():
        h._warm_drive_board_config = config
        return True

    h._send_dz06_neo_run_settings = AsyncMock(return_value=True)
    h._send_dz06_neo_configuration = AsyncMock(side_effect=read_config)
    h._send_dz06_neo_board_info = AsyncMock()
    h._send_command = AsyncMock(return_value=True)
    with patch.object(source, "establish_connection", AsyncMock(return_value=c)) as connect:
        for _ in range(3):
            await h._async_update_data()
    connect.assert_awaited_once()
    h._send_dz06_neo_run_settings.assert_awaited_once()
    h._send_dz06_neo_configuration.assert_awaited_once()
    assert h._warm_drive_board_config is config
    c.disconnect.assert_not_awaited()
    assert h._client is c


@pytest.mark.asyncio
async def test_cbff_recovery_retains_separate_connect_and_query_deadlines():
    h = heater()
    h._protocol_mode = 6
    h._client = SimpleNamespace(is_connected=True)
    h._send_command_unlocked = AsyncMock(side_effect=[False, False, False, True])
    h._ensure_connected = AsyncMock()
    h._cleanup_connection = AsyncMock()
    h._send_v21_time_sync = AsyncMock(return_value=True)
    deadlines = []

    @asynccontextmanager
    async def timeout(seconds):
        deadlines.append(seconds)
        yield

    with patch.object(source.asyncio, "timeout", timeout), patch.object(source.asyncio, "sleep", AsyncMock()):
        await asyncio.wait_for(h._async_update_data(), 1)
    assert deadlines == [15.0, 15.0, 15.0, 20.0, 15.0]
    h._cleanup_connection.assert_awaited_once()
    h._ensure_connected.assert_awaited_once()
    assert h._consecutive_failures == 0


def test_all_async_methods_are_full_production_coroutines():
    tree = ast.parse(Path(source.__file__).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "VevorHeaterCoordinator")
    for method in cls.body:
        if isinstance(method, ast.AsyncFunctionDef):
            assert inspect.iscoroutinefunction(getattr(source.VevorHeaterCoordinator, method.name)), method.name


@pytest.mark.asyncio
async def test_fifo_priority_and_bounded_poll_fairness_do_not_touch_connections():
    scheduler = BleOperationScheduler()
    order = []
    participants = [SimpleNamespace(_client=object()) for _ in range(7)]
    originals = [p._client for p in participants]

    async def job(i, poll=False):
        async with scheduler.operation(participants[i], poll=poll):
            order.append(i)
            await asyncio.sleep(0)

    async with scheduler.operation(participants[0]):
        jobs = [asyncio.create_task(job(1, poll=True))]
        jobs += [asyncio.create_task(job(i)) for i in range(2, 7)]
        await asyncio.sleep(0)
    await asyncio.gather(*jobs)
    assert order == [2, 3, 1, 4, 5, 6]  # Owning control already counts as one.
    assert [p._client for p in participants] == originals


@pytest.mark.asyncio
async def test_cancelled_waiter_and_owner_release_without_connection_side_effects():
    scheduler = BleOperationScheduler()
    a, b = object(), object()
    async with scheduler.operation(a):
        waiter = asyncio.create_task(scheduled_wait(scheduler, b))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert scheduler.owned_by(a)
    entered = asyncio.Event()

    async def owner():
        async with scheduler.operation(b):
            entered.set()
            await asyncio.sleep(60)

    task = asyncio.create_task(owner())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert scheduler.owner is None
    assert not scheduler._pending


async def scheduled_wait(scheduler, participant):
    async with scheduler.operation(participant):
        pass


@pytest.mark.asyncio
async def test_same_task_reentry_and_callback_task_independent_ownership():
    scheduler = BleOperationScheduler()
    h = object()
    async with scheduler.operation(h):
        async with scheduler.operation(h):
            assert scheduler.owned_by(h)
        task = asyncio.create_task(scheduled_wait(scheduler, h))
        await asyncio.sleep(0)
        assert not task.done()
    await task


@pytest.mark.asyncio
async def test_cross_task_coordinator_refresh_runs_after_operation_release():
    h = heater()
    h.async_request_refresh = source.VevorHeaterCoordinator.async_request_refresh.__get__(h)
    h._async_update_data = AsyncMock(return_value={})
    tasks = []
    h.hass.async_create_task = lambda coro: tasks.append(asyncio.create_task(coro))

    async def base_refresh(host):
        await asyncio.create_task(host._async_update_data())

    @ble_transaction
    async def command(host):
        await host.async_request_refresh()
        host._async_update_data.assert_not_awaited()

    with patch.object(source.VevorHeaterCoordinator.__bases__[0], "async_request_refresh", base_refresh):
        await asyncio.wait_for(command(h), 1)
        await asyncio.wait_for(asyncio.gather(*tasks), 1)
    h._async_update_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_recovery_and_shutdown_wait_for_operation_without_connecting():
    scheduler = BleOperationScheduler()
    blocker, h = heater(scheduler), heater(scheduler)
    h._ensure_connected = AsyncMock()
    h._cleanup_connection = AsyncMock()
    h._auto_offset_unsub = None
    async with scheduler.operation(blocker):
        task = asyncio.create_task(h.async_shutdown())
        await asyncio.sleep(0)
        assert not task.done()
        h._cleanup_connection.assert_not_awaited()
    await task
    h._cleanup_connection.assert_awaited_once()
    h._ensure_connected.assert_not_awaited()
    # Recovery keeps the original adapter logic, entered only after scheduling.
    with patch.dict(
        "sys.modules",
        {
            "bluetooth_adapters": SimpleNamespace(
                get_adapters=lambda: SimpleNamespace(refresh=AsyncMock(), adapters={})
            ),
            "bluetooth_auto_recovery": SimpleNamespace(recover_adapter=AsyncMock()),
        },
    ):
        h._resolve_local_hci_for_heater = lambda adapters: None
        async with scheduler.operation(blocker):
            task = asyncio.create_task(h._async_recover_internally())
            await asyncio.sleep(0)
            assert not task.done()
        assert await task is False
    h._ensure_connected.assert_not_awaited()


@pytest.mark.asyncio
async def test_burnoff_restore_and_off_are_atomic_after_burnoff_lock():
    from custom_components.diesel_heater.burnoff import BurnoffController

    h = heater()
    order = []

    class Burn:
        _host = h
        lock = asyncio.Lock()
        active = True
        cycle = SimpleNamespace(shutdown_after=True)

        def ecu_shutdown_observed(self):
            return False

        def ecu_can_restore(self):
            return True

        def reset_accumulator(self):
            pass

        async def restore_saved_mode(self):
            assert self.lock.locked()
            assert h._ble_scheduler.owned_by(h)
            order.append("restore")
            await asyncio.sleep(0.01)
            return True

        async def clear_state(self):
            pass

    async def off():
        assert h._ble_scheduler.owned_by(h)
        order.append("off")

    h._power_off = off
    burn = Burn()
    task = asyncio.create_task(BurnoffController.complete(burn))
    await asyncio.sleep(0)

    async def control():
        async with h.ble_operation():
            order.append("control")

    await asyncio.gather(task, control())
    assert order == ["restore", "off", "control"]
