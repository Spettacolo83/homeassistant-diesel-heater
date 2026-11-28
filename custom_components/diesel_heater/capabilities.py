"""Hardware capabilities used by entity setup and registry reconciliation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import VevorHeaterCoordinator


# Only owned, known integration entities are eligible for automatic removal.
_ENTITY_CAPABILITIES = {
    "binary_sensor": {
        "auto_start_stop_sensor": "auto_start_stop_sensor",
        "burnoff_active": "burnoff",
        "burnoff_pending": "burnoff",
        "problem": "burnoff",
        "cronus_continuous_run": "cronus",
        "cronus_interlock": "cronus",
        "pump_active": "heatgenie",
        "fan_active": "heatgenie",
        "glow_plug_active": "heatgenie",
    },
    "switch": {
        "auto_start_stop": "auto_start_stop",
        "automatic_burnoff": "burnoff",
        "auto_offset": "auto_offset",
        "altitude_unit": "altitude_unit",
        "high_altitude": "abba",
        "temp_unit": "temp_unit",
        "timer": "timer",
        "warm_drive_max_heat": "warm_drive",
    },
    "select": {
        "backlight_select": "backlight",
        "cronus_mode": "cronus_air",
        "high_altitude_mode": "hcalory_altitude",
        "running_mode": "non_cronus",
        "language": "language",
        "pump_type": "pump_type",
        "tank_volume_select": "tank_volume",
    },
    "sensor": {
        "co_ppm": "co_sensor",
        "case_temp": "case_temperature",
        "set_level": "level_telemetry",
        "cab_temp_raw": "heater_offset",
        "heater_offset": "heater_offset",
        "hardware_version": "cbff",
        "software_version": "cbff",
        "remain_run_time": "cbff",
        "startup_temp_diff": "startup_temp_diff",
        "shutdown_temp_diff": "shutdown_temp_diff",
        "intake_temperature": "intake_temperature",
        "outlet_temperature": "outlet_temperature",
        "motor_speed": "warm_drive",
        "pump_frequency": "warm_drive",
        "fire_temperature": "warm_drive",
        "hot_water_temperature": "warm_drive_water",
        "water_temperature": "warm_drive_water",
        "cronus_air_pressure": "cronus_air",
        "cronus_mode": "cronus_water",
        "altitude": "altitude",
        "burnoff_remaining": "burnoff",
        "burnoff_cycles": "burnoff",
        "burnoff_hours": "burnoff",
        "error_code": "non_cronus",
        "running_step": "non_cronus",
        "running_mode": "non_cronus",
        "est_hourly_fuel_consumption": "fuel",
        "est_daily_fuel_consumed": "fuel",
        "est_total_fuel_consumed": "fuel",
        "est_daily_fuel_history": "fuel",
        "daily_runtime": "fuel",
        "total_runtime": "fuel",
        "daily_runtime_history": "fuel",
        "fuel_remaining": "fuel",
        "last_refueled": "fuel",
        "est_fuel_since_refuel": "fuel",
        "cronus_external_temperature": "cronus",
        "cronus_coolant_temperature": "cronus",
        "cronus_duration": "cronus",
        "cronus_max_duration": "cronus",
    },
    "fan": {"heater_level": "level_fan"},
    "number": {
        "heater_offset": "heater_offset",
        "level": "level_number",
        "target_temp": "target_temperature",
        "tank_capacity": "fuel",
        "current_fuel_level": "fuel",
        "burnoff_duration": "burnoff",
        "burnoff_after_cycles": "burnoff",
        "burnoff_after_hours": "burnoff",
    },
    "button": {
        "sync_time": "time_sync",
        "reset_est_fuel_remaining": "fuel",
        "power_off_now": "burnoff",
        "run_burnoff": "burnoff",
    },
}


def controller_capabilities(coordinator: VevorHeaterCoordinator) -> dict[str, bool | None]:
    """Resolve support from the family and validated controller data.

    A missing flag is unresolved. Zero, False and a temporary unavailable
    state are not evidence that a feature is absent.
    """
    mode = coordinator.protocol_mode
    neo = coordinator.is_dz06_neo is True
    warm_drive = neo and coordinator.is_warm_drive_controller is True
    data = coordinator.data
    cronus = mode == 9
    cronus_type = data.get("cronus_controller_type")
    warm_type = data.get("neo_controller_type")
    warm_air: bool | None = warm_drive and warm_type == "air"
    warm_water: bool | None = warm_drive and warm_type == "water"
    if warm_drive and warm_type not in ("air", "water"):
        warm_air = warm_water = None
    heatgenie = mode == 8
    hcalory = mode == 7
    abba = mode == 5 and not neo
    cbff = mode == 6
    aa66 = mode == 4
    aa_encrypted = mode in (2, 4)
    auto_stop = data.get("supports_auto_start_stop") if aa_encrypted or cbff else (abba or hcalory or warm_drive)

    # A missing Cronus model profile is an options choice, not hardware absence.
    fuel = True if not cronus or coordinator.has_cronus_fuel_estimate is True else None
    return {
        "fuel": fuel,
        "burnoff": not cronus,
        "abba": abba,
        "altitude": mode not in (7, 9),
        "altitude_unit": data.get("supports_altitude_unit") if aa_encrypted else abba or cbff,
        "auto_offset": mode in (1, 2, 3, 4, 6) and not neo,
        "auto_start_stop": auto_stop,
        "auto_start_stop_sensor": auto_stop if aa_encrypted or abba or cbff else False,
        "backlight": data.get("supports_backlight") if aa_encrypted or cbff else False,
        "case_temperature": not cronus and not neo,
        "cbff": cbff,
        "co_sensor": data.get("supports_co_sensor") if aa_encrypted or cbff or hcalory else False,
        "cronus": cronus,
        "cronus_air": cronus and cronus_type == "air",
        "cronus_water": cronus and cronus_type == "water",
        "hcalory_altitude": (
            data["high_altitude"] in (0, 1, 2)
            if hcalory and data.get("high_altitude") is not None
            else None
            if hcalory
            else False
        ),
        "heater_offset": aa_encrypted or cbff,
        "heatgenie": heatgenie,
        "intake_temperature": data.get("supports_intake_temperature") if heatgenie else False,
        "language": data.get("supports_language") if aa_encrypted or cbff else False,
        "level_fan": False if cronus else warm_air if neo else True,
        "level_telemetry": not cronus or cronus_type == "air",
        "target_temperature": not cronus or cronus_type == "air",
        "level_number": (cronus_type == "air") if cronus else not neo,
        "outlet_temperature": data.get("supports_outlet_temperature") if heatgenie else False,
        "pump_type": data.get("supports_pump_type") if aa_encrypted or cbff else warm_drive,
        "tank_volume": data.get("supports_tank_volume") if aa_encrypted or cbff else warm_drive,
        "startup_temp_diff": data.get("supports_startup_temp_diff") if cbff else False,
        "shutdown_temp_diff": data.get("supports_shutdown_temp_diff") if cbff else False,
        "non_cronus": not cronus,
        "temp_unit": data.get("supports_temp_unit") if aa66 else abba or cbff or hcalory or heatgenie,
        "time_sync": not cronus and coordinator.supports_time_sync is True,
        "timer": data.get("supports_timer") if aa_encrypted else False,
        "warm_drive": warm_drive,
        "warm_drive_water": warm_water,
    }


@callback
def async_remove_unsupported_entities(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: VevorHeaterCoordinator
) -> None:
    """Remove obsolete entity entries after this heater's setup succeeds."""
    if not coordinator.data.get("connected") or (
        coordinator.protocol_mode == 0 and coordinator.is_dz06_neo is not True
    ):
        return

    capabilities = controller_capabilities(coordinator)
    registry = er.async_get(hass)
    prefix = f"{coordinator.address}_"
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.platform != DOMAIN or not entity.unique_id.startswith(prefix):
            continue
        suffix = entity.unique_id.removeprefix(prefix)
        feature = _ENTITY_CAPABILITIES.get(entity.domain, {}).get(suffix)
        if feature is not None and capabilities[feature] is False:
            registry.async_remove(entity.entity_id)
