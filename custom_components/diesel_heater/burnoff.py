"""Max-power soot burn-off: live cycle, soot accumulator, and scheduling.

The live cycle is an explicit phase machine. Soot load and "start on next
RUNNING" live on the accumulator and are not cycle phases.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    BURNOFF_NEAR_COMPLETE_REMAINING_RATIO,
    MAX_BURNOFF_IN_RUN_ABORTS,
    RUNNING_MODE_VENTILATION,
    RUNNING_STATE_OFF,
    RUNNING_STATE_ON,
    RUNNING_STEP_COOLDOWN,
    RUNNING_STEP_IGNITION,
    RUNNING_STEP_RUNNING,
    RUNNING_STEP_SELF_TEST,
    RUNNING_STEP_STANDBY,
    RUNNING_STEP_VENTILATION,
    UPDATE_INTERVAL,
    UPDATE_INTERVAL_HCALORY,
)

# Combustion steps. Standby is Auto Start/Stop idle (no re-ignite). Cooldown is
# shutdown-in-progress (restore writes often do not stick).
BURNOFF_HEAT_STEPS = frozenset(
    {
        RUNNING_STEP_SELF_TEST,
        RUNNING_STEP_IGNITION,
        RUNNING_STEP_RUNNING,
    }
)


class BurnoffPhase(StrEnum):
    """Live burn-off cycle phase.

    pending (start on next RUNNING) is accumulator state, not a phase.
    """

    IDLE = "idle"
    RUNNING = "running"
    AWAITING_STATUS = "awaiting_status"
    RESTORING = "restoring"


@dataclass
class BurnoffCycle:
    """In-progress max-power cycle and the snapshot to restore afterwards."""

    phase: BurnoffPhase = BurnoffPhase.IDLE
    shutdown_after: bool = False
    ends_at: datetime | None = None
    saved_mode: int | None = None
    saved_level: int | None = None
    saved_temp: float | None = None
    saved_protocol_state: dict[str, Any] | None = None
    applying: bool = False


@dataclass
class BurnoffAccumulator:
    """Soot since last successful clean, plus deferred in-run scheduling."""

    heating_seconds: float = 0.0
    cycles: int = 0
    pending: bool = False
    just_completed: bool = False
    in_run_aborts: int = 0
    skip_in_run: bool = False
    prev_step: int | None = None
    prev_state: int | None = None
    prev_mode: int | None = None


class BurnoffController:
    """Owns burn-off phase, soot counters, wait task, and one-shot Off intents.

    Command writes stay on the host (coordinator). Tests patch methods on this
    controller; lookups happen on self at call time so mocks still intercept.
    """

    def __init__(self, host: Any) -> None:
        """Initialize controller bound to a coordinator-like host."""
        self._host = host
        self.cycle = BurnoffCycle()
        self.accumulator = BurnoffAccumulator()
        self.lock = asyncio.Lock()
        self.cancel_event = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        # Power Off Now: the following ON→OFF must not set pending.
        self.skip_pending_on_off = False
        # HA sent the off command; do not count that shutdown as a controller cycle.
        self.ha_power_off = False
        # At most one in-run async_start_burnoff task at a time.
        self.start_scheduled = False
        # Entity fields only. Listeners are not ready while the host is constructed.
        self._seed_data()

    def _seed_data(self) -> None:
        """Write initial entity fields without notifying listeners."""
        data = self._host.data
        data["burnoff_active"] = False
        data["burnoff_remaining"] = None
        data["burnoff_cycles"] = 0
        data["burnoff_hours"] = 0.0
        data["burnoff_pending"] = False

    @property
    def active(self) -> bool:
        """Return True while a cycle is running or still restoring the snapshot."""
        return self.cycle.phase != BurnoffPhase.IDLE

    @property
    def pending(self) -> bool:
        """Return whether in-run burn-off will start on the next RUNNING step."""
        return self.accumulator.pending

    @property
    def remaining_seconds(self) -> int | None:
        """Return remaining burn-off time, or None if idle or restoring."""
        if self.cycle.phase not in (
            BurnoffPhase.RUNNING,
            BurnoffPhase.AWAITING_STATUS,
        ):
            return None
        if self.cycle.ends_at is None:
            return None
        remaining = (self.cycle.ends_at - datetime.now(UTC)).total_seconds()
        return max(0, int(remaining))

    @property
    def hours_since(self) -> float:
        """Return RUNNING hours since the last successful burn-off."""
        return round(self.accumulator.heating_seconds / 3600.0, 2)

    def storage_payload(self) -> dict[str, Any] | None:
        """Return persistable live-cycle state, or None when idle."""
        if not self.active:
            return None
        ends_at = self.cycle.ends_at
        return {
            "active": True,
            "phase": self.cycle.phase.value,
            "shutdown_after": self.cycle.shutdown_after,
            "ends_at": ends_at.isoformat() if ends_at is not None else None,
            "saved_mode": self.cycle.saved_mode,
            "saved_level": self.cycle.saved_level,
            "saved_temp": self.cycle.saved_temp,
            "saved_protocol_state": self.cycle.saved_protocol_state,
            "awaiting_snapshot_write": self.cycle.phase == BurnoffPhase.RESTORING,
        }

    def accumulator_payload(self) -> dict[str, Any]:
        """Return persistable soot-load counters and deferred in-run pending."""
        return {
            "seconds": self.accumulator.heating_seconds,
            "cycles": self.accumulator.cycles,
            "pending": self.accumulator.pending,
            "just_completed": self.accumulator.just_completed,
            "in_run_aborts": self.accumulator.in_run_aborts,
            "skip_in_run": self.accumulator.skip_in_run,
        }

    def load_accumulator(self, payload: dict[str, Any] | None) -> None:
        """Restore soot-load counters after Home Assistant restart."""
        if not payload:
            self.publish_accumulator()
            return
        try:
            self.accumulator.heating_seconds = max(0.0, float(payload.get("seconds", 0.0)))
        except (TypeError, ValueError):
            self.accumulator.heating_seconds = 0.0
        try:
            self.accumulator.cycles = max(0, int(payload.get("cycles", 0)))
        except (TypeError, ValueError):
            self.accumulator.cycles = 0
        self.accumulator.pending = bool(payload.get("pending", False))
        self.accumulator.just_completed = bool(payload.get("just_completed", False))
        try:
            self.accumulator.in_run_aborts = max(0, int(payload.get("in_run_aborts", 0)))
        except (TypeError, ValueError):
            self.accumulator.in_run_aborts = 0
        self.accumulator.skip_in_run = bool(payload.get("skip_in_run", False))
        self.publish_accumulator()

    def publish_accumulator(self) -> None:
        """Copy soot-load counters into coordinator data for diagnostic entities."""
        data = self._host.data
        prev_pending = data.get("burnoff_pending")
        prev_cycles = data.get("burnoff_cycles")
        data["burnoff_cycles"] = self.accumulator.cycles
        data["burnoff_hours"] = self.hours_since
        data["burnoff_pending"] = self.accumulator.pending
        if prev_pending != self.accumulator.pending or prev_cycles != self.accumulator.cycles:
            self._host.async_set_updated_data(data)

    def reset_accumulator(self) -> None:
        """Mark soot cleaned. Does not clear an in-progress cycle or deferred restore."""
        self.accumulator.heating_seconds = 0.0
        self.accumulator.cycles = 0
        self.accumulator.pending = False
        self.accumulator.just_completed = True
        self.accumulator.in_run_aborts = 0
        self.accumulator.skip_in_run = False
        self.publish_accumulator()

    def dirty(self) -> bool:
        """Return True if there has been combustion since the last successful burn-off."""
        if self.accumulator.heating_seconds > 0 or self.accumulator.cycles > 0:
            return True
        if self.accumulator.just_completed:
            # Successful clean: wait for new heating before HA Off burns again.
            return False
        # First ticks of a heat session (or unit tests) before runtime has accumulated.
        data = self._host.data
        return (
            data.get("running_state") == RUNNING_STATE_ON
            and data.get("running_step") in BURNOFF_HEAT_STEPS
            and data.get("running_mode") != RUNNING_MODE_VENTILATION
        )

    def nearly_complete(self) -> bool:
        """Return True if the timer is close enough to treat an abort as success."""
        remaining = self.remaining_seconds
        duration_seconds = self._host.burnoff_duration_minutes * 60
        if remaining is None or duration_seconds <= 0:
            return False
        return remaining <= duration_seconds * BURNOFF_NEAR_COMPLETE_REMAINING_RATIO

    def should_run_in_cycle(self) -> bool:
        """Return True if in-run burn-off should start or be deferred as pending."""
        if self.accumulator.pending:
            # LCD Off / abort retry / mid-heat threshold. Overrides skip_in_run.
            return True
        if self.accumulator.skip_in_run:
            return False
        hours_limit = self._host.burnoff_after_hours
        if hours_limit > 0 and self.accumulator.heating_seconds >= hours_limit * 3600:
            return True
        cycles_limit = self._host.burnoff_after_cycles
        return cycles_limit > 0 and self.accumulator.cycles >= cycles_limit

    def hour_tick_cap(self) -> float:
        """Return max RUNNING seconds to credit per status update."""
        interval = UPDATE_INTERVAL_HCALORY if self._host._protocol_mode == 7 else UPDATE_INTERVAL
        # Elapsed is now minus last successful poll. Two intervals covers one
        # missed (or late) update; a long BLE disconnect must not dump hours.
        return float(interval * 2)

    def accumulate_hours(self, elapsed_seconds: float) -> None:
        """Add RUNNING time to the soot accumulator."""
        # Don't count the Level 10 interval itself as new soot.
        if self.active or elapsed_seconds <= 0:
            return
        if self._host.data.get("running_mode") == RUNNING_MODE_VENTILATION:
            return
        tick = min(elapsed_seconds, self.hour_tick_cap())
        if tick <= 0:
            return
        self.accumulator.heating_seconds += tick
        self.accumulator.just_completed = False

    def _schedule_accumulator_save(self) -> None:
        """Persist soot-load counters without blocking a status callback."""
        self._host.hass.async_create_task(self._host.async_save_data())

    def observe_status(self) -> None:
        """Update soot load from a successful ECU status parse.

        Only call after a successful parse. The parse-error path forces
        running_state=0 and must not be treated as a real LCD Off.
        """
        acc = self.accumulator
        prev_step = acc.prev_step
        prev_state = acc.prev_state
        prev_mode = acc.prev_mode
        data = self._host.data
        new_step = data.get("running_step")
        new_state = data.get("running_state")
        new_mode = data.get("running_mode")

        accumulator_changed = False

        if (
            not self.active
            and prev_step is not None
            and prev_state is not None
            and not self.ha_power_off
            and prev_step in BURNOFF_HEAT_STEPS
            and new_step not in BURNOFF_HEAT_STEPS
            and new_state == RUNNING_STATE_ON
            and prev_mode != RUNNING_MODE_VENTILATION
            and new_mode != RUNNING_MODE_VENTILATION
            and new_step in (RUNNING_STEP_STANDBY, RUNNING_STEP_COOLDOWN)
        ):
            acc.cycles += 1
            acc.just_completed = False
            accumulator_changed = True
            self._host._logger.debug(
                "Burn-off cycle count %d (step %s -> %s while ON)",
                acc.cycles,
                prev_step,
                new_step,
            )

        if (
            self._host.burnoff_enabled
            and not self.active
            and prev_state == RUNNING_STATE_ON
            and new_state == RUNNING_STATE_OFF
        ):
            if self.skip_pending_on_off:
                self.skip_pending_on_off = False
            elif (
                not self.ha_power_off
                and not acc.just_completed
                and prev_mode != RUNNING_MODE_VENTILATION
                and (prev_step in BURNOFF_HEAT_STEPS or prev_step == RUNNING_STEP_COOLDOWN)
                and not acc.pending
            ):
                acc.pending = True
                accumulator_changed = True
                self._host._logger.info("LCD/controller Off while dirty: burn-off pending for next RUNNING")
            self.ha_power_off = False
        elif prev_state == RUNNING_STATE_OFF and new_state == RUNNING_STATE_ON:
            self.skip_pending_on_off = False
            self.ha_power_off = False

        acc.prev_step = new_step if isinstance(new_step, int) else None
        acc.prev_state = new_state if isinstance(new_state, int) else None
        acc.prev_mode = new_mode if isinstance(new_mode, int) else None

        if accumulator_changed:
            self.publish_accumulator()
            self._schedule_accumulator_save()

        self.maybe_start_in_run()

    def maybe_start_in_run(self) -> None:
        """Start in-run burn-off once RUNNING, or remember pending until then."""
        if not self._host.burnoff_enabled or self.active:
            return
        if self._host.burnoff_duration_minutes < 1:
            return
        if self._host.data.get("running_mode") == RUNNING_MODE_VENTILATION:
            return
        if not self.should_run_in_cycle():
            return
        # Established RUNNING only — not ignition or Auto Start/Stop standby.
        if (
            self._host.data.get("running_state") == RUNNING_STATE_ON
            and self._host.data.get("running_step") == RUNNING_STEP_RUNNING
        ):
            if self.start_scheduled:
                return
            self.start_scheduled = True
            self._host.hass.async_create_task(self.start_in_run())
            return
        # Threshold already hit (or LCD Off) but not yet RUNNING.
        if not self.accumulator.pending:
            self.accumulator.pending = True
            self.publish_accumulator()
            self._schedule_accumulator_save()

    async def start_in_run(self) -> None:
        """Start max-power burn-off without shutting down afterwards."""
        try:
            await self._host.async_start_burnoff(shutdown_after=False)
        finally:
            self.start_scheduled = False

    def _parse_ends_at(self, ends_at: Any) -> datetime | None:
        """Parse a stored ends_at value into an aware UTC datetime."""
        parsed: datetime | None = None
        if ends_at:
            parsed = dt_util.parse_datetime(ends_at)
            if not isinstance(parsed, datetime):
                try:
                    parsed = datetime.fromisoformat(str(ends_at))
                except (TypeError, ValueError):
                    parsed = None
        if parsed is not None and parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    def _phase_from_storage(self, burnoff: dict[str, Any]) -> BurnoffPhase | None:
        """Resolve a stored payload into a live phase, including legacy flags."""
        phase_raw = burnoff.get("phase")
        restoring = bool(burnoff.get("awaiting_snapshot_write", burnoff.get("restore_pending", False)))
        if phase_raw == BurnoffPhase.RESTORING or restoring:
            return BurnoffPhase.RESTORING
        if phase_raw in (
            BurnoffPhase.RUNNING,
            BurnoffPhase.AWAITING_STATUS,
        ) or burnoff.get("active"):
            # After HA reload, always wait for live ECU status before completing.
            return BurnoffPhase.AWAITING_STATUS
        return None

    async def load_state(self, burnoff: dict[str, Any] | None) -> None:
        """Restore an in-progress burn-off after Home Assistant restart."""
        if not burnoff or not burnoff.get("active"):
            return

        phase = self._phase_from_storage(burnoff)
        if phase is None:
            return

        self.cycle.phase = phase
        self.cycle.shutdown_after = bool(burnoff.get("shutdown_after", True))
        self.cycle.saved_mode = burnoff.get("saved_mode")
        self.cycle.saved_level = burnoff.get("saved_level")
        self.cycle.saved_temp = burnoff.get("saved_temp")
        saved_protocol_state = burnoff.get("saved_protocol_state")
        self.cycle.saved_protocol_state = (
            saved_protocol_state if isinstance(saved_protocol_state, dict) else None
        )
        self.cycle.ends_at = self._parse_ends_at(burnoff.get("ends_at")) or datetime.now(UTC)

        remaining = self.remaining_seconds
        self._host._logger.info(
            "Resuming in-progress burn-off (remaining=%ss, shutdown_after=%s, phase=%s)",
            remaining,
            self.cycle.shutdown_after,
            self.cycle.phase.value,
        )
        self.notify_state()
        if self.cycle.phase == BurnoffPhase.RESTORING:
            return
        if remaining is not None and remaining > 0:
            self.schedule_wait()

    def notify_state(self) -> None:
        """Push burn-off status into coordinator data for entities."""
        data = self._host.data
        data["burnoff_active"] = self.active
        data["burnoff_remaining"] = self.remaining_seconds
        self.publish_accumulator()
        self._host.async_set_updated_data(data)

    def should_run_before_shutdown(self) -> bool:
        """Return True if a shutdown request should start max-power burn-off."""
        if not self._host.burnoff_enabled:
            return False
        if self._host.burnoff_duration_minutes < 1:
            return False
        if not self.dirty():
            return False
        data = self._host.data
        if data.get("running_state") != RUNNING_STATE_ON:
            return False
        if data.get("running_mode") == RUNNING_MODE_VENTILATION:
            return False
        # Only start while actually heating. ON+STANDBY is Auto Start/Stop idle
        # and must not re-ignite at Level 10.
        return data.get("running_step") in BURNOFF_HEAT_STEPS

    def ecu_shutdown_observed(self) -> bool:
        """Return True if status shows the ECU has begun shutdown."""
        if self._host.data.get("running_state") != RUNNING_STATE_ON:
            return True
        return self._host.data.get("running_step") == RUNNING_STEP_COOLDOWN

    def ecu_can_restore(self) -> bool:
        """Return True if mode/setpoint writes are likely to stick."""
        return self._host.data.get("running_step") != RUNNING_STEP_COOLDOWN

    def schedule_abort_if_ecu_stopped(self) -> None:
        """Sync in-progress burn-off with a successful ECU status parse.

        Only call after a successful parse. The parse-error path forces
        running_state=0 and must not be treated as a real off.
        """
        if self.cycle.phase == BurnoffPhase.IDLE:
            return

        if self.cycle.phase == BurnoffPhase.RESTORING:
            if self.ecu_can_restore():
                self._host.hass.async_create_task(self.try_snapshot_write())
            return

        if self.ecu_shutdown_observed():
            if self.cancel_event.is_set():
                return
            self.cancel_event.set()
            self._host.hass.async_create_task(self.abort_on_external_shutdown())
            return

        if self.cycle.phase == BurnoffPhase.AWAITING_STATUS:
            # One-shot, same as the old awaiting-first-status flag: leave this
            # phase before the BLE work so a later parse cannot queue another
            # complete or max-power write. Cooldown is handled above.
            self.cycle.phase = BurnoffPhase.RUNNING
            remaining = self.remaining_seconds
            if remaining is None or remaining <= 0:
                self._host.hass.async_create_task(self.complete())
            else:
                self._host.hass.async_create_task(self.apply_max_power())

    async def abort_on_external_shutdown(self) -> None:
        """Cancel burn-off when the ECU stopped outside Home Assistant."""
        if not self.active:
            return
        if not self.ecu_shutdown_observed():
            return
        was_in_run = not self.cycle.shutdown_after
        nearly_done = self.nearly_complete()
        self._host._logger.info("Burn-off aborted: heater stopped externally (controller or ECU)")
        await self.cancel(restore=True)
        if not self._host.burnoff_enabled or self.skip_pending_on_off:
            return
        if nearly_done:
            self._host._logger.info("Burn-off aborted near timer end; treating as successful")
            self.reset_accumulator()
            await self._host.async_save_data()
            return
        if was_in_run:
            self.accumulator.in_run_aborts += 1
            if self.accumulator.in_run_aborts > MAX_BURNOFF_IN_RUN_ABORTS:
                self._host._logger.info(
                    "In-run burn-off aborted %d time(s); skipping further "
                    "threshold-triggered in-run until the next successful cycle",
                    self.accumulator.in_run_aborts,
                )
                self.accumulator.skip_in_run = True
                self.accumulator.pending = False
                self.publish_accumulator()
                await self._host.async_save_data()
                return
        self.accumulator.pending = True
        self.publish_accumulator()
        await self._host.async_save_data()

    def schedule_wait(self) -> None:
        """Schedule the burn-off wait as a Home Assistant background task."""
        if self.task is not None and not self.task.done():
            return
        self.cancel_event.clear()
        self.task = self._host.hass.async_create_background_task(
            self.wait(),
            name="diesel_heater_burnoff_wait",
        )

    async def wait(self) -> None:
        """Wait until burn-off ends, then restore mode and optionally power off."""
        try:
            while True:
                remaining = self.remaining_seconds
                self.notify_state()
                if remaining is None or remaining <= 0:
                    break
                try:
                    await asyncio.wait_for(
                        self.cancel_event.wait(),
                        timeout=min(remaining, 30),
                    )
                    return
                except TimeoutError:
                    continue
            if self.cancel_event.is_set():
                return
            await self.complete()
        except asyncio.CancelledError:
            self._host._logger.debug("Burn-off wait cancelled")
            raise
        except Exception:
            self._host._logger.exception("Burn-off wait failed")

    async def apply_max_power(self) -> bool:
        """Switch to Level mode and set maximum heater level."""
        self.cycle.applying = True
        try:
            return bool(await self._host.async_apply_burnoff_max_power(self.cycle))
        finally:
            self.cycle.applying = False

    async def restore_saved_mode(self) -> bool:
        """Restore the heating mode and setpoint captured before burn-off."""
        if self.cycle.saved_mode is None:
            return True
        if not self.ecu_can_restore():
            return False
        self.cycle.applying = True
        try:
            return bool(await self._host.async_restore_burnoff_snapshot(self.cycle))
        finally:
            self.cycle.applying = False

    async def clear_state(self) -> None:
        """Clear the live cycle (timer, snapshot, wait task). Leaves soot counters."""
        self.cycle = BurnoffCycle()
        self.task = None
        await self._host.async_save_data()
        self.notify_state()

    async def mark_restoring(self) -> None:
        """Remember that the snapshot still needs to be written to the ECU."""
        self.cycle.phase = BurnoffPhase.RESTORING
        # Cycle is over; remaining work is restore, not delayed Off.
        self.cycle.shutdown_after = False
        await self._host.async_save_data()
        self.notify_state()

    async def try_snapshot_write(self) -> None:
        """Write the saved mode/setpoint now that the ECU can accept settings."""
        async with self.lock:
            if self.cycle.phase != BurnoffPhase.RESTORING:
                return
            if not self.ecu_can_restore():
                return
            if await self.restore_saved_mode():
                await self.clear_state()

    async def disable(self) -> None:
        """Drop deferred in-run state and restore if a cycle is live.

        Called when the master burn-off switch is turned off.
        """
        self.accumulator.pending = False
        self.accumulator.skip_in_run = False
        self.accumulator.in_run_aborts = 0
        self.publish_accumulator()
        if self.active:
            await self.cancel(restore=True)
            return
        await self._host.async_save_data()

    async def cancel(self, *, restore: bool) -> None:
        """Cancel an in-progress burn-off, optionally restoring the previous mode."""
        if not self.active and self.task is None:
            return

        self.cancel_event.set()
        task = self.task
        self.task = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task

        async with self.lock:
            if not self.active:
                return
            if restore:
                if self.ecu_can_restore() and await self.restore_saved_mode():
                    await self.clear_state()
                    return
                await self.mark_restoring()
                return
            await self.clear_state()

    async def complete(self) -> None:
        """Finish burn-off: restore previous mode, then power off if requested."""
        async with self.lock:
            if not self.active:
                return
            # Don't send Off if the ECU already stopped (ABBA toggle would restart).
            shutdown_after = self.cycle.shutdown_after and not self.ecu_shutdown_observed()
            self._host._logger.info(
                "Burn-off complete (shutdown_after=%s, can_restore=%s)",
                shutdown_after,
                self.ecu_can_restore(),
            )
            # Soot is gone once the timer finishes, even if restore waits for cooldown.
            self.reset_accumulator()
            if not self.ecu_can_restore() or not await self.restore_saved_mode():
                await self.mark_restoring()
                return
            await self.clear_state()
        if shutdown_after:
            await self._host._power_off()

    async def start(self, *, shutdown_after: bool = True) -> None:
        """Run at max power, optionally shutting down when the timer expires."""
        async with self.lock:
            if self.active:
                if shutdown_after and not self.cycle.shutdown_after:
                    self.cycle.shutdown_after = True
                    await self._host.async_save_data()
                self._host._logger.debug("Burn-off already in progress, ignoring duplicate start")
                return

            if self._host.data.get("running_state") != RUNNING_STATE_ON:
                self._host._logger.warning("Cannot start burn-off: heater is not running")
                return

            # CBFF reports ventilation as running_mode 3. ABBA reports it as
            # running_step 6 and leaves running_mode as Level or Temperature.
            if (
                self._host.data.get("running_mode") == RUNNING_MODE_VENTILATION
                or self._host.data.get("running_step") == RUNNING_STEP_VENTILATION
            ):
                self._host._logger.warning("Cannot start burn-off while ventilating")
                return

            if self._host.data.get("running_step") not in BURNOFF_HEAT_STEPS:
                self._host._logger.warning("Cannot start burn-off: heater is not actively heating")
                return

            self.accumulator.pending = False
            self.cycle.saved_mode = self._host.data.get("running_mode")
            self.cycle.saved_level = self._host.data.get("set_level")
            self.cycle.saved_temp = self._host.data.get("set_temp")
            self.cycle.saved_protocol_state = self._host.burnoff_protocol_snapshot()
            self.cycle.shutdown_after = shutdown_after
            self.cycle.phase = BurnoffPhase.RUNNING
            duration = self._host.burnoff_duration_minutes
            self.cycle.ends_at = datetime.now(UTC) + timedelta(minutes=duration)

            self._host._logger.info(
                "Starting max-power burn-off for %d min (shutdown_after=%s, saved mode=%s level=%s temp=%s)",
                duration,
                shutdown_after,
                self.cycle.saved_mode,
                self.cycle.saved_level,
                self.cycle.saved_temp,
            )

            if not await self.apply_max_power():
                self.cycle.phase = BurnoffPhase.AWAITING_STATUS
            await self._host.async_save_data()
            self.notify_state()
            self.schedule_wait()

    async def stop_wait_task(self) -> None:
        """Cancel the wait task without changing persisted cycle state."""
        self.cancel_event.set()
        task = self.task
        self.task = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
