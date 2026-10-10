"""Tests for coordinator-level BT kernel auto-recovery.

Validates the inline recovery path added to `VevorHeaterCoordinator` after
diagnosing on 2026-10-10 that the BCM43438 BlueZ driver on Raspberry Pi
re-stalls GATT after exactly 1 poll with some diesel heaters. The manually
called `diesel_heater.recover_bluetooth` service was proven to work on 4
cycles, so we now run the same logic in-process on silent-stall detection.
"""
from __future__ import annotations

import asyncio
import sys
import time
import types
from unittest.mock import AsyncMock, MagicMock

# Install HA stubs via project conftest
from . import conftest  # noqa: F401
from .test_coordinator import create_mock_coordinator


def _install_bt_stubs(adapters: dict, recover_result: bool = True):
    """Install mock bluetooth_adapters + bluetooth_auto_recovery modules."""
    adapters_mgr = MagicMock()
    adapters_mgr.refresh = AsyncMock()
    adapters_mgr.adapters = adapters

    bt_adapters_mod = types.ModuleType("bluetooth_adapters")
    bt_adapters_mod.get_adapters = MagicMock(return_value=adapters_mgr)
    sys.modules["bluetooth_adapters"] = bt_adapters_mod

    recover_adapter = AsyncMock(return_value=recover_result)
    bt_recovery_mod = types.ModuleType("bluetooth_auto_recovery")
    bt_recovery_mod.recover_adapter = recover_adapter
    sys.modules["bluetooth_auto_recovery"] = bt_recovery_mod

    return adapters_mgr, recover_adapter


# ---------------------------------------------------------------------------
# _should_auto_recover
# ---------------------------------------------------------------------------


class TestShouldAutoRecover:
    """Decision logic — threshold + cooldown gates."""

    def test_below_threshold_returns_false(self):
        c = create_mock_coordinator()
        c._consecutive_failures = 1  # threshold is 2
        assert c._should_auto_recover() is False

    def test_at_threshold_returns_true(self):
        c = create_mock_coordinator()
        c._consecutive_failures = 2
        c._last_internal_recovery_at = 0.0  # never recovered
        assert c._should_auto_recover() is True

    def test_above_threshold_returns_true(self):
        c = create_mock_coordinator()
        c._consecutive_failures = 10
        c._last_internal_recovery_at = 0.0
        assert c._should_auto_recover() is True

    def test_inside_cooldown_returns_false(self):
        """Even with 100 failures, don't thrash — one recovery per cooldown."""
        c = create_mock_coordinator()
        c._consecutive_failures = 100
        c._last_internal_recovery_at = time.time() - 5.0  # 5s ago, cooldown 60s
        assert c._should_auto_recover() is False

    def test_after_cooldown_returns_true(self):
        c = create_mock_coordinator()
        c._consecutive_failures = 5
        c._last_internal_recovery_at = time.time() - 120.0  # 2 min ago
        assert c._should_auto_recover() is True


# ---------------------------------------------------------------------------
# _async_recover_internally
# ---------------------------------------------------------------------------


class TestAsyncRecoverInternally:
    """The actual kernel reset + BLE cleanup + event firing."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_calls_recover_adapter_for_hci_devices(self):
        _, recover_mock = _install_bt_stubs(
            {"hci0": {"address": "DC:A6:32:AA:BB:CC"}}
        )
        c = create_mock_coordinator()
        c._cleanup_connection = AsyncMock()

        ok = self._run(c._async_recover_internally())

        assert ok is True
        recover_mock.assert_awaited_once_with(0, "DC:A6:32:AA:BB:CC", True)
        c._cleanup_connection.assert_awaited_once()

    def test_skips_non_hci_entries(self):
        _, recover_mock = _install_bt_stubs(
            {
                "hci0": {"address": "AA:AA:AA:AA:AA:AA"},
                "bluez_input": {"address": "11:22:33:44:55:66"},
                "serial0": {"address": "77:88:99:00:11:22"},
            }
        )
        c = create_mock_coordinator()
        c._cleanup_connection = AsyncMock()

        self._run(c._async_recover_internally())

        assert recover_mock.await_count == 1
        recover_mock.assert_awaited_once_with(0, "AA:AA:AA:AA:AA:AA", True)

    def test_handles_multiple_hci_adapters(self):
        _, recover_mock = _install_bt_stubs(
            {
                "hci0": {"address": "AA:AA:AA:AA:AA:AA"},
                "hci1": {"address": "BB:BB:BB:BB:BB:BB"},
            }
        )
        c = create_mock_coordinator()
        c._cleanup_connection = AsyncMock()

        self._run(c._async_recover_internally())

        assert recover_mock.await_count == 2
        awaited_args = [call.args for call in recover_mock.await_args_list]
        assert (0, "AA:AA:AA:AA:AA:AA", True) in awaited_args
        assert (1, "BB:BB:BB:BB:BB:BB", True) in awaited_args

    def test_fires_event_on_success(self):
        _install_bt_stubs({"hci0": {"address": "AA:BB:CC:DD:EE:FF"}})
        c = create_mock_coordinator()
        c._cleanup_connection = AsyncMock()
        c.address = "AA:BB:CC:DD:EE:FF"
        c._consecutive_failures = 3

        self._run(c._async_recover_internally())

        c.hass.bus.async_fire.assert_called_once()
        event_name, payload = c.hass.bus.async_fire.call_args[0]
        assert event_name.endswith("_bluetooth_recovered")
        assert payload["source"] == "coordinator_auto_recovery"
        assert payload["address"] == "AA:BB:CC:DD:EE:FF"
        assert payload["consecutive_failures"] == 3

    def test_no_event_when_recovery_failed(self):
        """If recover_adapter returns False (kernel reset failed), skip event."""
        _install_bt_stubs(
            {"hci0": {"address": "AA:BB:CC:DD:EE:FF"}},
            recover_result=False,
        )
        c = create_mock_coordinator()
        c._cleanup_connection = AsyncMock()

        ok = self._run(c._async_recover_internally())

        assert ok is False
        c.hass.bus.async_fire.assert_not_called()
        # cleanup still runs
        c._cleanup_connection.assert_awaited_once()

    def test_cleans_up_connection_even_on_adapter_failure(self):
        """A raise from recover_adapter must not prevent cleanup."""
        _, recover_mock = _install_bt_stubs({"hci0": {"address": "AA:BB:CC:DD:EE:FF"}})
        recover_mock.side_effect = RuntimeError("hcidown failed")
        c = create_mock_coordinator()
        c._cleanup_connection = AsyncMock()

        ok = self._run(c._async_recover_internally())

        assert ok is False
        c._cleanup_connection.assert_awaited_once()

    def test_graceful_when_bluetooth_recovery_unavailable(self):
        """ImportError on bluetooth_auto_recovery doesn't crash the coordinator."""
        sys.modules.pop("bluetooth_auto_recovery", None)
        sys.modules.pop("bluetooth_adapters", None)
        # Install bluetooth_adapters but NOT bluetooth_auto_recovery -> ImportError
        bt_adapters_mod = types.ModuleType("bluetooth_adapters")
        bt_adapters_mod.get_adapters = MagicMock(return_value=MagicMock())
        sys.modules["bluetooth_adapters"] = bt_adapters_mod

        c = create_mock_coordinator()
        c._cleanup_connection = AsyncMock()

        ok = self._run(c._async_recover_internally())

        assert ok is False
        # Cleanup should NOT be called since we bailed on import error
        c._cleanup_connection.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_connection_failure + schedule integration
# ---------------------------------------------------------------------------


class TestHandleConnectionFailureSchedulesRecovery:
    """When failures accumulate past threshold, a recovery task is scheduled."""

    def test_single_failure_does_not_schedule_recovery(self):
        _install_bt_stubs({"hci0": {"address": "AA:AA:AA:AA:AA:AA"}})
        c = create_mock_coordinator()
        c._consecutive_failures = 0  # will become 1 after call
        c.hass.async_create_task = MagicMock()

        c._handle_connection_failure(Exception("one-off"))

        c.hass.async_create_task.assert_not_called()

    def test_second_failure_schedules_recovery_once(self):
        """At the threshold, the task is scheduled exactly once."""
        _install_bt_stubs({"hci0": {"address": "AA:AA:AA:AA:AA:AA"}})
        c = create_mock_coordinator()
        c._consecutive_failures = 1  # will become 2 — at threshold
        c._last_internal_recovery_at = 0.0

        # Make async_create_task consume the coroutine so no "never awaited" warning
        created = []

        def _create(coro, *a, **kw):
            created.append(coro)
            coro.close()
            return MagicMock()

        c.hass.async_create_task = MagicMock(side_effect=_create)

        c._handle_connection_failure(Exception("silent-stall"))

        assert len(created) == 1
        # Last recovery timestamp was updated
        assert c._last_internal_recovery_at > 0

    def test_third_failure_within_cooldown_does_not_reschedule(self):
        """After one recovery, further failures within cooldown don't re-trigger."""
        _install_bt_stubs({"hci0": {"address": "AA:AA:AA:AA:AA:AA"}})
        c = create_mock_coordinator()
        c._consecutive_failures = 10
        c._last_internal_recovery_at = time.time() - 5.0  # 5s ago
        c.hass.async_create_task = MagicMock()

        c._handle_connection_failure(Exception("still stalled"))

        c.hass.async_create_task.assert_not_called()

    def test_failure_after_cooldown_schedules_again(self):
        _install_bt_stubs({"hci0": {"address": "AA:AA:AA:AA:AA:AA"}})
        c = create_mock_coordinator()
        c._consecutive_failures = 10
        c._last_internal_recovery_at = time.time() - 120.0  # 2 min ago

        created = []

        def _create(coro, *a, **kw):
            created.append(coro)
            coro.close()
            return MagicMock()

        c.hass.async_create_task = MagicMock(side_effect=_create)

        c._handle_connection_failure(Exception("still stalled"))

        assert len(created) == 1
