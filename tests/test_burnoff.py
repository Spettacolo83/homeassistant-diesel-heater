"""Unit tests for the extracted burn-off phase machine."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.diesel_heater.burnoff import (
    BURNOFF_HEAT_STEPS,
    BurnoffController,
    BurnoffPhase,
)
from custom_components.diesel_heater.const import (
    RUNNING_MODE_LEVEL,
    RUNNING_MODE_TEMPERATURE,
    RUNNING_STATE_OFF,
    RUNNING_STATE_ON,
    RUNNING_STEP_COOLDOWN,
    RUNNING_STEP_RUNNING,
    RUNNING_STEP_STANDBY,
)

from .test_coordinator import (
    _enable_burnoff,
    _enable_in_run,
    _set_heating,
    create_mock_coordinator,
)


def test_phases_are_mutually_exclusive():
    """A cycle can be in only one phase; restoring is still active."""
    controller = BurnoffController(host=MagicMock())
    assert controller.cycle.phase == BurnoffPhase.IDLE
    assert controller.active is False
    assert controller.remaining_seconds is None

    controller.cycle.phase = BurnoffPhase.RUNNING
    controller.cycle.ends_at = datetime.now(UTC) + timedelta(minutes=5)
    assert controller.active is True
    assert controller.remaining_seconds is not None
    assert controller.cycle.phase == BurnoffPhase.RUNNING

    controller.cycle.phase = BurnoffPhase.AWAITING_STATUS
    assert controller.active is True
    assert controller.cycle.phase == BurnoffPhase.AWAITING_STATUS
    assert controller.remaining_seconds is not None

    controller.cycle.phase = BurnoffPhase.RESTORING
    assert controller.active is True
    assert controller.cycle.phase == BurnoffPhase.RESTORING
    assert controller.remaining_seconds is None

    controller.cycle.phase = BurnoffPhase.PAUSED
    assert controller.active is True
    assert controller.cycle.phase == BurnoffPhase.PAUSED
    assert controller.remaining_seconds is None


def test_storage_payload_writes_phase_and_legacy_flag():
    """Live-cycle storage includes phase plus the old awaiting_snapshot_write flag."""
    host = MagicMock()
    controller = BurnoffController(host)
    controller.cycle.phase = BurnoffPhase.RESTORING
    controller.cycle.shutdown_after = False
    controller.cycle.saved_mode = RUNNING_MODE_TEMPERATURE
    controller.cycle.saved_temp = 21
    controller.cycle.saved_protocol_state = {"heatgenie_run_mode": 1}
    controller.cycle.ends_at = datetime.now(UTC)

    payload = controller.storage_payload()
    assert payload is not None
    assert payload["active"] is True
    assert payload["phase"] == BurnoffPhase.RESTORING
    assert payload["awaiting_snapshot_write"] is True
    assert payload["saved_mode"] == RUNNING_MODE_TEMPERATURE
    assert payload["saved_protocol_state"] == {"heatgenie_run_mode": 1}


@pytest.mark.asyncio
async def test_load_state_falls_back_from_legacy_awaiting_flags():
    """Old payloads without phase still resume restoring vs awaiting-status."""
    coordinator = create_mock_coordinator()
    coordinator._burnoff.schedule_wait = MagicMock()

    restoring = {
        "active": True,
        "shutdown_after": False,
        "ends_at": datetime.now(UTC).isoformat(),
        "saved_mode": RUNNING_MODE_LEVEL,
        "saved_level": 4,
        "saved_temp": None,
        "awaiting_snapshot_write": True,
    }
    await coordinator._burnoff.load_state(restoring)
    assert coordinator._burnoff.cycle.phase == BurnoffPhase.RESTORING
    coordinator._burnoff.schedule_wait.assert_not_called()

    resumed = create_mock_coordinator()
    resumed._burnoff.schedule_wait = MagicMock()
    await resumed._burnoff.load_state(
        {
            "active": True,
            "shutdown_after": True,
            "ends_at": (datetime.now(UTC) + timedelta(minutes=4)).isoformat(),
            "saved_mode": RUNNING_MODE_TEMPERATURE,
            "saved_level": 3,
            "saved_temp": 20,
        }
    )
    assert resumed._burnoff.cycle.phase == BurnoffPhase.AWAITING_STATUS
    resumed._burnoff.schedule_wait.assert_called_once()

    phased = create_mock_coordinator()
    phased._burnoff.schedule_wait = MagicMock()
    await phased._burnoff.load_state(
        {
            "active": True,
            "phase": BurnoffPhase.RESTORING,
            "shutdown_after": False,
            "ends_at": datetime.now(UTC).isoformat(),
            "saved_mode": RUNNING_MODE_LEVEL,
            "saved_level": 2,
            "saved_temp": None,
            "awaiting_snapshot_write": False,
        }
    )
    assert phased._burnoff.cycle.phase == BurnoffPhase.RESTORING
    phased._burnoff.schedule_wait.assert_not_called()


@pytest.mark.parametrize(
    ("prev", "new", "expect_pending", "expect_cycles"),
    [
        (
            (RUNNING_STATE_ON, RUNNING_STEP_RUNNING, RUNNING_MODE_LEVEL),
            (RUNNING_STATE_OFF, RUNNING_STEP_STANDBY, RUNNING_MODE_LEVEL),
            True,
            0,
        ),
        (
            (RUNNING_STATE_ON, RUNNING_STEP_RUNNING, RUNNING_MODE_TEMPERATURE),
            (RUNNING_STATE_ON, RUNNING_STEP_COOLDOWN, RUNNING_MODE_TEMPERATURE),
            False,
            1,
        ),
        (
            (RUNNING_STATE_ON, RUNNING_STEP_STANDBY, RUNNING_MODE_TEMPERATURE),
            (RUNNING_STATE_OFF, RUNNING_STEP_STANDBY, RUNNING_MODE_TEMPERATURE),
            False,
            0,
        ),
    ],
)
def test_observe_status_edges(prev, new, expect_pending, expect_cycles):
    """LCD Off while dirty pendings; leave-heating counts a cycle; idle Off does not."""
    coordinator = create_mock_coordinator()
    _enable_burnoff(coordinator)

    def _close_task(coro, *args, **kwargs):
        coro.close()
        return MagicMock()

    coordinator.hass.async_create_task = _close_task
    prev_state, prev_step, prev_mode = prev
    new_state, new_step, new_mode = new
    coordinator.data["running_state"] = prev_state
    coordinator.data["running_step"] = prev_step
    coordinator.data["running_mode"] = prev_mode
    coordinator._burnoff.observe_status()

    coordinator.data["running_state"] = new_state
    coordinator.data["running_step"] = new_step
    coordinator.data["running_mode"] = new_mode
    coordinator._burnoff.observe_status()

    assert coordinator.burnoff_pending is expect_pending
    assert coordinator._burnoff.accumulator.cycles == expect_cycles


def test_ha_power_off_does_not_count_cycle():
    """HA Off intent must not increment the controller cycle counter."""
    coordinator = create_mock_coordinator()

    def _close_task(coro, *args, **kwargs):
        coro.close()
        return MagicMock()

    coordinator.hass.async_create_task = _close_task
    coordinator._burnoff.ha_power_off = True
    coordinator.data["running_state"] = RUNNING_STATE_ON
    coordinator.data["running_step"] = RUNNING_STEP_RUNNING
    coordinator.data["running_mode"] = RUNNING_MODE_TEMPERATURE
    coordinator._burnoff.observe_status()
    coordinator.data["running_step"] = RUNNING_STEP_COOLDOWN
    coordinator._burnoff.observe_status()
    assert coordinator._burnoff.accumulator.cycles == 0


def test_parse_error_off_without_observe_does_not_pending():
    """Forcing running_state=0 without observe is not treated as LCD Off."""
    coordinator = create_mock_coordinator()
    _enable_burnoff(coordinator)
    coordinator.data["running_state"] = RUNNING_STATE_ON
    coordinator.data["running_step"] = RUNNING_STEP_RUNNING
    coordinator.data["running_mode"] = RUNNING_MODE_TEMPERATURE
    coordinator._burnoff.observe_status()
    coordinator.data["running_state"] = 0
    coordinator.data["running_step"] = 0
    assert coordinator.burnoff_pending is False


def test_heat_steps_exclude_standby_and_cooldown():
    """In-run / HA Off start only from combustion steps."""
    assert RUNNING_STEP_RUNNING in BURNOFF_HEAT_STEPS
    assert RUNNING_STEP_STANDBY not in BURNOFF_HEAT_STEPS
    assert RUNNING_STEP_COOLDOWN not in BURNOFF_HEAT_STEPS


@pytest.mark.asyncio
async def test_restore_without_snapshot_succeeds_during_cooldown():
    coordinator = create_mock_coordinator()
    coordinator.data["running_step"] = RUNNING_STEP_COOLDOWN
    coordinator._burnoff.cycle.saved_mode = None

    assert await coordinator._burnoff.restore_saved_mode() is True


@pytest.mark.asyncio
async def test_concurrent_in_run_starts_schedule_once():
    """Two overlapping start_in_run calls share one async_start_burnoff."""
    coordinator = create_mock_coordinator()
    entered = 0
    release = asyncio.Event()
    started = asyncio.Event()

    async def _start(*, shutdown_after: bool = True) -> None:
        nonlocal entered
        entered += 1
        assert shutdown_after is False
        started.set()
        await release.wait()

    coordinator.async_start_burnoff = _start
    controller = coordinator._burnoff
    first = asyncio.create_task(controller.start_in_run())
    second = asyncio.create_task(controller.start_in_run())

    await started.wait()
    await asyncio.sleep(0)
    assert entered == 1
    assert controller.start_scheduled is True

    release.set()
    await asyncio.gather(first, second)
    assert entered == 1
    assert controller.start_scheduled is False


@pytest.mark.asyncio
async def test_maybe_start_in_run_skips_while_start_is_claimed():
    """A later status tick does not queue another start once the claim is held."""
    coordinator = create_mock_coordinator()
    _enable_in_run(coordinator, cycles=1)
    _set_heating(coordinator)
    coordinator.data["running_mode"] = RUNNING_MODE_LEVEL
    coordinator._burnoff.accumulator.cycles = 1

    entered = 0
    release = asyncio.Event()

    async def _start(*, shutdown_after: bool = True) -> None:
        nonlocal entered
        entered += 1
        await release.wait()

    coordinator.async_start_burnoff = _start
    tasks: list[asyncio.Task[None]] = []

    def _create_task(coro, *args, **kwargs):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task

    coordinator.hass.async_create_task = _create_task
    coordinator._burnoff.maybe_start_in_run()
    await asyncio.sleep(0)
    assert entered == 1
    assert coordinator._burnoff.start_scheduled is True

    coordinator._burnoff.maybe_start_in_run()
    await asyncio.sleep(0)
    assert len(tasks) == 1
    assert entered == 1

    release.set()
    await asyncio.gather(*tasks)
    assert coordinator._burnoff.start_scheduled is False


@pytest.mark.asyncio
async def test_start_in_run_clears_claim_so_a_later_start_can_run():
    """Finishing a start drops the claim so the next in-run start can proceed."""
    coordinator = create_mock_coordinator()
    entered = 0

    async def _start(*, shutdown_after: bool = True) -> None:
        nonlocal entered
        entered += 1

    coordinator.async_start_burnoff = _start
    controller = coordinator._burnoff

    await controller.start_in_run()
    assert entered == 1
    assert controller.start_scheduled is False

    await controller.start_in_run()
    assert entered == 2
    assert controller.start_scheduled is False
