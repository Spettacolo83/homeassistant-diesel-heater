"""Operating-state labels shared by the mode and telemetry entities."""
from __future__ import annotations

from typing import TYPE_CHECKING, Final

from .const import (
    RUNNING_MODE_LEVEL,
    RUNNING_MODE_NAMES,
    RUNNING_MODE_TEMPERATURE,
    RUNNING_MODE_VENTILATION,
    RUNNING_STATE_OFF,
    RUNNING_STATE_ON,
    RUNNING_STEP_COOLDOWN,
    RUNNING_STEP_NAMES,
    RUNNING_STEP_STANDBY,
    RUNNING_STEP_VENTILATION,
)

if TYPE_CHECKING:
    from .coordinator import VevorHeaterCoordinator

# HeatGenie 1.1.1 store/index.js uses states 9 and 10 for Start/Stop.
_HEATGENIE_RUNNING_STEPS: Final = {
    0: "Resetting",
    1: "Ignition",
    2: "Temperature Control",
    3: "Manual Control",
    4: "Cooldown",
    5: "Standby",
    6: "Error",
    7: "Manual Fuel Pump",
    8: "Ventilation",
    9: "Start/Stop Mode",
    10: "Start/Stop Mode",
}


def reported_running_mode(coordinator: VevorHeaterCoordinator) -> str | None:
    """Return a validated mode or a known operating state."""
    data = coordinator.data
    protocol = coordinator.protocol_mode
    step = data.get("running_step")
    mode = data.get("running_mode")

    if protocol == 8:
        # HeatGenie F2 machine states are independent of its heat mode.
        raw_state = data.get("heatgenie_raw_state")
        if raw_state in (7, 8, 9, 10):
            return _HEATGENIE_RUNNING_STEPS[raw_state]

    # Hcalory also reports the fan step while starting a burn; its
    # status nibble is what identifies actual ventilation.
    neo = protocol == 0 and coordinator.is_dz06_neo is True
    if (protocol == 7 and data.get("hcalory_status") == 0xC) or (
        (protocol == 5 or neo) and step == RUNNING_STEP_VENTILATION
    ):
        return RUNNING_MODE_NAMES[RUNNING_MODE_VENTILATION]
    if mode in (RUNNING_MODE_LEVEL, RUNNING_MODE_TEMPERATURE):
        return RUNNING_MODE_NAMES[mode]
    if (
        (protocol == 6 or (protocol == 4 and coordinator.supports_aa66_ventilation))
        and mode == RUNNING_MODE_VENTILATION
        and data.get("running_state") == RUNNING_STATE_ON
    ):
        return RUNNING_MODE_NAMES[RUNNING_MODE_VENTILATION]

    # Preserve a reported heat mode above, including while the device is
    # stopped. If it reports no heat mode, show only substantiated states.
    if protocol == 7 and data.get("hcalory_status") == 0xF:
        return "Fault"
    if protocol == 8:
        if raw_state in (0, 4, 5, 6):
            return _HEATGENIE_RUNNING_STEPS[raw_state]
        return None
    if protocol in (1, 2, 3, 4, 5, 6, 7) or neo:
        if step == RUNNING_STEP_COOLDOWN:
            return RUNNING_STEP_NAMES[RUNNING_STEP_COOLDOWN]
        # AirHeaterBLE also lists its closed/Standby state at step 5.
        standby = step == RUNNING_STEP_STANDBY or (protocol in (1, 2, 3, 4) and step == 5)
        if standby and data.get("running_state") == RUNNING_STATE_OFF:
            return RUNNING_STEP_NAMES[RUNNING_STEP_STANDBY]
    return None


def reported_running_step(coordinator: VevorHeaterCoordinator) -> str | None:
    """Return the known label or the raw code when a step was reported."""
    data = coordinator.data
    protocol = coordinator.protocol_mode
    if protocol == 8:
        raw_state = data.get("heatgenie_raw_state")
        if raw_state is None:
            return None
        return _HEATGENIE_RUNNING_STEPS.get(raw_state, f"Unknown ({raw_state})")

    step = data.get("running_step")
    if step is None:
        return None
    if protocol in (1, 2, 3, 4) and step == 5:
        # AirHeaterBLE's step text identifies 5 as closed/Standby.
        return RUNNING_STEP_NAMES[RUNNING_STEP_STANDBY]
    return RUNNING_STEP_NAMES.get(step, f"Unknown ({step})")
