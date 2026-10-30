"""Exercise the real broker and full imported production coordinator with fake BLE."""

import ast
import asyncio
import inspect
import logging
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.diesel_heater import ble_session as module
from custom_components.diesel_heater import ble_transaction as transaction_module
from custom_components.diesel_heater.burnoff import BurnoffController
from custom_components.diesel_heater.coordinator import VevorHeaterCoordinator as Actual

Broker = module.BleSessionBroker
transaction = transaction_module.ble_transaction
ROOT = Path(__file__).resolve().parents[1] / "custom_components/diesel_heater"
cls = next(
    n
    for n in ast.parse((ROOT / "coordinator.py").read_text()).body
    if isinstance(n, ast.ClassDef) and n.name == "VevorHeaterCoordinator"
)


class Client:
    is_connected = True


class Fake(Actual):
    is_dz06_neo = False
    is_warm_drive = False

    def _should_auto_recover(self):
        return False

    async def _finish_ble_session(self):
        await Actual._finish_ble_session(self)

    active = 0
    peak = 0

    def __init__(self, broker, name="heater"):
        self._ble_broker = broker
        self.name = name
        self._client = None
        self._v21_handshake_task = None
        self._ble_refresh_pending = False
        self._logger = logging.getLogger("test")
        self.hass = type(
            "HA", (), {"async_create_task": lambda _, task: self.tasks.append(asyncio.create_task(task))}
        )()
        self.tasks = []
        self.events = []
        self.connected = 0
        self.cleanups = 0
        self.fail_connect = False
        self.fail_cleanup = False
        self.self_cancel_cleanup = False
        self._last_auto_time_sync_date = datetime.now().date()
        self._is_cronus_device = False
        self._is_heatgenie_device = False
        self._heatgenie_lock = asyncio.Lock()
        self._feaa_lock = asyncio.Lock()
        self._time_synced_this_connection = True
        self._protocol_mode = 4
        self._protocol = None
        self._characteristic = object()
        self._passkey = 1234
        self._notification_data = None
        self._consecutive_failures = 0
        self._max_stale_cycles = 3
        self._VOLATILE_FIELDS = ("temperature",)
        self._last_valid_data = {"temperature": 20}
        self.data = {"temperature": 20, "connected": True}

    async def _check_daily_reset(self):
        self.events.append("daily_reset")

    async def _check_daily_runtime_reset(self):
        self.events.append("runtime_reset")

    def ble_session(self):
        return transaction_module.transaction_context(self)

    async def _ensure_connected(self):
        if self._client:
            return
        if self.fail_connect:
            raise OSError("unavailable")
        self._client = Client()
        self.connected += 1
        Fake.active += 1
        Fake.peak = max(Fake.active, Fake.peak)

    async def _cleanup_connection(self):
        self.cleanups += 1
        await asyncio.sleep(0)
        if self.self_cancel_cleanup:
            raise asyncio.CancelledError()
        if self.fail_cleanup:
            raise OSError("proxy still connected")
        if self._client:
            Fake.active -= 1
            self._client = None

    async def _async_update_data_connected(self, **kwargs):
        self.events.append("read")
        return self.data

    def _build_command_packet(self, command, argument):
        return bytes((command, argument))

    async def _write_gatt(self, packet):
        assert self._client and self._client.is_connected
        self.events.append(("write", tuple(packet)))
        self._notification_data = b"ok"

    async def _refresh_after_control_command(self):
        await self.async_request_refresh()


class Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        Fake.active = Fake.peak = 0
        self.broker = Broker()

    def test_full_production_class_retains_all_async_methods(self):
        # Execute the ENTIRE class body, including helpers, in source order.
        # This catches a method shadowing the imported transaction decorator.
        for method in cls.body:
            if isinstance(method, ast.AsyncFunctionDef):
                self.assertTrue(inspect.iscoroutinefunction(getattr(Actual, method.name)), method.name)
        self.assertFalse(inspect.iscoroutinefunction(Actual.ble_session))

    async def test_four_poll_fifo_and_single_connection(self):
        heaters = [Fake(self.broker, str(i)) for i in range(4)]
        order = []

        async def poll(h):
            async with self.broker.session(h, poll=True):
                order.append(h.name)
                await asyncio.sleep(0.01)

        await asyncio.gather(*(poll(h) for h in heaters))
        self.assertEqual(order, ["0", "1", "2", "3"])
        self.assertEqual(Fake.peak, 1)
        self.assertEqual(Fake.active, 0)
        self.assertTrue(all(h.cleanups == 1 for h in heaters))

    async def test_command_priority_and_bounded_poll_fairness(self):
        blocker = Fake(self.broker)
        order = []

        async def job(name, poll):
            h = Fake(self.broker, name)
            async with self.broker.session(h, poll=poll):
                order.append(name)

        async with self.broker.session(blocker, poll=True):
            jobs = [asyncio.create_task(job("poll", True))]
            jobs += [asyncio.create_task(job(str(i), False)) for i in range(5)]
            await asyncio.sleep(0)
        await asyncio.gather(*jobs)
        self.assertEqual(order, ["0", "1", "2", "poll", "3", "4"])
        self.assertEqual(Fake.peak, 1)

    async def test_cancel_waiter_and_active_owner_cleanup(self):
        first, second = Fake(self.broker), Fake(self.broker)
        async with self.broker.session(first):
            waiter = asyncio.create_task(second._async_update_data())
            await asyncio.sleep(0)
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
        self.assertEqual(second.connected, 0)
        entered = asyncio.Event()

        async def active():
            async with self.broker.session(second):
                entered.set()
                await asyncio.sleep(60)

        task = asyncio.create_task(active())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(Fake.active, 0)
        self.assertIsNone(self.broker.owner)
        self.assertFalse(self.broker._pending)

    async def test_disconnect_failure_quarantines_and_retries_before_new_connect(self):
        a, b = Fake(self.broker), Fake(self.broker)
        a.fail_cleanup = True
        async with self.broker.session(a):
            pass
        with self.assertRaises(OSError):
            async with self.broker.session(b):
                pass
        self.assertEqual(b.connected, 0)
        a.fail_cleanup = False
        async with self.broker.session(b):
            pass
        self.assertEqual(Fake.peak, 1)
        self.assertEqual(Fake.active, 0)

    async def test_self_cancelled_cleanup_also_quarantines(self):
        a, b = Fake(self.broker), Fake(self.broker)
        a.self_cancel_cleanup = True
        async with self.broker.session(a):
            pass
        self.assertIs(self.broker._blocked, a)
        with self.assertRaises(asyncio.CancelledError):
            async with self.broker.session(b):
                pass
        self.assertEqual(b.connected, 0)
        a.self_cancel_cleanup = False
        async with self.broker.session(b):
            pass
        self.assertEqual(Fake.peak, 1)

    async def test_actual_full_status_poll_requires_followup_status_command(self):
        h = Fake(self.broker)
        h._async_update_data_connected = Actual._async_update_data_connected.__get__(h)
        h._last_update_time = h._last_save_time = time.time()
        h._update_fuel_tracking = lambda elapsed: None
        h._update_runtime_tracking = lambda elapsed: None
        h._consecutive_failures = 1
        await h._async_update_data()
        self.assertIn(("write", (1, 0)), h.events)
        self.assertEqual(h._consecutive_failures, 0)
        self.assertIsNotNone(h._last_successful_read)
        self.assertIn("last_successful_read", h.data)
        self.assertEqual(h._last_valid_data, {"temperature": 20})
        self.assertIsNone(h._client)

    async def test_actual_send_command_reconnects_and_disconnects(self):
        h = Fake(self.broker)
        self.assertTrue(await h._send_command(4, 2))
        self.assertEqual(h.connected, 1)
        self.assertEqual(h.events, [("write", (4, 2))])
        self.assertIsNone(h._client)

    async def test_actual_cross_task_refresh_is_deferred_and_no_deadlock(self):
        h = Fake(self.broker)

        @transaction
        async def command(host):
            await host._send_command(4, 2)
            await host.async_request_refresh()
            self.assertEqual(host.events, [("write", (4, 2))])

        async def cross_task_refresh(host):
            await asyncio.create_task(host._async_update_data())

        with patch.object(Actual.__bases__[0], "async_request_refresh", cross_task_refresh):
            await asyncio.wait_for(command(h), 1)
            await asyncio.wait_for(asyncio.gather(*h.tasks), 1)
        self.assertEqual(h.events, [("write", (4, 2)), "daily_reset", "runtime_reset", "read"])
        self.assertEqual(Fake.peak, 1)

    async def test_actual_burnoff_restore_mode_target_is_atomic(self):
        h, other = Fake(self.broker), Fake(self.broker)
        h._burnoff = type("Burnoff", (), {"active": False})()

        # Real restore method calls the two public setters, each nested session.
        # Bound instance wrappers keep the same production transaction decorator.
        async def set_mode(value):
            async with self.broker.session(h):
                await h._send_command(2, value)
                await h.async_request_refresh()
                await asyncio.sleep(0.01)
                return True

        async def set_level(value):
            return await h._send_command(4, value)

        h.async_set_mode, h.async_set_level = set_mode, set_level
        cycle = type("Cycle", (), {"saved_mode": 1, "saved_level": 7, "saved_temp": None, "saved_protocol_state": {}})()
        task = asyncio.create_task(h.async_restore_burnoff_snapshot(cycle))
        await asyncio.sleep(0.001)
        poll = asyncio.create_task(other._async_update_data())
        self.assertTrue(await asyncio.wait_for(task, 1))
        await asyncio.wait_for(poll, 1)
        await asyncio.gather(*h.tasks)
        self.assertEqual([e for e in h.events if isinstance(e, tuple)][:2], [("write", (2, 1)), ("write", (4, 7))])
        self.assertEqual(Fake.peak, 1)

    async def test_actual_burnoff_complete_restore_and_poweroff_share_lease(self):
        h = Fake(self.broker)
        writes = []

        class Burn:
            _host = h
            lock = asyncio.Lock()
            active = True
            cycle = type("Cycle", (), {"shutdown_after": True})()

            def ecu_shutdown_observed(self):
                return False

            def ecu_can_restore(self):
                return True

            def reset_accumulator(self):
                pass

            async def restore_saved_mode(self):
                writes.append("restore_mode")
                await asyncio.sleep(0.01)
                writes.append("restore_target")
                return True

            async def clear_state(self):
                pass

        async def off():
            self.assertTrue(self.broker.owned_by(h))
            writes.append("off")

        h._power_off = off
        burn = Burn()
        task = asyncio.create_task(BurnoffController.complete(burn))
        await asyncio.sleep(0.001)

        async def user():
            async with self.broker.session(h):
                writes.append("user")

        user_task = asyncio.create_task(user())
        await asyncio.wait_for(asyncio.gather(task, user_task), 1)
        self.assertEqual(writes, ["restore_mode", "restore_target", "off", "user"])

    async def test_actual_abba_power_guards_use_fresh_status_inside_lease(self):
        h = Fake(self.broker)
        h._protocol_mode = 5
        h.data.update(running_state=0, running_step=0)

        class Burn:
            ha_power_off = False

            async def cancel(_, **kwargs):
                self.assertFalse(self.broker.owned_by(h))

        h._burnoff = Burn()
        original = h._write_gatt

        async def write(packet):
            await original(packet)
            if packet[0] == 1:
                h.data["running_state"] = 1  # Physical heater already started.

        h._write_gatt = write
        await h.async_turn_on()
        self.assertEqual(h.events, [("write", (1, 0))])  # Never toggle it OFF.
        h.events.clear()

        async def off_write(packet):
            await original(packet)
            if packet[0] == 1:
                h.data["running_state"] = 0

        h._write_gatt = off_write
        h.data["running_state"] = 1  # Stale cache says running.
        await h._power_off()
        self.assertEqual(h.events, [("write", (1, 0))])  # Never toggle it ON.

    async def test_actual_delayed_v21_handshake_finishes_before_disconnect(self):
        h = Fake(self.broker)
        h._v21_handshake_sent = True
        async with self.broker.session(h):
            h._v21_handshake_task = asyncio.create_task(h._send_v21_handshake(b"handshake"))
        self.assertTrue(h._v21_handshake_sent)
        self.assertTrue(h._v21_handshake_task.done())
        self.assertEqual(h.events, [("write", tuple(b"handshake"))])
        self.assertIsNone(h._client)

    async def test_callback_task_does_not_inherit_owner(self):
        h = Fake(self.broker)
        async with self.broker.session(h):

            async def callback():
                self.assertFalse(self.broker.owned_by(h))
                await h._send_command(4, 2)

            task = asyncio.create_task(callback())
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertEqual(h.events, [])
        await task
        self.assertEqual(h.connected, 2)

    async def test_failed_scheduled_polls_keep_cache_then_unavailable(self):
        h = Fake(self.broker)
        h.fail_connect = True
        for _ in range(3):
            self.assertEqual((await h._async_update_data())["temperature"], 20)
            self.assertTrue(h.data["connected"])
        with self.assertRaises(UpdateFailed):
            await h._async_update_data()
        self.assertIsNone(h.data["temperature"])
        self.assertFalse(h.data["connected"])

    async def test_recovery_does_not_connect_failed_device_and_waits_for_owner(self):
        h, other = Fake(self.broker), Fake(self.broker)
        h.fail_connect = True
        called = []

        async def recovery():
            self.assertEqual(Fake.active, 0)
            called.append("recover")
            return True

        h._async_recover_internally_leased = recovery
        async with self.broker.session(other):
            task = asyncio.create_task(h._async_recover_internally())
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertEqual(called, [])
        self.assertTrue(await task)
        self.assertEqual(h.connected, 0)
        self.assertEqual(called, ["recover"])

    async def test_shutdown_cleanup_waits_for_active_transaction_without_reconnect(self):
        from unittest.mock import AsyncMock

        h = Fake(self.broker)
        h._burnoff = type("Burn", (), {"stop_wait_task": AsyncMock(), "stop_in_run_start_task": AsyncMock()})()
        h._auto_offset_unsub = None
        async with self.broker.session(h):
            task = asyncio.create_task(h.async_shutdown())
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertEqual(h.cleanups, 0)
        await task
        self.assertEqual(h.connected, 1)
        self.assertIsNone(h._client)
        self.assertEqual(Fake.active, 0)

    async def test_cronus_public_off_connects_before_record_write(self):
        from unittest.mock import AsyncMock

        from diesel_heater_ble import ProtocolCronus

        h = Fake(self.broker)
        h._protocol_mode = 9
        h._protocols = {9: ProtocolCronus()}
        h._cronus_transaction_lock = asyncio.Lock()
        h._cronus_write_event = asyncio.Event()

        async def write(packet):
            self.assertTrue(self.broker.owned_by(h))
            self.assertIsNotNone(h._client)
            h._cronus_write_succeeded = True
            h._cronus_write_event.set()

        h._write_gatt = write
        h.async_request_refresh = AsyncMock()
        await h.async_turn_off()
        self.assertEqual(h.connected, 1)
        self.assertIsNone(h._client)

    async def test_warm_drive_partial_write_uses_reconnected_configuration(self):
        from unittest.mock import AsyncMock

        from .test_dz06_neo import coordinator_for_layout

        h = coordinator_for_layout("air")
        h._ble_broker = self.broker
        fresh = bytearray(range(20))
        fresh[2:4] = bytes((0, 7))

        async def connect():
            h._client = Client()
            h._warm_drive_board_config = fresh.copy()

        async def cleanup():
            h._client = None
            h._warm_drive_board_config = None

        h._ensure_connected = connect
        h._cleanup_connection = cleanup
        h._send_dz06_neo_configuration = AsyncMock(return_value=True)
        packets = []

        async def write(packet):
            self.assertTrue(self.broker.owned_by(h))
            packets.append(bytes(packet))

        h._write_gatt = write
        h._warm_drive_board_config = None
        await h.async_set_warm_drive_max_heat(True)
        self.assertEqual(packets[0][13], 2)
        self.assertEqual(packets[0][2:13], bytes(fresh[2:13]))
        self.assertEqual(packets[0][14:17], bytes(fresh[14:17]))
        self.assertIsNone(h._warm_drive_board_config)

    async def test_cronus_missing_optional_records_keep_extended_poll_budget(self):
        from unittest.mock import AsyncMock

        from .test_coordinator import create_mock_coordinator

        h = create_mock_coordinator()
        h._ble_broker = self.broker
        h._protocol_mode = 9
        h._is_cronus_device = True
        h._ensure_connected = AsyncMock()
        h._cleanup_connection = AsyncMock()
        h._last_auto_time_sync_date = datetime.now().date()
        values = {
            "h1_available": b"\x02",
            "air_state": b"\x00",
            "air_state_real": b"\x05",
            "air_mode": b"\x00",
        }
        calls = []

        async def read(name):
            calls.append(name)
            await asyncio.sleep(0.003)
            if name in values:
                h._cronus_records[name] = values[name]
                return True
            return False

        h._async_read_cronus_record = read
        with (
            patch.object(module, "POLL_TIMEOUT", 0.01),
            patch(
                "custom_components.diesel_heater.coordinator.dt_util.now",
                return_value=datetime.now(),
            ),
        ):
            await h._async_update_data()
        self.assertEqual(len(calls), 17)
        self.assertEqual(h._consecutive_failures, 0)
        self.assertEqual(h._ble_poll_timeout, 90)
        h._cleanup_connection.assert_awaited_once()

    async def test_transaction_timeout_releases_after_cleanup(self):
        h = Fake(self.broker)
        original = module.POLL_TIMEOUT
        module.POLL_TIMEOUT = 0.01
        try:
            with self.assertRaises(TimeoutError), patch.object(Fake, "_ble_poll_timeout", 0.01):
                async with self.broker.session(h, poll=True):
                    await asyncio.sleep(10)
        finally:
            module.POLL_TIMEOUT = original
        self.assertEqual(Fake.active, 0)
        self.assertIsNone(self.broker.owner)


if __name__ == "__main__":
    unittest.main()
