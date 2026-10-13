"""Tests for coordinator-level BT kernel auto-recovery.

Validates the inline recovery path added to `VevorHeaterCoordinator`:

- Scope: only reset the ONE local HCI adapter that is actually serving this
  heater (issue #104). Never touch unrelated adapters just to chase this
  heater's silent-stall.
- Trigger gate: 2 consecutive failed polls + 60s cooldown.
- Timeout wrapper: `_async_update_data` applies `asyncio.wait_for(..., 15)`
  around every status request so a wedged bleak write cannot block the
  update loop forever (which would prevent the auto-recovery from ever
  firing — observed live on 2026-10-11).
"""
from __future__ import annotations

import asyncio
import sys
import time
import types
from unittest.mock import AsyncMock, MagicMock, patch

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


def _patch_last_service_info(source_mac_or_proxy: str | None):
    """Patch `coordinator.bluetooth.async_last_service_info` for this test.

    Pass a local MAC string (uppercase) to simulate the heater being seen
    via that local adapter, a proxy string (e.g. "ESP-xxx") to simulate a
    remote scanner, or None to simulate no recent advertisement.
    """
    from custom_components.diesel_heater import coordinator as coord_module

    if source_mac_or_proxy is None:
        return patch.object(
            coord_module.bluetooth, "async_last_service_info", return_value=None
        )
    info = MagicMock()
    info.source = source_mac_or_proxy
    return patch.object(
        coord_module.bluetooth, "async_last_service_info", return_value=info
    )


# ---------------------------------------------------------------------------
# _should_auto_recover
# ---------------------------------------------------------------------------


class TestShouldAutoRecover:
    """Decision logic — threshold + cooldown gates."""

    def test_below_threshold_returns_false(self):
        c = create_mock_coordinator()
        c._consecutive_failures = 1
        assert c._should_auto_recover() is False

    def test_at_threshold_returns_true(self):
        c = create_mock_coordinator()
        c._consecutive_failures = 2
        c._last_internal_recovery_at = 0.0
        assert c._should_auto_recover() is True

    def test_above_threshold_returns_true(self):
        c = create_mock_coordinator()
        c._consecutive_failures = 10
        c._last_internal_recovery_at = 0.0
        assert c._should_auto_recover() is True

    def test_inside_cooldown_returns_false(self):
        c = create_mock_coordinator()
        c._consecutive_failures = 100
        c._last_internal_recovery_at = time.time() - 5.0
        assert c._should_auto_recover() is False

    def test_after_cooldown_returns_true(self):
        c = create_mock_coordinator()
        c._consecutive_failures = 5
        c._last_internal_recovery_at = time.time() - 120.0
        assert c._should_auto_recover() is True


# ---------------------------------------------------------------------------
# _async_recover_internally — scope-limited to the heater's local adapter
# ---------------------------------------------------------------------------


class TestAsyncRecoverInternally:
    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_recovers_only_the_adapter_serving_this_heater(self):
        """With two local HCIs, only the one HA last saw this heater on is reset."""
        _, recover_mock = _install_bt_stubs({
            "hci0": {"address": "AA:AA:AA:AA:AA:AA"},
            "hci1": {"address": "BB:BB:BB:BB:BB:BB"},
        })
        c = create_mock_coordinator()
        c._cleanup_connection = AsyncMock()
        c.address = "11:22:33:44:55:66"

        with _patch_last_service_info("BB:BB:BB:BB:BB:BB"):
            ok = self._run(c._async_recover_internally())

        assert ok is True
        recover_mock.assert_awaited_once_with(1, "BB:BB:BB:BB:BB:BB", True)
        c._cleanup_connection.assert_awaited_once()

    def test_skips_recovery_for_remote_proxy_source(self):
        """Issue #104: heater via ESPHome proxy must NOT trigger local reset."""
        _, recover_mock = _install_bt_stubs({
            "hci0": {"address": "AA:AA:AA:AA:AA:AA"},
        })
        c = create_mock_coordinator()
        c._cleanup_connection = AsyncMock()

        # Scanner source is a proxy name, not a local HCI MAC
        with _patch_last_service_info("esphome-proxy-livingroom"):
            ok = self._run(c._async_recover_internally())

        assert ok is False
        recover_mock.assert_not_awaited()
        # Still clean up our own stale client
        c._cleanup_connection.assert_awaited_once()
        # No event fired
        c.hass.bus.async_fire.assert_not_called()

    def test_skips_recovery_when_source_unknown(self):
        """No recent advertisement → cannot determine adapter → skip."""
        _, recover_mock = _install_bt_stubs({
            "hci0": {"address": "AA:AA:AA:AA:AA:AA"},
        })
        c = create_mock_coordinator()
        c._cleanup_connection = AsyncMock()

        with _patch_last_service_info(None):
            ok = self._run(c._async_recover_internally())

        assert ok is False
        recover_mock.assert_not_awaited()
        c._cleanup_connection.assert_awaited_once()

    def test_does_not_touch_unrelated_local_adapter(self):
        """Confirms the specific regression from #104: 3 local adapters, only
        the matching one gets reset — the other two are untouched."""
        _, recover_mock = _install_bt_stubs({
            "hci0": {"address": "AA:AA:AA:AA:AA:AA"},  # unrelated
            "hci1": {"address": "BB:BB:BB:BB:BB:BB"},  # unrelated
            "hci2": {"address": "CC:CC:CC:CC:CC:CC"},  # target
        })
        c = create_mock_coordinator()
        c._cleanup_connection = AsyncMock()

        with _patch_last_service_info("CC:CC:CC:CC:CC:CC"):
            self._run(c._async_recover_internally())

        assert recover_mock.await_count == 1
        recover_mock.assert_awaited_once_with(2, "CC:CC:CC:CC:CC:CC", True)

    def test_fires_event_with_adapter_metadata_on_success(self):
        _install_bt_stubs({"hci0": {"address": "AA:BB:CC:DD:EE:FF"}})
        c = create_mock_coordinator()
        c._cleanup_connection = AsyncMock()
        c.address = "99:99:99:99:99:99"
        c._consecutive_failures = 3

        with _patch_last_service_info("AA:BB:CC:DD:EE:FF"):
            self._run(c._async_recover_internally())

        c.hass.bus.async_fire.assert_called_once()
        event_name, payload = c.hass.bus.async_fire.call_args[0]
        assert event_name.endswith("_bluetooth_recovered")
        assert payload["source"] == "coordinator_auto_recovery"
        assert payload["address"] == "99:99:99:99:99:99"
        assert payload["adapter"] == "hci0"
        assert payload["adapter_mac"] == "AA:BB:CC:DD:EE:FF"
        assert payload["consecutive_failures"] == 3

    def test_no_event_when_recovery_returns_false(self):
        _install_bt_stubs(
            {"hci0": {"address": "AA:BB:CC:DD:EE:FF"}},
            recover_result=False,
        )
        c = create_mock_coordinator()
        c._cleanup_connection = AsyncMock()

        with _patch_last_service_info("AA:BB:CC:DD:EE:FF"):
            ok = self._run(c._async_recover_internally())

        assert ok is False
        c.hass.bus.async_fire.assert_not_called()
        c._cleanup_connection.assert_awaited_once()

    def test_cleans_up_connection_even_on_adapter_recover_raise(self):
        _, recover_mock = _install_bt_stubs({"hci0": {"address": "AA:BB:CC:DD:EE:FF"}})
        recover_mock.side_effect = RuntimeError("hcidown failed")
        c = create_mock_coordinator()
        c._cleanup_connection = AsyncMock()

        with _patch_last_service_info("AA:BB:CC:DD:EE:FF"):
            ok = self._run(c._async_recover_internally())

        assert ok is False
        c._cleanup_connection.assert_awaited_once()

    def test_graceful_when_bluetooth_auto_recovery_module_absent(self):
        sys.modules.pop("bluetooth_auto_recovery", None)
        sys.modules.pop("bluetooth_adapters", None)
        bt_adapters_mod = types.ModuleType("bluetooth_adapters")
        bt_adapters_mod.get_adapters = MagicMock(return_value=MagicMock())
        sys.modules["bluetooth_adapters"] = bt_adapters_mod

        c = create_mock_coordinator()
        c._cleanup_connection = AsyncMock()

        ok = self._run(c._async_recover_internally())

        assert ok is False
        c._cleanup_connection.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_connection_failure schedules recovery
# ---------------------------------------------------------------------------


class TestHandleConnectionFailureSchedulesRecovery:
    def test_single_failure_does_not_schedule_recovery(self):
        _install_bt_stubs({"hci0": {"address": "AA:AA:AA:AA:AA:AA"}})
        c = create_mock_coordinator()
        c._consecutive_failures = 0
        c.hass.async_create_task = MagicMock()

        c._handle_connection_failure(Exception("one-off"))

        c.hass.async_create_task.assert_not_called()

    def test_second_failure_schedules_recovery_once(self):
        _install_bt_stubs({"hci0": {"address": "AA:AA:AA:AA:AA:AA"}})
        c = create_mock_coordinator()
        c._consecutive_failures = 1
        c._last_internal_recovery_at = 0.0

        created = []
        def _create(coro, *a, **kw):
            created.append(coro)
            coro.close()
            return MagicMock()
        c.hass.async_create_task = MagicMock(side_effect=_create)

        c._handle_connection_failure(Exception("silent-stall"))

        assert len(created) == 1
        assert c._last_internal_recovery_at > 0

    def test_third_failure_within_cooldown_does_not_reschedule(self):
        _install_bt_stubs({"hci0": {"address": "AA:AA:AA:AA:AA:AA"}})
        c = create_mock_coordinator()
        c._consecutive_failures = 10
        c._last_internal_recovery_at = time.time() - 5.0
        c.hass.async_create_task = MagicMock()

        c._handle_connection_failure(Exception("still stalled"))

        c.hass.async_create_task.assert_not_called()

    def test_failure_after_cooldown_schedules_again(self):
        _install_bt_stubs({"hci0": {"address": "AA:AA:AA:AA:AA:AA"}})
        c = create_mock_coordinator()
        c._consecutive_failures = 10
        c._last_internal_recovery_at = time.time() - 120.0

        created = []
        def _create(coro, *a, **kw):
            created.append(coro)
            coro.close()
            return MagicMock()
        c.hass.async_create_task = MagicMock(side_effect=_create)

        c._handle_connection_failure(Exception("still stalled"))

        assert len(created) == 1


# ---------------------------------------------------------------------------
# Timeout wrapper around _send_command (issue: bleak write hangs forever
# when the kernel adapter is wedged, preventing the recovery threshold from
# ever being reached)
# ---------------------------------------------------------------------------


class TestSendCommandTimeoutWrapper:
    """`_async_update_data` must apply a hard outer timeout per attempt."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_hung_send_command_increments_failure_counter(self):
        """A `_send_command` that never returns must still produce a failure."""
        from custom_components.diesel_heater import coordinator as coord_module

        _install_bt_stubs({"hci0": {"address": "AA:AA:AA:AA:AA:AA"}})
        c = create_mock_coordinator()
        c._consecutive_failures = 0
        c._client = MagicMock()
        c._client.is_connected = True

        # Simulate bleak hang by making _send_command block for far longer
        # than the wrapper's timeout (15s). The wait_for wrapper should fire
        # after a short monkey-patched timeout and the loop should mark it
        # a failure.
        async def _hang(*a, **kw):
            await asyncio.sleep(60)
            return True

        c._send_command = AsyncMock(side_effect=_hang)
        c._check_daily_reset = AsyncMock()
        c._check_daily_runtime_reset = AsyncMock()
        c._ensure_connected = AsyncMock()
        c._handle_connection_failure = MagicMock(
            wraps=lambda err: setattr(c, "_consecutive_failures", c._consecutive_failures + 1)
        )

        # Shrink the wrapper timeout from 15s to 0.05s via monkey-patch of
        # asyncio.wait_for inside coord_module scope.
        orig_wait_for = asyncio.wait_for

        async def _fast_wait_for(aw, timeout):
            return await orig_wait_for(aw, timeout=0.05)

        with patch.object(coord_module.asyncio, "wait_for", side_effect=_fast_wait_for):
            try:
                self._run(c._async_update_data())
            except Exception:
                pass  # UpdateFailed may propagate; irrelevant here

        # The key assertion: _handle_connection_failure was called at least once
        # — proving that a hung _send_command does produce a failure signal
        # rather than blocking forever.
        assert c._handle_connection_failure.called
